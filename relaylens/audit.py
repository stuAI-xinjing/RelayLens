"""Reproducible multi-signal audits of GPT and Claude gateway claims."""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import random
import time
import urllib.request
import uuid
from pathlib import Path

from . import __version__
from .evidence import diagnostics, quality_profile, checked_rows
from .comparison import apply_comparisons, read_report
from .grading import exact, strict_json
from .model_targets import TARGETS, known_efforts, profile, tool_expected
from .privacy import private_report
from .stats import summary
from .suite_loader import load_suite
from .transport import Client, extract
from .numeric_fingerprint import VERSION as NUMERIC_VERSION, prompts as numeric_prompts, describe as describe_numeric

EFFORTS = ('omit', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
FINGERPRINTS = (
    'Choose a random integer between 1 and 100. Output only the integer.',
    'Name one color in English. Output only one lowercase word.',
    'Choose a random uppercase letter from A through Z. Output only the letter.',
    'Name one animal in English. Output only one lowercase word.',
    'Choose heads or tails. Output only one lowercase word.',
)


def make_tool_case(seed):
    rng = random.Random(seed ^ 0x5EEDC0DE)
    name = f'lookup_{rng.getrandbits(32):08x}'
    city, temperature, condition = rng.choice((('Paris',17,'clear'),('Osaka',23,'humid'),('Quito',14,'cloudy'),('Reykjavik',6,'windy')))
    tool = {'type':'function','name':name,'description':'Return the temperature and condition for a city.',
            'parameters':{'type':'object','properties':{'city':{'type':'string'}},'required':['city'],'additionalProperties':False},'strict':True}
    return tool, f'Call {name} for {city}, then return ONLY the exact JSON object from the tool, including every field and its type.', {'city':city,'temperature_c':temperature,'condition':condition,'receipt':f'{rng.getrandbits(80):020x}'}


def verdict(report):
    cases = report.get('cases',[])
    completed = [r for r in cases if r.get('completed')]
    graded = [r for r in cases if 'grade' in r]
    rate = sum(bool(r.get('completed') and r['grade'].get('passed')) for r in graded)/len(graded) if graded else None
    tool = report.get('tool_summary',{})
    expected_tool = tool_expected(report.get('target_model'),report.get('api_style'))
    tool_ok = all(tool.get(k) for k in ('call_detected','followup_completed','result_used'))
    comp = report.get('reference_comparison',{})
    calibrated = comp.get('capability_calibrated',False)
    result = {'grade':'B', 'label':'已完成基础检测；目标能力待参考校准',
              'identity_claim':'not established', 'capability_status':'uncalibrated',
              'task_accuracy':rate, 'reasons':[]}
    if not completed:
        result.update(grade='D',label='未获得可用回答',capability_status='unavailable')
    elif rate is not None and rate < .5:
        result.update(grade='C',label='基础任务表现偏低',capability_status='low_on_this_suite')
    quality = quality_profile(cases)
    if quality.get('completion_rate') is not None and quality['completion_rate'] < .9:
        result.update(grade='C',label='接口可用性或输出完整性不足；能力判断受干扰',capability_status='service_degradation')
    if not tool_ok:
        result['reasons'].append('工具闭环未通过；检查接口适配和原始错误。' if expected_tool else
                                 '官方文档中此型号的 Chat 接口不支持工具调用；已保留探针结果，能力判定不以它为前提。可使用 Responses 测工具。')
    if report.get('model_requested') not in report.get('models',{}).get('ids',[]):
        result['reasons'].append('模型目录未列出请求 ID；目录及返回名称仅为服务方声明。')
    if calibrated and comp.get('status') == 'below_reference':
        result.update(grade='C',label='本套题能力显著低于可信目标参考',capability_status='below_reference')
    elif calibrated and comp.get('status') == 'within_margin' and result['grade'] == 'B' and (tool_ok or not expected_tool):
        result.update(grade='A',label='本套题与可信目标参考的能力差距在容差内',capability_status='within_reference_margin')
    elif calibrated and comp.get('status') == 'service_degradation':
        result.update(grade='C',label='含失败请求的表现低于参考；尚不能归因为模型变弱',capability_status='service_degradation')
    elif comp:
        result['reasons'].append('参考比较：' + comp.get('status','error') + ('；尚未声明参考可信' if not comp.get('trusted_by_operator') else ''))
    result['limitations'] = ['A 也只适用于本套题、设置和时段。黑盒结果不能证明权重身份，也不能排除按请求混用。',
                             '速度、模型名、reasoning token、自报身份和文风均不能单独证明真伪。']
    if rate is not None and rate >= .95:
        result['reasons'].append('本套题接近满分，可能缺乏区分度；请检查挑战题和多个可信型号参考是否仍同分。')
    if any(r.get('target_model')==report.get('target_model') and r.get('trusted_by_operator') and
           r.get('status')=='distribution_shift' for r in report.get('numeric_reference_panel',{}).get('comparisons',[])):
        result['reasons'].append('数字序列行为与可信目标参考有显著差异；需排查采样、系统提示和路由变化，不能直接认定是假模型。')
    return result


def run(args):
    args.api_key = args.api_key or os.environ.get('RELAYLENS_API_KEY') or os.environ.get('RELAY_API_KEY') or os.environ.get('T8_API_KEY') or getpass.getpass('API Key（隐藏输入）: ').strip()
    fn, suite_version, suite_source, commitment = load_suite(args.suite_module,pack=args.pack,context_records=args.context_records)
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1, 2**63)
    target_id = args.target_model or (args.model if profile(args.model) else None)
    if args.target_model and not profile(args.target_model):
        raise ValueError('目标型号应为 gpt-* 或 claude-*；--model 可填写中转站自定义 ID。')
    efforts = args.efforts if args.efforts is not None else list(known_efforts(target_id,args.api) or ('high',))
    settings = {'task_effort':args.task_effort,'max_output_tokens':args.max_output_tokens,'stream':args.stream,
                'repeats':args.repeats,'task_rounds':args.task_rounds,'fingerprint_samples':args.fingerprint_samples,
                'fingerprint_temperature':args.fingerprint_temperature,'efforts':efforts,
                'numeric_samples':args.numeric_samples,'numeric_version':NUMERIC_VERSION,
                'pack':args.pack,'context_records':args.context_records if args.pack=='challenge' else None,
                'chat_token_field':args.chat_token_field if args.api=='chat' else None}
    client = Client(args.base_url,args.api_key,api=args.api,route=args.route,proxy=args.proxy,
                    timeout=args.timeout,max_tokens=args.max_output_tokens,chat_token_field=args.chat_token_field)
    report = {'schema_version':'0.7','tool_version':__version__,'suite_version':suite_version,'suite_source':suite_source,'suite_commitment':commitment,
              'run_id':str(uuid.uuid4()),'started_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'base_url':client.base,
              'api_style':args.api,'model_requested':args.model,'target_model':target_id,'target':profile(target_id),
              'seed':seed,'settings':settings,'network':{'route':args.route,'proxy_configured':bool(args.proxy)},'cases':[]}
    if args.egress and not args.no_egress:
        try:
            # Independent geo lookup receives no API authentication header.
            req = urllib.request.Request('https://ipinfo.io/json',headers={'User-Agent':'RelayLens/0.5.1'})
            with client.opener.open(req,timeout=args.timeout) as response:
                report['egress'] = json.loads(response.read().decode('utf-8'))
        except Exception as exc:
            report['egress'] = {'error':type(exc).__name__ + ': ' + str(exc)}
    sequence = 0

    def add(case_id, family, prompt, call, task=None, repeat=0):
        nonlocal sequence
        observed, calls, context = extract(call,args.api)
        sequence += 1
        row = {'id':case_id + f'@{repeat}', 'case_id':case_id,'family':family,'repeat':repeat,'sequence':sequence,
               'prompt_hash':task.prompt_hash if task else hashlib.sha256(prompt.encode()).hexdigest(),
               'completed':observed['completed'],'observed':observed,
               'answer_sha256':hashlib.sha256(observed.get('text','').encode()).hexdigest()}
        if task:
            row['difficulty'] = task.metadata.get('difficulty','standard')
            row['input_chars'] = len(task.prompt)
            try:
                row['grade'] = task.grade(observed.get('text',''))
                if not isinstance(row['grade'],dict) or type(row['grade'].get('passed')) is not bool:
                    raise ValueError('grader must return a boolean passed field')
            except Exception as exc:
                row['grade'] = {'passed':False,'format_passed':False,'reason':'grader_error','error':type(exc).__name__}
        report['cases'].append(row)
        if args.progress:
            print(f'[{sequence}] {family} / {case_id} / {"完成" if observed["completed"] else "失败"}',flush=True)
        return observed,calls,context

    models = client.request('/models')
    md = models.get('data')
    md = md if isinstance(md,dict) else {}
    report['models'] = {k:models.get(k) for k in ('http_status','transport_state','latency_ms','error')}
    report['models']['ids'] = [r.get('id') for r in md.get('data',[]) if isinstance(r,dict)]
    for effort in efforts:
        prompt = 'Reply with exactly the token RELAYLENS_OK.'
        observed,_,_ = add('parameter-'+effort,'parameter',prompt,client.call(args.model,prompt,effort=effort,stream=args.stream))
        supported = known_efforts(target_id,args.api)
        observed['requested_effort'] = effort
        observed['documented_support'] = None if supported is None else effort in supported
        observed['exact_instruction_followed'] = observed.get('text','').strip() == 'RELAYLENS_OK'
    tasks = fn(seed,args.task_rounds) if args.task_rounds else []
    for repeat in range(args.repeats):
        shuffled = tasks[:]
        random.Random(seed + 31 + repeat).shuffle(shuffled)
        for task in shuffled:
            add(task.id,task.family,task.prompt,client.call(args.model,task.prompt,effort=args.task_effort,stream=args.stream),task,repeat)
    tool_results = []
    for repeat in range(args.repeats):
        tool,prompt,result = make_tool_case(seed+repeat)
        observed,calls,context = add('tool-initial','tool',prompt,client.call(args.model,prompt,tools=[tool],effort=args.task_effort),repeat=repeat)
        detected = observed['completed'] and len(calls)==1 and calls[0].get('name')==tool['name'] and bool(calls[0].get('call_id'))
        used, completed = False, False
        selected = calls[0] if detected else None
        if selected:
            try:
                arguments = strict_json(selected.get('arguments','{}'))
            except (TypeError,ValueError):
                arguments = {}
            detected = detected and exact(arguments, {'city':result['city']})
            if args.api == 'responses':
                follow_context = [{'role':'user','content':prompt}] + (context or []) + [{'type':'function_call_output','call_id':selected['call_id'],'output':json.dumps(result)}]
            elif args.api == 'messages':
                follow_context = [{'role':'user','content':prompt},context,{'role':'user','content':[{'type':'tool_result','tool_use_id':selected['call_id'],'content':json.dumps(result)}]}]
            else:
                follow_context = [{'role':'user','content':prompt},context,{'role':'tool','tool_call_id':selected['call_id'],'content':json.dumps(result)}]
            follow,_,_ = add('tool-followup','tool_followup',prompt,client.call(args.model,None,context=follow_context,tools=[tool],effort=args.task_effort,stream=args.stream),repeat=repeat)
            completed = follow['completed']
            try:
                used = completed and exact(strict_json(follow.get('text','')),result)
            except (TypeError,ValueError):
                used = False
        tool_results.append({'call_detected':detected,'followup_completed':completed,'result_used':bool(detected and used)})
    report['tool_summary'] = {k:all(r[k] for r in tool_results) for k in ('call_detected','followup_completed','result_used')}
    report['tool_summary']['rounds'] = tool_results
    report['tool_summary']['documented_expectation'] = tool_expected(target_id,args.api)
    jobs = [(i,j) for i in range(len(FINGERPRINTS)) for j in range(args.fingerprint_samples)]
    random.Random(seed ^ 9127).shuffle(jobs)
    for i,j in jobs:
        prompt = FINGERPRINTS[i]
        add(f'fingerprint-{i}','fingerprint',prompt,client.call(args.model,prompt,effort=args.task_effort,
            temperature=args.fingerprint_temperature,stream=args.stream),repeat=j)
    probes = numeric_prompts(seed,args.numeric_samples)
    random.Random(seed ^ 31271).shuffle(probes)
    for probe in probes:
        add(f'numeric-sequence-{probe["index"]}','numeric_fingerprint',probe['prompt'],
            client.call(args.model,probe['prompt'],effort=args.task_effort,
                        temperature=args.fingerprint_temperature,stream=args.stream))
        report['cases'][-1]['numeric_index'] = probe['index']
    report['numeric_summary'] = describe_numeric(report)
    report['task_summary'] = summary(report['cases'])
    report['diagnostics'] = diagnostics(report['cases'])
    report['quality_profile'] = quality_profile(report['cases'])
    report['verdict'] = verdict(report)
    report['privacy_note'] = 'Public exports scrub keys, URLs, IPs, local paths and answer text. Full local reports retain answers for review.'
    return report


