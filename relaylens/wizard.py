"""A console wizard for the standalone Windows launcher, with no installation."""
import getpass
import time
from pathlib import Path

from .model_targets import TARGETS


def ask(text, default=''):
    return input(f'{text}' + (f' [{default}]' if default != '' else '') + '：').strip() or str(default)


def integer(text, default, minimum=0):
    while True:
        try:
            value = int(ask(text,default))
            if value >= minimum:
                return value
        except ValueError:
            pass
        print(f'请输入 >= {minimum} 的整数。')


def configure(args):
    from .model_targets import profile
    from .transport import normalize_base
    print('\nRelayLens 中转透镜 · 3 分钟快速检查\n8 道关键题 + 参数/工具检查；完整检测可在高级设置中选择。\n')
    while True:
        entered = ask('中转站 API 地址',args.base_url or '')
        try:
            args.base_url = normalize_base(entered)
            break
        except ValueError:
            print('请填有效的 HTTP(S) API 地址，不要把 Key 放在网址中。')
    targets = list(TARGETS)
    for i,key in enumerate(targets,1):
        print(f'{i:2}. {TARGETS[key]["label"]}' + (' （旧型号）' if TARGETS[key]['tier']=='legacy' else ''))
    while True:
        selected = ask('所选 GPT/Claude 型号：序号或完整 ID',args.target_model or '1')
        if selected.isdigit() and 1 <= int(selected) <= len(targets): selected = targets[int(selected)-1]
        if profile(selected): break
        print('请填写 gpt-* 或 claude-* 型号；中转别名在高级设置填写。')
    args.target_model = selected
    args.model = args.model or selected
    args.api = 'messages' if selected.startswith('claude-') else 'responses'
    args.api_key = getpass.getpass('API Key（隐藏输入，仅本次使用）：').strip()
    advanced = getattr(args,'advanced',False)
    if not advanced:
        advanced = ask('回车开始快检；如需调整接口、模型别名或完整检测，输入 A','').lower()=='a'
    args.mode = 'fast'
    if advanced:
        args = advanced_settings(args)
    args.out = ask('报告路径',str(Path('reports') / time.strftime('relaylens_%Y%m%d_%H%M%S.json'))) if advanced else str(Path('reports') / time.strftime('relaylens_%Y%m%d_%H%M%S.json'))
    args.html_out = str(Path(args.out).with_suffix('.html'))
    args.open_report = True
    args.progress = True
    if args.mode=='fast' and not advanced:
        print('\n开始快检，默认 8 道关键题、最多约 12 次请求、4 路并行、3 分钟采集预算。\n如使用了命令行参数，以参数为准。按站点实际计费；Ctrl+C 可停止采集并保留结果。\n')
    else:
        print(f'\n开始{ "限时快速" if args.mode=="fast" else "完整" }检测，使用你选择的设置；按实际请求计费。\n')
    return args


def advanced_settings(args):
    args.mode = 'fast' if ask('检测模式：1=限时快速，2=完整自定义','2')=='1' else 'full'
    args.model = ask('实际发送的模型 ID（可填中转站别名）',args.model)
    api = ask('API：1=Responses，2=Chat Completions，3=Claude Messages','3' if args.api=='messages' else '1')
    args.api = {'1':'responses','2':'chat','3':'messages'}.get(api,api)
    while args.api not in ('responses','chat','messages'):
        args.api = ask('请填写 responses / chat / messages','responses')
    if args.api=='chat':
        args.chat_token_field = 'max_tokens' if ask('Chat 预算字段：1=当前格式，2=旧网关 max_tokens','1')=='2' else 'max_completion_tokens'
    route = ask('线路：1=系统/VPN，2=直连，3=指定 HTTP 代理','1')
    args.route = 'direct' if route=='2' else 'env'
    args.proxy = ask('HTTP 代理地址') if route=='3' else None
    pack = ask('题库：0=精选8题，1=标准8类，2=完整14类','0' if args.mode=='fast' else '2')
    args.pack = {'0':'fast','1':'standard','2':'challenge'}.get(pack,'challenge')
    args.context_records = integer('上下文记录数',128 if args.pack=='fast' else 1024,32)
    args.task_rounds = integer('每类随机题数量',1 if args.mode=='fast' else 5)
    args.repeats = integer('同题重复次数',1 if args.mode=='fast' else 3,1)
    args.task_effort = ask('任务思考档（omit 使用服务器默认）','high')
    args.fingerprint_samples = integer('短回答分布探针数/种，5种；0=跳过',0)
    args.numeric_samples = integer('数字序列探针请求数；0=跳过，30起可与官方参考检验',0)
    seed = ask('随机种子：官方/中转对照须相同，留空自动生成')
    while seed and not seed.isdigit(): seed = ask('请输入非负整数或留空')
    args.seed = int(seed) if seed else None
    args.reference_report = ask('可选：官方参考 JSON 报告路径').strip('"') or None
    args.reference_dir = ask('可选：多个官方参考所在文件夹').strip('"') or None
    args.trust_reference = False
    if args.reference_report or args.reference_dir:
        args.trust_reference = ask('你已核实参考来自标注的官方模型？y/n','n').lower()=='y'
    args.timeout = integer('每次请求超时（秒）',180 if args.mode=='fast' else 300,1)
    args.max_output_tokens = integer('每次最大输出 token（含推理预算）',32768,128)
    args.stream = ask('流式记录首文本耗时？y/n','y').lower()=='y'
    args.egress = ask('查询网络出口地区？y/n','n').lower()=='y'
    if args.mode=='fast':
        args.time_budget = integer('本轮总时限（秒）',180,1)
        args.concurrency = integer('并行请求数',4,1)
    return args
