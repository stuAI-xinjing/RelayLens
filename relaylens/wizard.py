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
    print('\nRelayLens 中转透镜 · 独立 GPT / Claude 检测器\n')
    args.base_url = ask('中转站 API 地址',args.base_url or '')
    while not args.base_url:
        args.base_url = ask('地址不能为空，请重新填写')
    targets = list(TARGETS)
    for i, key in enumerate(targets,1):
        value = TARGETS[key]
        print(f'{i:2}. {value["label"]} / {key}' + (' （旧型号）' if value['tier'] == 'legacy' else ''))
    selected = ask('目标型号：填序号或完整 GPT/Claude 型号',args.target_model or '1')
    if selected.isdigit() and 1 <= int(selected) <= len(targets):
        selected = targets[int(selected)-1]
    args.target_model = selected
    args.model = ask('实际发送的模型 ID（可填中转站别名）',args.model or selected)
    api = ask('API：1=Responses，2=Chat Completions，3=Claude Messages','3' if selected.startswith('claude-') else '1')
    args.api = {'1':'responses','2':'chat','3':'messages'}.get(api,api)
    while args.api not in ('responses','chat','messages'):
        args.api = ask('请填写 responses / chat / messages','responses')
    args.api_key = getpass.getpass('该站点的 API Key（隐藏输入，仅本次使用）：').strip()
    route = ask('线路：1=系统/VPN，2=直连，3=指定 HTTP 代理','1')
    args.route = 'direct' if route == '2' else 'env'
    args.proxy = ask('HTTP 代理地址') if route == '3' else None
    args.task_rounds = integer('每类随机题数量（8类）',5)
    args.repeats = integer('同一组题重复次数',3,1)
    args.task_effort = ask('任务思考档（可填 omit 使用服务器默认）','high')
    args.fingerprint_samples = integer('每种回答分布探针采样数，5种；0=跳过，20起可检验',0)
    seed = ask('随机种子：同题官方/中转对照须填同一个整数')
    while seed and not seed.isdigit():
        seed = ask('请输入非负整数或留空')
    args.seed = int(seed) if seed else None
    args.reference_report = ask('可选：官方参考 JSON 报告路径').strip('"') or None
    args.trust_reference = False
    if args.reference_report:
        args.trust_reference = ask('你是否已核实此报告来自所选官方模型？y/n','n').lower() == 'y'
    args.timeout = integer('每次请求超时（秒）',120,1)
    args.max_output_tokens = integer('每次最大输出 token（含推理预算，过小会截断）',4096,128)
    args.stream = ask('流式输出以记录首个文本 token 耗时？y/n','y').lower() == 'y'
    args.egress = ask('查询本次网络出口地区？y/n','n').lower() == 'y'
    args.out = ask('报告路径',str(Path('reports') / time.strftime('relaylens_%Y%m%d_%H%M%S.json')))
    args.html_out = str(Path(args.out).with_suffix('.html'))
    args.open_report = True
    args.progress = True
    parameters = 4 if args.api == 'messages' else 5
    estimate = parameters + 8*args.task_rounds*args.repeats + 2*args.repeats + 5*args.fingerprint_samples
    print(f'\n本轮预计约 {estimate} 次 API 请求，按站点实际计费。结果写入 {args.out}。\n')
    return args
