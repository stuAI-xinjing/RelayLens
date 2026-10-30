"""Bounded parallel collection using killable, isolated network workers.

The parent owns the deadline and the report. Slow DNS, incomplete SSE frames,
and idle connections cannot hold it hostage. Keys are passed in memory only.
"""
import json
import multiprocessing
import os
from pathlib import Path
import random
import signal
import tempfile
import time
import urllib.request
from types import SimpleNamespace

from .model_targets import known_efforts, tool_expected
from .numeric_fingerprint import prompts as numeric_prompts
from .reporting import clean_local
from .transport import Client


def _worker(config,job,path):
    signal.signal(signal.SIGINT,signal.SIG_IGN)
    from .audit import record_case, run_tool
    args = SimpleNamespace(**config)
    result = {'rows':[],'finished':False}
    def write():
        # Atomic replacement permits recovering completed tool stages on timeout.
        data = clean_local(result,(args.api_key,))
        temp = Path(path).with_suffix('.tmp')
        temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        os.replace(temp,path)
    def add(case_id,family,prompt,call,task=None,repeat=0):
        row,calls,context = record_case(case_id,family,prompt,call,args.api,task,repeat)
        result['rows'].append(row); write()
        return row['observed'],calls,context
    try:
        client = Client(args.base_url,args.api_key,api=args.api,route=args.route,proxy=args.proxy,
                        timeout=args.timeout,max_tokens=args.max_output_tokens,chat_token_field=args.chat_token_field,counter_model=args.target_model or args.model,
                        official_count_key_env=getattr(args,'official_count_key_env',None),stream_usage=getattr(args,'stream_usage',True))
        kind = job['kind']
        if kind=='egress':
            request=urllib.request.Request('https://ipinfo.io/json',headers={'User-Agent':'RelayLens'})
            with client.opener.open(request,timeout=args.timeout) as response:
                result['egress']=json.load(response)
        elif kind=='catalog':
            response=client.request('/models'); data=response.get('data')
            data=data if isinstance(data,dict) else {}
            result['models']={k:response.get(k) for k in ('http_status','transport_state','latency_ms','error')}
            result['models']['ids']=[x.get('id') for x in data.get('data',[]) if isinstance(x,dict)]
        elif kind=='tool':
            result['tool_summary']=run_tool(client,args.model,args.api,args.task_effort,args.stream,job['seed'],add,job['repeat'])
        else:
            prompt=job['prompt']
            call=client.call(args.model,prompt,effort=job.get('effort',args.task_effort),stream=args.stream,
                             temperature=args.fingerprint_temperature if kind in ('fingerprint','numeric') else None)
            observed,_,_=add(job['id'],job['family'],prompt,call,repeat=job.get('repeat',0))
            if kind=='parameter':
                supported=known_efforts(args.target_model or args.model,args.api)
                observed.update(requested_effort=job['effort'],documented_support=None if supported is None else job['effort'] in supported,
                                exact_instruction_followed=observed.get('text','').strip()=='RELAYLENS_OK')
            if kind=='numeric': result['rows'][-1]['numeric_index']=job['numeric_index']
        result['finished']=True
    except Exception as exc:
        result['worker_error']=type(exc).__name__+': '+str(exc)
    write()


def _missing(job,state,api,existing):
    from .audit import record_case
    if job['kind'] in ('catalog','egress'): return []
    if existing and job['kind']!='tool': return []
    if job['kind']=='tool':
        case_id='tool-followup' if existing else 'tool-initial'
        family='tool_followup' if existing else 'tool'
        prompt='Tool round trip was not finished.'; task=None
    else:
        case_id,family=job['id'],job['family']; task=job.get('task')
        prompt=task.prompt if task else job['prompt']
    row,_,_=record_case(case_id,family,prompt,{'transport_state':state,'data':{},
        'error':'本轮时间已到或已中止；此项没有完整结果。' if state!='worker_error' else '检测进程未返回完整结果。'},
        api,task,job.get('repeat',0))
    if job['kind']=='numeric': row['numeric_index']=job['numeric_index']
    return [row]