def main(argv=None):
    p = argparse.ArgumentParser(prog='relaylens',description='GPT/Claude 中转站能力、稳定性和行为核验')
    p.add_argument('--base-url'); p.add_argument('--model'); p.add_argument('--api-key')
    p.add_argument('--target-model',help='声称的 GPT/Claude 目标型号；可与中转模型 ID 不同')
    p.add_argument('--list-targets',action='store_true'); p.add_argument('--interactive',action='store_true')
    p.add_argument('--api',choices=('responses','chat','messages'),default='responses')
    p.add_argument('--chat-token-field',choices=('max_completion_tokens','max_tokens'),default='max_completion_tokens',help='Chat输出预算字段；旧网关可显式选max_tokens')
    p.add_argument('--route',choices=('env','direct'),default='env'); p.add_argument('--proxy')
    p.add_argument('--seed',type=int); p.add_argument('--task-rounds','--logic-rounds',dest='task_rounds',type=int,default=3)
    p.add_argument('--quick',action='store_true',help='旧入口兼容：只做一个参数探针和工具烟测')
    p.add_argument('--repeats',type=int,default=1,help='同一组题重复次数；3 次起可观察同题波动')
    p.add_argument('--task-effort',default='high',choices=EFFORTS)
    p.add_argument('--suite-module',help='本地私有题库模块，提供 suite(seed, rounds)')
    p.add_argument('--pack',choices=('standard','challenge'),default='standard',help='standard保留8类；challenge加入6类复杂/前后端/上下文题')
    p.add_argument('--context-records',type=int,default=1024,help='challenge上下文记录数，>=32；报告使用字符数和实际usage，不假称token数')
    p.add_argument('--efforts',nargs='+',choices=EFFORTS,help='参数探针；默认采用目标的文档支持档位')
    p.add_argument('--stream',action='store_true'); p.add_argument('--progress',action='store_true')
    p.add_argument('--fingerprint-samples',type=int,default=0,help='每种短回答探针采样数，5种；20起可做分布检验')
    p.add_argument('--fingerprint-temperature',type=float,help='可选；只在端点支持时设置，参考须相同')
    p.add_argument('--numeric-samples',type=int,default=0,help='可选数字序列探针请求数；3次预览、30次起与同配置参考做统计检验；额外计费')
    p.add_argument('--timeout',type=float,default=60); p.add_argument('--max-output-tokens',type=int,default=1200)
    p.add_argument('--out',default='relaylens-report.json'); p.add_argument('--public-out'); p.add_argument('--html-out')
    p.add_argument('--open-report',action='store_true'); p.add_argument('--no-egress',action='store_true')
    p.add_argument('--egress',action='store_true',help='可选查询 ipinfo.io 的本次网络出口信息')
    p.add_argument('--reference-report',help='相同配置的可信官方 JSON 报告')
    p.add_argument('--reference-dir',help='多个 GPT/Claude 官方参考 JSON 所在目录')
    p.add_argument('--compare-report',help='离线重新比较已有报告，不调用API、不需要Key')
    p.add_argument('--trust-reference',action='store_true',help='你已自行核实参考报告来自所选官方模型；程序无法认证导入文件')
    p.add_argument('--loss-margin',type=float,default=.10,help='允许的参考能力损失比例，默认0.10')
    args = p.parse_args(argv)
    if args.list_targets:
        print('\n'.join(f'{k}: {v["label"]} ({v["tier"]})' for k,v in TARGETS.items()))
        return 0
    if args.compare_report:
        if not 0 < args.loss_margin < 1: p.error('0 < loss-margin < 1 required')
        report = read_report(args.compare_report)
        if any('grade' in r for r in report.get('cases',[]) if isinstance(r,dict)):
            checked_rows(report)
        elif not report.get('settings',{}).get('numeric_samples'):
            p.error('报告没有任务评分或数字探针')
        # Imported previous claims are never trusted or carried forward.
        report.pop('reference_panel',None); report.pop('reference_comparison',None)
        report.pop('numeric_reference_panel',None)
        report['numeric_summary'] = describe_numeric(report)
        report['quality_profile'] = quality_profile(report.get('cases',[]))
        apply_comparisons(report,[args.reference_report] if args.reference_report else [],args.reference_dir,
                          trusted=args.trust_reference,margin=args.loss_margin)
        report['verdict'] = verdict(report)
        return save_report(report,args)
    if args.interactive or not args.base_url:
        from .wizard import configure
        args = configure(args)
    if not args.model:
        p.error('--model is required')
    if args.quick:
        args.task_rounds, args.repeats, args.efforts, args.fingerprint_samples = 0, 1, ['high'], 0
        args.numeric_samples = 0
    if args.task_rounds < 0 or args.repeats < 1 or args.fingerprint_samples < 0 or args.numeric_samples < 0 or not 0 < args.loss_margin < 1:
        p.error('rounds/samples >= 0, repeats >= 1, 0 < loss-margin < 1 required')
    if args.task_effort not in EFFORTS or args.max_output_tokens < 1 or args.timeout <= 0:
        p.error('请选择支持的 task-effort，且 timeout/max-output-tokens 必须为正数')
    if args.context_records < 32: p.error('context-records must be >=32')
    report = run(args)
    if args.reference_report or args.reference_dir:
        apply_comparisons(report,[args.reference_report] if args.reference_report else [],args.reference_dir,
                          trusted=args.trust_reference,margin=args.loss_margin)
        report['verdict'] = verdict(report)
    return save_report(report,args)


def save_report(report,args):
    # Scrub secrets even in local reports; retain the local endpoint and answers.
    from .reporting import clean_local, write_html
    report = clean_local(report, (args.api_key or '',))
    Path(args.out).parent.mkdir(parents=True,exist_ok=True)
    Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if args.public_out:
        public = private_report(report,(args.api_key or '',))
        for row in public.get('cases',[]):
            row.get('observed',{}).pop('text',None)
        Path(args.public_out).parent.mkdir(parents=True,exist_ok=True)
        Path(args.public_out).write_text(json.dumps(public,ensure_ascii=False,indent=2),encoding='utf-8')
    if args.html_out or args.open_report:
        html_path = args.html_out or str(Path(args.out).with_suffix('.html'))
        write_html(report,html_path)
        if args.open_report:
            import webbrowser
            webbrowser.open(Path(html_path).resolve().as_uri())
    print(json.dumps({'report':str(Path(args.out).resolve()),'target_model':report['target_model'],
                      'verdict':report['verdict'],'task_summary':report.get('task_summary',{}),
                      'stability':report.get('diagnostics',{}).get('stability',{})},ensure_ascii=False,indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
