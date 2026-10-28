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
from .content_review import review_grade, review_report, content_passed
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
        row['grade'] = review_grade(task,row.get('observed',{}).get('text',''),row['grade'])
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
    'S':'可信同题对照显示优于所选模型参考；结论限于本套题与本配置。',
    'A':'本轮能力达标：关键能力表现优秀，值得按实际用途试用。',
    'B':'基本可用：大部分题目通过，但有短板或高阶覆盖不足。',
    'C':'能力存疑：多项任务未通过，暂不建议按目标档位付费。',
    'D':'能力明显不足：本轮多数题未通过，或显著低于可信目标参考。',
    'U':'检测未完成：有效题数或完成率不足，先处理连接和超时。',
}


def verdict(report):
    cases = report.get('cases',[])
    graded = [r for r in cases if 'grade' in r]
    quality = quality_profile(cases)
    n = len(graded); completed = sum(bool(r.get('completed')) for r in graded)
    passed = sum(content_passed(r) for r in graded)
    accuracy = passed/n if n else 0
    unique = {r.get('prompt_hash') for r in graded if r.get('prompt_hash')}
    challenge = {r.get('prompt_hash') for r in graded if r.get('prompt_hash') and r.get('difficulty')=='challenge'}
    family_scores = {}
    for row in graded:
        family_scores.setdefault(row['family'],[]).append(content_passed(row))
    coverage_ok = len(family_scores)>=6 and len(challenge)>=4
    family_floor = min((sum(v)/len(v) for v in family_scores.values()),default=0)
    comp = report.get('reference_comparison',{})
    calibrated = comp.get('capability_calibrated',False)
    result = {'grade':'C','label':'能力存疑','identity_claim':'not established','capability_status':'issues_on_this_suite',
              'rating_policy':'target-separated-2','evidence_basis':'task_screen',
              'basis_label':'本轮能力筛查','task_accuracy':passed/n if n else None,
              'target_assessment':'尚无充分的同配置官方对照；本等级表示本轮能力表现。',
              'coverage':{'unique_questions':len(unique),'families':len(family_scores),'challenge_questions':len(challenge)},
              'reasons':[f'内容完全正确 {passed}/{n}，严格格式通过 {sum(bool(r.get("completed") and r["grade"].get("passed")) for r in graded)}/{n}，完整回答 {completed}/{n}。'], 'grade_guide':GRADE_GUIDE,
              'action':'先核对失败项并复测；目前不建议按所选型号的档位付费。'}
    # These are disclosed operational thresholds, not model-specific IQ cutoffs
    # or probabilities. Same-prompt repeats cannot supply missing coverage.
    if accuracy>=.9 and coverage_ok and family_floor>=.75:
        result.update(grade='A',label='本轮能力达标，值得试用',capability_status='strong_on_this_suite',
                      action='建议先用于你的实际任务；若表现稳定且费用合适，可继续使用。')
    elif accuracy>=.75:
        result.update(grade='B',label='基本可用，仍有短板',capability_status='mostly_passed_on_this_suite',
                      action='可先用于已经通过的任务类型；失败或未覆盖的能力先小规模试用。')
        if not coverage_ok:
            result['reasons'].append('高阶覆盖不足：A 级筛查需至少 6 类任务，其中至少 4 道不同高阶题。')
        elif family_floor<.75:
            result['reasons'].append('部分任务类别通过率低于 75%，总分较高也保留短板提示。')
    elif accuracy<.5:
        result.update(grade='D',label='本轮能力明显不足',capability_status='low_on_this_suite',
                      action='不建议为当前表现支付所选型号档位的费用；核对题目和配置后再复测。')
    if n and passed<n:
        result['reasons'].append(f'{n-passed} 道内容未完全正确；另有 {quality.get("format_only_failures",0)} 道内容正确但格式不符。分项得分不用于提高等级。')
    result['screen_grade'] = result['grade']
    result.update(target_grade='U',target_label='目标水平尚未验证')
    if calibrated and comp.get('status')=='below_reference':
        result.update(target_grade='D',target_label='明显低于所选模型参考',grade='D',label='明显低于目标能力参考',capability_status='below_reference',evidence_basis='official_reference',
                      basis_label='可信官方能力对照',target_assessment='对照显示本轮能力明显低于所选型号的参考。',
                      action='不建议按所选型号档位付费；保留报告，核对渠道后再复测。')
        result['reasons'].append('同题、同配置的能力差距超过预设容差。')
    elif calibrated and comp.get('status')=='within_margin':
        result.update(target_grade='A',target_label='很大可能达到所选模型参考水平（预设容差内）',grade='A',label='目标能力参考达标，值得使用',capability_status='within_reference_margin',
                      evidence_basis='official_reference',basis_label='可信官方能力对照',
                      target_assessment='本套题与所选型号的能力差距在容差内；不要求底层型号相同。',
                      action='能力对照已通过；结合实际任务、稳定性和费用决定是否继续使用。')
        result['reasons'].append('已核实的官方参考对照通过；更好的答题表现不会因型号或风格不同被扣分。')

    elif calibrated and comp.get('status')=='above_reference':
        result.update(grade='S',target_grade='S',target_label='本套题有充分证据优于所选模型参考',
                      label='优于所选模型参考',capability_status='above_reference',evidence_basis='official_reference',
                      basis_label='可信官方能力对照',target_assessment='同题同配置的保守差距上界仍小于零；本结论不外推为所有用途都更强。',
                      action='本套题对照支持更强表现；继续结合实际用途、稳定性和费用判断。')

    # Interface usability and identity/behavior evidence remain visible, but
    # they do not lower a capability grade when task performance is sufficient.
    tool = report.get('tool_summary',{})
    expected_tool = tool_expected(report.get('target_model'),report.get('api_style'))
    tool_ok = all(tool.get(k) for k in ('call_detected','followup_completed','result_used'))
    parameters = [r for r in cases if r.get('family')=='parameter']
    parameter_ok = all(r.get('completed') and r.get('observed',{}).get('exact_instruction_followed') is True for r in parameters)
    usability_notes=[]
    if expected_tool and not tool_ok:
        usability_notes.append('工具闭环未通过；依赖工具调用的用途应先修复接口或复测。')
    if not parameter_ok:
        usability_notes.append('参数或精确指令探针未通过；核对 API 格式和思考档。')
    result['usability']={'status':'issues_found' if usability_notes else 'checks_passed' if parameters else 'partially_checked',
                         'notes':usability_notes}
    if usability_notes:
        result['action']+=' 如需依赖失败的接口功能，应先处理下方接口提示。'
    drift = any(r.get('target_model')==report.get('target_model') and r.get('trusted_by_operator') and
                 r.get('status')=='distribution_shift' for r in report.get('numeric_reference_panel',{}).get('comparisons',[]))
    result['identity_signal']={'status':'behavior_difference' if drift else 'not_established',
        'summary':'数字行为与目标参考不同；可能有提示词、采样或路由变化，不代表能力较低。' if drift else '模型来源未认证；能力相当或更好时，不因身份未知而扣分。'}
    if len(unique)<8 or (n and completed/n<.9) or (calibrated and comp.get('status')=='service_degradation'):
        reason='不同题目不足 8 道' if len(unique)<8 else '请求未完整完成'
        result.update(grade='U',screen_grade='U',target_grade='U',target_label='证据不足，目标水平尚未验证',label='检测未完成 · '+reason,evidence_basis='incomplete',basis_label='证据未收集完整',
                      capability_status='insufficient_samples' if len(unique)<8 else 'service_degradation',
                      action='先检查地址、接口、Key 或超时，再运行快检；本次暂不能评定能力。')
    if report.get('run_state',{}).get('end_reason') in ('budget_exhausted','interrupted'):
        result['reasons'].append('已保存已完成的结果；剩余检查因时间上限或手动中止而停止。')
    result['sample_note'] = '16 道快检只减少单题影响，不能单独证明达到任何具体型号；不同种子不能直接比较高低。'
    result['summary'] = GRADE_GUIDE[result['grade']]
    result['limitations'] = ['A 表示能力筛查或参考对照达标，不是原厂身份认证，也不是经标定的真货概率。',
        '快检只能支持本轮覆盖能力的试用判断；判断具体型号同等水平需要匹配参考。价格未录入，不计算性价比或承诺物有所值。']
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
    report = {'schema_version':'0.9','tool_version':__version__,'suite_version':suite_version,'suite_source':suite_source,'suite_commitment':commitment,
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
            req = urllib.request.Request('https://ipinfo.io/json',headers={'User-Agent':'RelayLens/0.8.0'})
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
    p.add_argument('--mode',choices=('fast','full'),default='full',help='fast=16题并行限时快检；full=完整自定义检测。双击向导默认fast')
    p.add_argument('--advanced',action='store_true',help='进入向导高级设置')
    p.add_argument('--time-budget',type=float,default=180,help='快速模式总采集时限，默认180秒；完整模式不受此限制')
    p.add_argument('--concurrency',type=int,default=4,help='快速模式并行请求进程数，默认4')
    p.add_argument('--seed',type=int); p.add_argument('--task-rounds','--logic-rounds',dest='task_rounds',type=int)
    p.add_argument('--quick',action='store_true',help='旧入口兼容：只做一个参数探针和工具烟测')
    p.add_argument('--repeats',type=int,default=1,help='同一组题重复次数；3 次起可观察同题波动')
    p.add_argument('--task-effort',default='high',choices=EFFORTS)
    p.add_argument('--suite-module',help='本地私有题库模块，提供 suite(seed, rounds)')
    p.add_argument('--pack',choices=('standard','challenge','fast'),help='fast精选8类，每类默认2题；standard标准8类；challenge完整14类')
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
    p.add_argument('--review-content',action='store_true',help='配合--compare-report，离线复核内置题内容；保留严格原评分，不调用API')
    p.add_argument('--compare-report',help='离线重新比较已有报告，不调用API、不需要Key')
    p.add_argument('--trust-reference',action='store_true',help='你已自行核实参考报告来自所选官方模型；程序无法认证导入文件')
    p.add_argument('--loss-margin',type=float,default=.10,help='允许的参考能力损失比例，默认0.10')
    args = p.parse_args(argv)
    if args.list_targets:
        print('\n'.join(f'{k}: {v["label"]} ({v["tier"]})' for k,v in TARGETS.items()))
        return 0
    if args.compare_report:
        if not 0 < args.loss_margin < 1: p.error('0 < loss-margin < 1 required')
        if Path(args.compare_report).resolve()==Path(args.out).resolve(): p.error('请使用新的输出路径，保留原始报告')
        report = read_report(args.compare_report)
        if args.review_content: report = review_report(report)
        if any('grade' in r for r in report.get('cases',[]) if isinstance(r,dict)):
            checked_rows(report)
        elif not report.get('settings',{}).get('numeric_samples'):
            p.error('报告没有任务评分或数字探针')
        # Imported previous claims are never trusted or carried forward.
        report.pop('reference_panel',None); report.pop('reference_comparison',None)
        report.pop('numeric_reference_panel',None)
        report['task_summary'] = summary(report.get('cases',[]))
        report['numeric_summary'] = describe_numeric(report)
        report['quality_profile'] = quality_profile(report.get('cases',[]))
        apply_comparisons(report,[args.reference_report] if args.reference_report else [],args.reference_dir,
                          trusted=args.trust_reference,margin=args.loss_margin)
        report['verdict'] = verdict(report)
        return save_report(report,args)
    if args.review_content: p.error('--review-content requires --compare-report')
    if args.interactive or not args.base_url:
        from .wizard import configure
        args = configure(args)
    defaults={'pack':'fast' if args.mode=='fast' else 'standard','task_rounds':2 if args.mode=='fast' else 3,
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
        print('\n目标能力：'+result.get('target_label','尚未验证'))
        print(f'本轮结果：{result["label"]}' + (f'（{result["grade"]}）' if result['grade']!='U' else ''))
        print(result.get('summary',''))
        print('依据：'+result.get('basis_label','旧版评级')+'；'+result.get('target_assessment',''))
        print('下一步：'+result.get('action','查看报告'))
        for note in result.get('usability',{}).get('notes',[]): print('接口提示：'+note)
        print('报告已保存：'+str(Path(args.out).resolve()))
    else:
        print(json.dumps({'report':str(Path(args.out).resolve()),'target_model':report['target_model'],
                          'verdict':report['verdict'],'task_summary':report.get('task_summary',{}),
                          'stability':report.get('diagnostics',{}).get('stability',{})},ensure_ascii=False,indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