def collect(args,report,tasks):
    from .audit import FINGERPRINTS, grade_task
    started=time.monotonic(); last_progress=started
    # Reserve up to five seconds for stopping workers and writing reports.
    deadline=started+max(.1,args.time_budget-min(5,args.time_budget*.1))
    jobs=[{'kind':'parameter','id':'parameter-'+effort,'family':'parameter',
           'prompt':'Reply with exactly the token RELAYLENS_OK.','effort':effort} for effort in report['settings']['efforts']]
    jobs += [{'kind':'tool','seed':report['seed']+i,'repeat':i} for i in range(args.repeats)]
    for repeat in range(args.repeats):
        shuffled=tasks[:]; random.Random(report['seed']+31+repeat).shuffle(shuffled)
        jobs += [{'kind':'task','id':t.id,'family':t.family,'task':t,'repeat':repeat} for t in shuffled]
    from .token_counter import control_prompts
    jobs += [{'kind':'token_control','id':'token-control-'+str(i),'family':'token_control','prompt':prompt}
             for i,prompt in enumerate(control_prompts(report['seed'],getattr(args,'token_probes',0)))]
    jobs.append({'kind':'catalog'})
    if args.egress and not args.no_egress: jobs.append({'kind':'egress'})
    jobs += [{'kind':'fingerprint','id':f'fingerprint-{i}','family':'fingerprint','prompt':prompt,'repeat':j}
             for i,prompt in enumerate(FINGERPRINTS) for j in range(args.fingerprint_samples)]
    jobs += [{'kind':'numeric','id':f'numeric-sequence-{p["index"]}','family':'numeric_fingerprint',
              'numeric_index':p['index'],'prompt':p['prompt']} for p in numeric_prompts(report['seed'],args.numeric_samples)]
    context=multiprocessing.get_context('spawn')
    pending=list(enumerate(jobs)); active={}; outcomes={}; end_reason='completed'
    config={k:getattr(args,k) for k in ('base_url','api_key','api','route','proxy','timeout','max_output_tokens',
            'chat_token_field','model','target_model','task_effort','stream','fingerprint_temperature')}
    config['stream_usage'] = getattr(args,'stream_usage',True)
    config['official_count_key_env'] = getattr(args,'official_count_key_env',None)
    def read(path):
        try: return json.loads(path.read_text(encoding='utf-8'))
        except (ValueError,OSError): return {'rows':[],'finished':False}
    with tempfile.TemporaryDirectory(prefix='relaylens-fast-') as folder:
        folder=Path(folder).resolve()
        assert folder.parent==Path(tempfile.gettempdir()).resolve() and folder.name.startswith('relaylens-fast-')
        try:
            while pending or active:
                if time.monotonic()>=deadline:
                    end_reason='budget_exhausted'; break
                while pending and len(active)<args.concurrency and time.monotonic()<deadline:
                    index,job=pending.pop(0); path=folder/f'{index}.json'
                    # Keep private task objects and graders in the parent; custom
                    # modules need not be importable/pickleable by spawned workers.
                    wire_job={k:v for k,v in job.items() if k!='task'}
                    if job.get('task'): wire_job['prompt']=job['task'].prompt
                    process=context.Process(target=_worker,args=(config,wire_job,str(path)),daemon=True)
                    try:
                        process.start(); active[index]=(process,path)
                    except Exception:
                        outcomes[index]={'rows':[],'finished':False,'state':'worker_error'}
                for index,(process,path) in list(active.items()):
                    if not process.is_alive():
                        process.join(); outcomes[index]=read(path); process.close(); del active[index]
                        if args.progress:
                            print(f'已完成 {len(outcomes)}/{len(jobs)} 项 · 已用 {time.monotonic()-started:.0f} 秒 / {args.time_budget:g} 秒',flush=True)
                            last_progress=time.monotonic()
                if args.progress and time.monotonic()-last_progress>=5:
                    print(f'正在检测 · 已完成 {len(outcomes)}/{len(jobs)} 项 · 剩余约 {max(0,deadline-time.monotonic()):.0f} 秒',flush=True)
                    last_progress=time.monotonic()
                if active: time.sleep(.03)
        except KeyboardInterrupt:
            end_reason='interrupted'
        finally:
            # Terminate all before joining any; never wait on an unbounded read.
            for process,_ in active.values():
                if process.is_alive(): process.terminate()
            for index,(process,path) in active.items():
                process.join(timeout=.2)
                if process.is_alive(): process.kill(); process.join(timeout=.2)
                outcomes[index]=read(path)
                if not process.is_alive(): process.close()
    tools=[]; sequence=0
    for index,job in enumerate(jobs):
        outcome=outcomes.get(index,{'rows':[],'finished':False})
        rows=outcome['rows']
        if not outcome.get('finished'):
            state='time_budget_exhausted' if end_reason=='budget_exhausted' else 'interrupted' if end_reason=='interrupted' else 'worker_error'
            rows += _missing(job,state,args.api,rows)
        for row in rows:
            if job['kind']=='task' and 'grade' not in row: grade_task(row,job['task'])
            if job['kind']=='numeric': row['numeric_index']=job['numeric_index']
            sequence+=1; row['sequence']=sequence; report['cases'].append(row)
        if job['kind']=='tool':
            tools.append(outcome.get('tool_summary') or dict(call_detected=False,followup_completed=False,result_used=False))
        if job['kind']=='catalog':
            report['models']=outcome.get('models') or {'transport_state':'not_completed','ids':[]}
        if job['kind']=='egress':
            report['egress']=outcome.get('egress') or {'status':'not_collected','reason':'本轮未取得出口查询结果'}
    report['tool_summary']={k:bool(tools) and all(t[k] for t in tools) for k in ('call_detected','followup_completed','result_used')}
    report['tool_summary'].update(rounds=tools,documented_expectation=tool_expected(report.get('target_model'),args.api))
    report['run_state']={'mode':'fast','end_reason':end_reason,'elapsed_seconds':round(time.monotonic()-started,2),
        'time_budget_seconds':args.time_budget,'planned_questions':len(tasks)*args.repeats,
        'planned_requests_max':len(jobs)+args.repeats,'completed_jobs':sum(bool(x.get('finished')) for x in outcomes.values()),
        'planned_jobs':len(jobs),'concurrency':args.concurrency}
    return report
