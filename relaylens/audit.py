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


def record_case(case_id, family, prompt, call, api, task=None, repeat=0, sequence=0):
    observed, calls, context = extract(call,api)
    row = {'id':case_id + f'@{repeat}', 'case_id':case_id,'family':family,'repeat':repeat,'sequence':sequence,
           'prompt_hash':task.prompt_hash if task else hashlib.sha256(prompt.encode()).hexdigest(),
           'completed':observed['completed'],'observed':observed,
           'answer_sha256':hashlib.sha256(observed.get('text','').encode()).hexdigest()}
    if task: grade_task(row,task)
    return row,calls,context


def grade_task(row,task):
    row['prompt_hash'] = task.prompt_hash
    row['difficulty'] = task.metadata.get('difficulty','standard')
    row['input_chars'] = len(task.prompt)
    try:
        row['grade'] = task.grade(row.get('observed',{}).get('text',''))
        if not isinstance(row['grade'],dict) or type(row['grade'].get('passed')) is not bool:
            raise ValueError('grader must return a boolean passed field')
    except Exception as exc:
        row['grade'] = {'passed':False,'format_passed':False,'reason':'grader_error','error':type(exc).__name__}


def run_tool(client, model, api, effort, stream, seed, add, repeat=0):
    tool,prompt,result = make_tool_case(seed)
    observed,calls,context = add('tool-initial','tool',prompt,client.call(model,prompt,tools=[tool],effort=effort),repeat=repeat)
    detected = observed['completed'] and len(calls)==1 and calls[0].get('name')==tool['name'] and bool(calls[0].get('call_id'))
    used, completed = False, False
    selected = calls[0] if detected else None
    if selected:
        try:
            arguments = strict_json(selected.get('arguments','{}'))
        except (TypeError,ValueError):
            arguments = {}
        detected = detected and exact(arguments, {'city':result['city']})
        if api == 'responses':
            follow_context = [{'role':'user','content':prompt}] + (context or []) + [{'type':'function_call_output','call_id':selected['call_id'],'output':json.dumps(result)}]
        elif api == 'messages':
            follow_context = [{'role':'user','content':prompt},context,{'role':'user','content':[{'type':'tool_result','tool_use_id':selected['call_id'],'content':json.dumps(result)}]}]
        else:
            follow_context = [{'role':'user','content':prompt},context,{'role':'tool','tool_call_id':selected['call_id'],'content':json.dumps(result)}]
        follow,_,_ = add('tool-followup','tool_followup',prompt,client.call(model,None,context=follow_context,tools=[tool],effort=effort,stream=stream),repeat=repeat)
        completed = follow['completed']
        try:
            used = completed and exact(strict_json(follow.get('text','')),result)
        except (TypeError,ValueError):
            used = False
    return {'call_detected':detected,'followup_completed':completed,'result_used':bool(detected and used)}


GRADE_GUIDE = {
    'A':'符合官方参考：同配置能力差距在预设容差内。',
    'B':'关键检查通过：本轮表现正常，尚未完成目标型号认证。',
    'C':'存在疑点：关键题、参数、工具或行为出现异常。',
    'D':'明显不符合目标参考：能力显著低于已核实的官方对照。',
    'U':'检测未完成：样本不足、连接失败或超时，不能判定真假。',
}


def verdict(report):
    cases = report.get('cases',[])
    graded = [r for r in cases if 'grade' in r]
    quality = quality_profile(cases)
    n = len(graded); completed = sum(bool(r.get('completed')) for r in graded)
    passed = sum(bool(r.get('completed') and r['grade'].get('passed')) for r in graded)
    tool = report.get('tool_summary',{})
    expected_tool = tool_expected(report.get('target_model'),report.get('api_style'))
    tool_ok = all(tool.get(k) for k in ('call_detected','followup_completed','result_used'))
    parameters = [r for r in cases if r.get('family')=='parameter']
    parameter_ok = all(r.get('completed') and r.get('observed',{}).get('exact_instruction_followed') is True for r in parameters)
    comp = report.get('reference_comparison',{})
    calibrated = comp.get('capability_calibrated',False)
    result = {'grade':'C','label':'存在疑点','identity_claim':'not established','capability_status':'uncalibrated',
              'task_accuracy':passed/n if n else None,'reasons':[], 'grade_guide':GRADE_GUIDE,
              'action':'先查看失败项并复测；确认前不建议把它当作所选型号长期使用。'}
    result['reasons'].append(f'关键题通过 {passed}/{n}，完整回答 {completed}/{n}。')
    if n>=8 and passed==n and (tool_ok or not expected_tool) and parameter_ok:
        result.update(grade='B',label='关键检查通过',action='本轮表现正常，可先试用；确认具体型号需增加同配置官方对照。')
    elif n and passed<n:
        result['reasons'].append(f'{n-passed} 道题未通过；其中 {quality.get("format_only_failures",0)} 道仅为输出格式问题。')
        result['capability_status']='low_on_this_suite' if passed/n<.5 else 'issues_on_this_suite'
        result['label']='关键题未全部通过'
    if calibrated and comp.get('status')=='below_reference':
        result.update(grade='D',label='明显低于目标参考',capability_status='below_reference',
                      action='不建议按所选型号使用或付费；保留报告，核对渠道后再复测。')
        result['reasons'].append('同题、同配置的比较显示能力差距超过预设容差。')
    elif calibrated and comp.get('status')=='within_margin' and (tool_ok or not expected_tool) and parameter_ok:
        result.update(grade='A',label='符合官方参考',capability_status='within_reference_margin',
                      action='本次能力符合所选模型的可信参考，可按本次配置使用。')
        result['reasons'].append('已核实的官方参考对照通过，能力差距在预设容差内。')
    if expected_tool and not tool_ok:
        result['reasons'].append('工具调用未完成闭环；可能是接口适配或模型行为问题。')
        if result['grade']=='C': result['label']='工具或能力检查存在疑点'
    if not parameter_ok:
        result['reasons'].append('参数或精确指令探针未通过，请检查 API 格式和思考档。')
    drift = any(r.get('target_model')==report.get('target_model') and r.get('trusted_by_operator') and
                 r.get('status')=='distribution_shift' for r in report.get('numeric_reference_panel',{}).get('comparisons',[]))
    if drift:
        if result['grade'] in ('A','B'):
            result.update(grade='C',label='能力通过，但行为存在疑点',action='排查系统提示、采样或路由变化后复测，暂不确认型号。')
        result['reasons'].append('数字行为与可信目标参考有显著差异。')
    if n<8 or completed/n<.9 or (calibrated and comp.get('status')=='service_degradation'):
        reason='样本不足' if n<8 else '请求未完整完成'
        result.update(grade='U',label='检测未完成 · '+reason,
                      capability_status='insufficient_samples' if n<8 else 'service_degradation',
                      action='先检查地址、接口、Key 或超时，再运行快检；当前不能判定模型真假。')
    if report.get('run_state',{}).get('end_reason') in ('budget_exhausted','interrupted'):
        result['reasons'].append('已保存已完成的结果；剩余检查因时间上限或手动中止而停止。')
    result['summary'] = GRADE_GUIDE[result['grade']]
    result['limitations'] = ['等级表示本次能力和行为证据，不是模型身份概率；A/D 都不等于百分百真/假。',
                             '结论只适用于本批题目、设置和时段；高分也可能是题目对多个模型都足够容易。']
    return result


def run(args):
    args.api_key = args.api_key or os.environ.get('RELAYLENS_API_KEY') or os.environ.get('RELAY_API_KEY') or os.environ.get('T8_API_KEY') or getpass.getpass('API Key（隐藏输入）: ').strip()
    started = time.monotonic()
    fn, suite_version, suite_source, commitment = load_suite(args.suite_module,pack=args.pack,context_records=args.context_records)
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1, 2**63)
    target_id = args.target_model or (args.model if profile(args.model) else None)
    if args.target_model and not profile(args.target_model):
        raise ValueError('目标型号应为 gpt-* 或 claude-*；--model 可填写中转站自定义 ID。')
    efforts = args.efforts if args.efforts is not None else ([args.task_effort] if args.mode=='fast' else list(known_efforts(target_id,args.api) or ('high',)))
    settings = {'task_effort':args.task_effort,'max_output_tokens':args.max_output_tokens,'stream':args.stream,
                'repeats':args.repeats,'task_rounds':args.task_rounds,'fingerprint_samples':args.fingerprint_samples,
                'fingerprint_temperature':args.fingerprint_temperature,'efforts':efforts,
                'numeric_samples':args.numeric_samples,'numeric_version':NUMERIC_VERSION,
                'pack':args.pack,'context_records':args.context_records if args.pack in ('challenge','fast') else None,
                'mode':args.mode,'concurrency':args.concurrency if args.mode=='fast' else 1,
                'chat_token_field':args.chat_token_field if args.api=='chat' else None}
    client = Client(args.base_url,args.api_key,api=args.api,route=args.route,proxy=args.proxy,
                    timeout=args.timeout,max_tokens=args.max_output_tokens,chat_token_field=args.chat_token_field)
    report = {'schema_version':'0.8','tool_version':__version__,'suite_version':suite_version,'suite_source':suite_source,'suite_commitment':commitment,
              'run_id':str(uuid.uuid4()),'started_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'base_url':client.base,
              'api_style':args.api,'model_requested':args.model,'target_model':target_id,'target':profile(target_id),
              'seed':seed,'settings':settings,'network':{'route':args.route,'proxy_configured':bool(args.proxy)},'cases':[]}
    if args.mode=='fast':
        from .fast_runner import collect
        collect(args,report,fn(seed,args.task_rounds) if args.task_rounds else [])
        return finalize_report(report)
    if args.egress and not args.no_egress:
        try:
            # Independent geo lookup receives no API authentication header.
            req = urllib.request.Request('https://ipinfo.io/json',headers={'User-Agent':'RelayLens/0.6.0'})
            with client.opener.open(req,timeout=args.timeout) as response:
                report['egress'] = json.loads(response.read().decode('utf-8'))
        except Exception as exc:
            report['egress'] = {'error':type(exc).__name__ + ': ' + str(exc)}
    sequence = 0

    def add(case_id, family, prompt, call, task=None, repeat=0):
        nonlocal sequence
        sequence += 1
        row,calls,context = record_case(case_id,family,prompt,call,args.api,task,repeat,sequence)
        report['cases'].append(row)
        if args.progress:
            print(f'[{sequence}] {family} / {case_id} / {"完成" if row["completed"] else "失败"}',flush=True)
        return row['observed'],calls,context

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
    tool_results = [run_tool(client,args.model,args.api,args.task_effort,args.stream,seed+repeat,add,repeat)
                    for repeat in range(args.repeats)]
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
    report['run_state']={'mode':'full','end_reason':'completed','elapsed_seconds':round(time.monotonic()-started,2)}
    return finalize_report(report)


def finalize_report(report):
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
    p.add_argument('--mode',choices=('fast','full'),default='full',help='fast=8题并行限时快检；full=完整自定义检测。双击向导默认fast')
    p.add_argument('--advanced',action='store_true',help='进入向导高级设置')
    p.add_argument('--time-budget',type=float,default=180,help='快速模式总采集时限，默认180秒；完整模式不受此限制')
    p.add_argument('--concurrency',type=int,default=4,help='快速模式并行请求进程数，默认4')
    p.add_argument('--seed',type=int); p.add_argument('--task-rounds','--logic-rounds',dest='task_rounds',type=int)
    p.add_argument('--quick',action='store_true',help='旧入口兼容：只做一个参数探针和工具烟测')
    p.add_argument('--repeats',type=int,default=1,help='同一组题重复次数；3 次起可观察同题波动')
    p.add_argument('--task-effort',default='high',choices=EFFORTS)
    p.add_argument('--suite-module',help='本地私有题库模块，提供 suite(seed, rounds)')
    p.add_argument('--pack',choices=('standard','challenge','fast'),help='fast精选8题；standard标准8类；challenge完整14类')
    p.add_argument('--context-records',type=int,help='上下文记录数，>=32；快检默认128，完整默认1024')
    p.add_argument('--efforts',nargs='+',choices=EFFORTS,help='参数探针；默认采用目标的文档支持档位')
    p.add_argument('--stream',action=argparse.BooleanOptionalAction,default=None); p.add_argument('--progress',action='store_true')
    p.add_argument('--fingerprint-samples',type=int,default=0,help='每种短回答探针采样数，5种；20起可做分布检验')
    p.add_argument('--fingerprint-temperature',type=float,help='可选；只在端点支持时设置，参考须相同')
    p.add_argument('--numeric-samples',type=int,default=0,help='可选数字序列探针请求数；3次预览、30次起与同配置参考做统计检验；额外计费')
    p.add_argument('--timeout',type=float); p.add_argument('--max-output-tokens',type=int)
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
    defaults={'pack':'fast' if args.mode=='fast' else 'standard','task_rounds':1 if args.mode=='fast' else 3,
              'context_records':128 if args.mode=='fast' else 1024,'timeout':180 if args.mode=='fast' else 60,
              'max_output_tokens':32768 if args.mode=='fast' else 1200,'stream':args.mode=='fast'}
    for key,value in defaults.items():
        if getattr(args,key) is None: setattr(args,key,value)
    if not args.model:
        p.error('--model is required')
    if args.quick:
        args.mode='full'
        args.task_rounds, args.repeats, args.efforts, args.fingerprint_samples = 0, 1, ['high'], 0
        args.numeric_samples = 0
    if args.task_rounds < 0 or args.repeats < 1 or args.fingerprint_samples < 0 or args.numeric_samples < 0 or not 0 < args.loss_margin < 1:
        p.error('rounds/samples >= 0, repeats >= 1, 0 < loss-margin < 1 required')
    if args.task_effort not in EFFORTS or args.max_output_tokens < 1 or args.timeout <= 0:
        p.error('请选择支持的 task-effort，且 timeout/max-output-tokens 必须为正数')
    if args.context_records < 32: p.error('context-records must be >=32')
    if not __import__('math').isfinite(args.time_budget) or args.time_budget<=0 or args.concurrency<1:
        p.error('time-budget必须为有限正数，concurrency必须>=1')
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
    if args.progress or args.interactive:
        result=report['verdict']
        print(f'\n检测结果：{result["label"]}' + (f'（{result["grade"]}）' if result['grade']!='U' else ''))
        print(result.get('summary',''))
        print('下一步：'+result.get('action','查看报告'))
        print('报告已保存：'+str(Path(args.out).resolve()))
    else:
        print(json.dumps({'report':str(Path(args.out).resolve()),'target_model':report['target_model'],
                          'verdict':report['verdict'],'task_summary':report.get('task_summary',{}),
                          'stability':report.get('diagnostics',{}).get('stability',{})},ensure_ascii=False,indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
