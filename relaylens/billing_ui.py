"""Optional local billing workspace; deterministic parsers, no model or hosted server."""
import base64
import json
import secrets
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .reporting import clean_local, write_html

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_BODY_BYTES = 28 * 1024 * 1024
ALLOWED_SUFFIXES = {'.csv', '.tsv', '.json', '.jsonl', '.ndjson', '.txt', '.png', '.jpg', '.jpeg', '.webp', '.bmp'}


class BillingWorkspace:
    """State for one report. Credentials and raw bills never enter the saved report."""

    def __init__(self, report_path, session=None):
        self.source = Path(report_path).resolve()
        self.report = json.loads(self.source.read_text(encoding='utf-8-sig'))
        if not isinstance(self.report, dict) or 'verdict' not in self.report:
            raise ValueError('请选择 RelayLens 生成的 JSON 报告。')
        stem = self.source.stem
        self.output = self.source.with_name(stem + '-billing.json')
        from .token_audit import summarize_report
        self.report['token_audit'] = summarize_report(self.report)
        self.lock = threading.RLock()
        self.session = dict(session or {})

    def state(self):
        return {'target_model': self.report.get('target_model'),
                'billing': self.report.get('billing'),
                'token_audit': self.report.get('token_audit'),
                'token_reference_panel': self.report.get('token_reference_panel'),
                'base_url': self.report.get('base_url', ''),
                'session_key_available': bool(self.session.get('key')),
                'saved': self.output.exists(), 'output_name': self.output.name}

    def accept(self, imported):
        from .billing import reconcile_billing
        if imported.get('state') == 'needs_review' or not imported.get('records'):
            return {'import': {k: imported.get(k) for k in ('state', 'warnings', 'ocr_text', 'source_type', 'review_rows')},
                    'state': self.state()}
        audit = reconcile_billing(self.report, imported['records'])
        audit['import_warnings'] = imported.get('warnings', [])
        audit['source_type'] = imported.get('source_type')
        # Only the reconciler's summary is retained; the imported records stay ephemeral.
        self.report['billing'] = clean_local(audit)
        self.save()
        return {'state': self.state(), 'import': {'state': imported.get('state'),
                'warnings': imported.get('warnings', [])}}

    def save(self):
        report = clean_local(self.report)
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.output.parent,
                                         suffix='.tmp', delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
        try:
            write_html(report, self.output.with_suffix('.html'))
            temp_path.replace(self.output)
        finally:
            temp_path.unlink(missing_ok=True)

    def import_file(self, filename, encoded):
        from .billing import import_billing_file, import_billing_image
        suffix = Path(str(filename)).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise ValueError('请拖入 CSV、TSV、JSON、TXT 或整页账单截图。')
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise ValueError('文件数据无效，请重新选择文件。') from None
        if len(content) > MAX_FILE_BYTES:
            raise ValueError('单个文件请小于 20 MB。')
        with tempfile.TemporaryDirectory(prefix='relaylens-bill-') as directory:
            path = Path(directory) / ('bill' + suffix)
            path.write_bytes(content)
            imported = (import_billing_image(path) if suffix in {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
                        else import_billing_file(path))
        return self.accept(imported)

    def import_reference(self, encoded):
        from .token_audit import compare_consumption
        content=base64.b64decode(encoded,validate=True)
        if len(content)>MAX_FILE_BYTES: raise ValueError('reference too large')
        reference=json.loads(content.decode('utf-8-sig'))
        comparison=compare_consumption(self.report,reference,trusted=True)
        self.report['token_reference_panel']={'comparisons':[comparison],'load_errors':[]}
        self.save()
        return {'state':self.state(),'import':{'state':'ok','warnings':['已按你核实的官方参考比较；仅更新 Token 消耗对照，能力评级保持原报告。']}}

    def connect(self, data):
        from .billing import fetch_key_billing
        url = str(data.get('url', '')).strip()
        key = str(data.get('key', '')).strip()
        if not key:
            from .transport import normalize_base
            original = urlsplit(normalize_base(self.report.get('base_url','')))
            target = urlsplit(normalize_base(url))
            if (original.scheme,original.netloc) != (target.scheme,target.netloc):
                raise ValueError('更换站点后请填写该站点的查询 Key。')
            key = self.session.get('key','')
        if not url or not key:
            raise ValueError('请填写账单站点网址及拥有查询权限的 Key。')
        endpoint = str(data.get('endpoint', '')).strip() or None
        result = fetch_key_billing(url, key, endpoint=endpoint,
                                  route=self.session.get('route', 'env'),
                                  proxy=self.session.get('proxy', ''))
        # Remove credential echoes even if an unusual gateway includes them in a warning.
        if result.get('state')=='ok': self.session['key'] = key
        return self.accept(clean_local(result, (key,)))


PAGE = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RelayLens · Token 核账</title><style>
:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif;color:#223348;background:#f4f7fb}main{max-width:1120px;margin:auto;padding:32px 24px}header{display:flex;justify-content:space-between;align-items:center;gap:20px}h1{font-size:29px;margin:0}h2{font-size:19px;margin-top:0}h3{font-size:16px}p{margin:8px 0}.muted{color:#63748a}.pill{border-radius:30px;padding:6px 12px;background:#e6f4ef;color:#187356;font-size:12px}.card{background:white;border:1px solid #dfe7f0;border-radius:18px;padding:24px;margin:20px 0;box-shadow:0 5px 16px #213e5b04}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.grid .card{margin:0}label{display:block;margin-top:12px}input,textarea{font:inherit;width:100%;padding:11px 12px;border:1px solid #c9d5e5;border-radius:9px;background:white}button,.button{font:inherit;cursor:pointer;border:0;border-radius:9px;background:#225fc7;color:white;padding:10px 18px;display:inline-block;text-decoration:none;margin-top:14px}button:disabled{opacity:.5;cursor:wait}.secondary{background:#edf2fa;color:#25486e}.drop{display:block;width:100%;padding:28px 18px;text-align:center;border:2px dashed #a9c1df;border-radius:12px;background:#f8fbff;color:#25486e;cursor:pointer}.drop.over{background:#e4efff;border-color:#225fc7}.drop input{margin-top:12px;padding:6px;background:transparent;border:0;font-size:13px}.grade{font-size:28px;font-weight:650;color:#205caf}details{margin-top:12px}summary{cursor:pointer;color:#35577a}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 ui-monospace,monospace;background:#f4f7fb;padding:14px;border-radius:8px;max-height:400px;overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;border-bottom:1px solid #e4e9f0;padding:10px;overflow-wrap:anywhere}.scroll{overflow:auto}iframe{width:100%;height:740px;border:1px solid #dfe7f0;border-radius:12px;background:white}#notice{padding:12px 16px;border-radius:10px;background:#eaf1fb;white-space:pre-wrap}#notice:empty{display:none}.warn{color:#865914}.hidden{display:none!important}.boundary{border-left:4px solid #2567bb}a{color:#235caa}@media(max-width:760px){main{padding:18px 12px}.grid{grid-template-columns:1fr}header{align-items:flex-start}.card{padding:18px}}
</style><main><header><div><h1>RelayLens · Token 核账</h1><p class="muted" id="target">读取本轮报告…</p></div><div><span class="pill">本机处理 · 无需大模型</span><br><a class="button secondary" href="report" target="_blank" rel="noopener">打开完整检测报告</a> <button id="shutdown" class="secondary">关闭本机服务</button></div></header>
<section class="card boundary"><h2>自动核算，让记录说话</h2><p>程序使用协议字段、独立计数、确定性匹配和本机 OCR；不让被测模型自报 Token。</p><p class="muted">建议另外创建一个专用测试 Key，便于隔离记录、提高匹配准确度。原有 Key 也可以使用。</p><p class="muted">Token 消耗的甲＋～戊＋表示相对参考消耗量，与能力 S/A/B/C/D 完全独立。未取得可比较的官方参考时，不强行给消耗等级。</p></section>
<section class="card" id="tokenMetrics"><h2>Token 消耗 · 独立于能力等级</h2><div id="tokenSummary"></div><details><summary>导入我已核实来源的官方同题参考</summary><p class="muted">选择官方直连生成的 RelayLens JSON；型号、题目种子、思考档和预算需一致。此操作声明你已核实来源，仅比较消耗，不修改能力评级。</p><input id="referenceFile" type="file" accept=".json"></details></section><div id="notice" role="status" aria-live="polite"></div><div class="grid">
<section class="card"><h2>连接账单查询</h2><p class="muted">支持提供只读用量接口的站点。先用测试 Key；权限不足时可填后台专门提供的查询凭据。</p><form id="connect"><label for="url">中转站网址</label><input id="url" type="url" required placeholder="https://relay.example" autocomplete="url"><label for="key">测试 Key / 只读账单凭据</label><input id="key" type="password" autocomplete="off" placeholder="仅用于本次连接，不写入报告"><details><summary>站点提供了其他账单接口</summary><label for="endpoint">同站点的只读接口地址</label><input id="endpoint" placeholder="留空自动尝试已支持的接口"></details><button>连接并自动对账</button></form><p class="muted">网页登录态与调用 Key 可能不同。本工具不会自动读取浏览器 Cookie；站点不开放查询接口时，使用右侧导入。</p></section>
<section class="card"><h2>拖入整份账单或整页截图</h2><p class="muted">无需挑字段。优先导出 CSV / JSON，数字更完整；截图由本机 OCR 识别，识别不清会明确提示。</p><label class="drop" id="drop">把文件拖到这里，或选择文件<input id="file" type="file" accept=".csv,.tsv,.json,.jsonl,.ndjson,.txt,.png,.jpg,.jpeg,.webp,.bmp"></label><p class="muted">最大 20 MB。原始账单、截图和认证信息不会写入结果报告。</p><details><summary>我只能复制整个页面的文字</summary><textarea id="billText" rows="6" placeholder="粘贴完整账单文字或 CSV / JSON"></textarea><button id="parseText" type="button" class="secondary">自动识别并对账</button></details></section></div>
<section class="card hidden" id="review"><h2>截图识别需要复核</h2><p class="muted">以下是本机识别结果。可修正明显的文字识别错误后重试；无法可靠识别表格时，请导入站点整份导出文件。</p><div class="scroll" id="ocrGrid"></div><details><summary>识别原文</summary><textarea id="ocrText" rows="7"></textarea></details><button id="retryOcr" class="secondary">确认修正后的识别结果并对账</button></section>
<section class="card"><h2>本轮核账结果</h2><div id="result"><p class="muted">等待账单记录。接口 usage 已包含在原检测报告中；尚未读取账单不代表已对账。</p></div><p id="saved" class="muted"></p><details><summary>查看完整核账依据</summary><pre id="details">尚无账单记录。</pre></details></section>
<section class="card"><h2>检测报告 · 能力与消耗分别查看</h2><iframe id="report" title="RelayLens 检测报告" src="report" sandbox="allow-same-origin"></iframe></section></main>
<script>
const $=id=>document.getElementById(id);let busy=false;
function show(message){$('notice').textContent=message||''}
async function api(path,data){if(busy)return;busy=true;document.querySelectorAll('button').forEach(x=>x.disabled=true);try{const r=await fetch(path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json'}:{},body:data?JSON.stringify(data):undefined});const result=await r.json();if(!r.ok)throw Error(result.error||'请求失败');return result}finally{busy=false;document.querySelectorAll('button').forEach(x=>x.disabled=false)}}
function add(parent,tag,text,cls){const e=document.createElement(tag);e.textContent=text;if(cls)e.className=cls;parent.append(e);return e}
function render(state){renderTokens(state);if(!$('url').value)$('url').value=state.base_url||'';if(state.session_key_available)$('key').placeholder='留空使用本轮测试 Key（仅保留在内存）';$('target').textContent='目标模型：'+(state.target_model||'未记录')+' · 本次检测单独核对';const b=state.billing;const root=$('result');root.replaceChildren();if(b){const statuses={matched:'已匹配',partial:'部分匹配',unmatched:'未匹配',no_match:'未匹配',no_records:'没有可用记录',complete:'匹配完成'};add(root,'p',statuses[b.state]||('状态：'+b.state),'grade');if(b.matched!==undefined)add(root,'p','匹配记录：'+b.matched);if(b.coverage!==undefined)add(root,'p','请求覆盖率：'+(typeof b.coverage==='number'?(100*b.coverage).toFixed(1)+'%':JSON.stringify(b.coverage)));for(const [field,label] of [['input_tokens','输入'],['output_tokens','输出'],['cached_tokens','缓存读取']]){const row=(b.comparison_totals||{})[field];if(row&&row.compared_calls){add(root,'p',label+'：接口 '+row.api_reported+' → 账单 '+row.bill_reported+'，'+(row.ratio==null?'无有效比值':row.ratio.toFixed(3)+' 倍')+'；'+row.different_calls+' 次存在差异',row.different_calls?'warn':'')}}for(const [currency,value] of Object.entries(b.matched_costs||{}))add(root,'p','已匹配账单金额：'+value.toFixed(6)+' '+currency+'（不含未匹配记录）');for(const w of [...(b.warnings||[]),...(b.import_warnings||[])])add(root,'p',w,'warn');add(root,'p','账单与接口一致仅说明两处记录一致；中转站上报数据不能替代独立计数。','muted');$('details').textContent=JSON.stringify(b,null,2)}else add(root,'p','尚未完成账单对账。导入整份账单后会自动匹配本次请求。','muted');$('saved').textContent=state.saved?'已保存 '+state.output_name+' 及同名 HTML；原检测报告保留。':'';}
function renderTokens(state){const root=$('tokenSummary');root.replaceChildren();const a=state.token_audit||{};const rows=(state.token_reference_panel||{}).comparisons||[];if(!rows.some(r=>r.grade))add(root,'p','消耗等级：待官方同条件参考','grade');for(const r of rows){if(r.grade)add(root,'p',r.grade+' · '+(r.label||'')+' · 比值 '+Number(r.ratio).toFixed(2)+'×','grade')}const totals=a.totals||{};add(root,'p','接口上报输入 '+(totals.input_tokens??'未记录')+' · 输出 '+(totals.output_tokens??'未记录')+' · 缓存读取 '+(totals.cache_read_tokens??'未记录'));const independent=a.independent_input||{};if(independent.input_tokens!=null)add(root,'p','独立输入计数：'+independent.input_tokens+'（'+(independent.all_official_counts?'官方计数接口':'本机估算，不能据此认定虚报')+'；覆盖 '+independent.known_requests+'/'+independent.total_requests+' 次）');const m=a.multiplier||{};if(m.slope!==null&&m.slope!==undefined){add(root,'p','输入增量斜率 '+Number(m.slope).toFixed(3)+'× · 固定差额 '+Math.round(m.intercept_tokens||0)+' Token');add(root,'p','斜率来自独立计数与接口上报值；是否可判读取决于计数精度、输入跨度及受控条件。','muted')}add(root,'p','甲＋ / 甲 / 乙 / 丙 / 丁 / 戊 / 戊＋：极少 / 少很多 / 少一些 / 平均 / 多一些 / 多很多 / 极多。消耗少不直接证明能力更强或计费更真实。','muted')}
function received(r){if(!r)return;if(r.state)render(r.state);const imp=r.import||{};$('review').classList.toggle('hidden',!imp.ocr_text);if(imp.ocr_text)$('ocrText').value=imp.ocr_text;renderReview(imp.review_rows||[]);show((imp.warnings||[]).join('\n')||(imp.state==='needs_review'?'识别结果需要复核。':'本轮核账已更新。'));$('report').src='report?t='+Date.now()}
const reviewFields=['timestamp','model','input_tokens','output_tokens','cached_tokens','cost','currency'];function renderReview(rows){const grid=$('ocrGrid');grid.replaceChildren();if(!rows.length)return;const t=add(grid,'table',''),head=add(t,'tr','');for(const label of ['时间','模型','输入 Token','输出 Token','缓存读取','费用','币种'])add(head,'th',label);for(const row of rows){const tr=add(t,'tr','');for(const field of reviewFields){const td=add(tr,'td','');const input=add(td,'input','');input.value=row[field]??'';input.style.minWidth=field==='timestamp'?'180px':'100px';input.dataset.field=field}}}async function upload(file){if(!file)return;if(file.size>20*1024*1024){show('请选择小于 20 MB 的文件。');return}show('正在本机识别并匹配账单…');try{const reader=new FileReader();reader.onload=async()=>{try{received(await api('import',{name:file.name,data:String(reader.result).split(',')[1]}))}catch(e){show(e.message)}};reader.onerror=()=>show('文件读取失败，请重新选择。');reader.readAsDataURL(file)}catch(e){show(e.message)}}
$('referenceFile').onchange=e=>{const f=e.target.files[0];if(!f)return;if(f.size>20*1024*1024){show('文件超过 20 MB');return}const reader=new FileReader();reader.onload=async()=>{try{received(await api('reference',{data:String(reader.result).split(',')[1]}))}catch(err){show(err.message)}};reader.readAsDataURL(f)};$('file').onchange=e=>upload(e.target.files[0]);$('drop').ondragover=e=>{e.preventDefault();$('drop').classList.add('over')};$('drop').ondragleave=()=>$('drop').classList.remove('over');$('drop').ondrop=e=>{e.preventDefault();$('drop').classList.remove('over');upload(e.dataTransfer.files[0])};$('connect').onsubmit=async e=>{e.preventDefault();show('正在读取本次 Key 的账单记录…');try{received(await api('connect',{url:$('url').value,key:$('key').value,endpoint:$('endpoint').value}))}catch(err){show(err.message)}finally{$('key').value=''}};async function textImport(id){show('正在识别整份账单文字…');try{received(await api('text',{text:$(id).value}))}catch(e){show(e.message)}}$('parseText').onclick=()=>textImport('billText');$('retryOcr').onclick=async()=>{const trs=[...$('ocrGrid').querySelectorAll('tr')].slice(1);if(!trs.length)return textImport('ocrText');const rows=trs.map(tr=>Object.fromEntries([...tr.querySelectorAll('input')].map(i=>[i.dataset.field,i.value])));try{received(await api('text',{text:JSON.stringify(rows)}))}catch(e){show(e.message)}};$('shutdown').onclick=async()=>{try{await api('shutdown',{});show('本机服务已关闭。已保存的 JSON / HTML 报告仍可独立打开。');document.querySelectorAll('button,input,textarea').forEach(e=>e.disabled=true)}catch(e){show(e.message)}};api('state').then(render).catch(e=>show(e.message));
</script></html>'''


def create_server(report_path, session=None):
    """Create a loopback-only server; callers control its lifetime (also useful in tests)."""
    workspace = BillingWorkspace(report_path, session=session)
    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Do not print paths, credentials or imported data.

        def respond(self, status, payload, mime='application/json; charset=utf-8'):
            body = (json.dumps(payload, ensure_ascii=False).encode('utf-8')
                    if isinstance(payload, (dict, list)) else payload.encode('utf-8')
                    if isinstance(payload, str) else payload)
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Frame-Options', 'SAMEORIGIN')
            self.end_headers()
            self.wfile.write(body)

        def route(self):
            expected = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != expected:
                return None
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + expected:
                return None
            path = urlsplit(self.path).path
            prefix = '/' + token + '/'
            return path[len(prefix):] if path.startswith(prefix) else None

        def do_GET(self):
            route = self.route()
            if route is None:
                return self.respond(403, {'error': '请使用本次启动时显示的本机地址。'})
            with workspace.lock:
                if route == '':
                    return self.respond(200, PAGE, 'text/html; charset=utf-8')
                if route == 'state':
                    return self.respond(200, workspace.state())
                if route == 'report':
                    with tempfile.TemporaryDirectory(prefix='relaylens-view-') as directory:
                        path = Path(directory) / 'report.html'
                        write_html(clean_local(workspace.report), path)
                        return self.respond(200, path.read_bytes(), 'text/html; charset=utf-8')
            self.respond(404, {'error': '页面不存在。'})

        def do_POST(self):
            route = self.route()
            if route not in ('import', 'text', 'connect', 'reference', 'shutdown'):
                return self.respond(403, {'error': '此请求地址不可用。'})
            if self.headers.get_content_type() != 'application/json':
                return self.respond(415, {'error': '请选择页面中的导入功能。'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                length = 0
            if not 0 < length <= MAX_BODY_BYTES:
                return self.respond(413, {'error': '文件过大或请求为空。'})
            try:
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('导入数据格式无效。')
                if route == 'shutdown':
                    self.respond(200, {'stopped': True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                with workspace.lock:
                    if route == 'import':
                        result = workspace.import_file(data.get('name', ''), data.get('data', ''))
                    elif route == 'reference':
                        result = workspace.import_reference(data.get('data',''))
                    elif route == 'text':
                        from .billing import parse_billing_text
                        result = workspace.accept(parse_billing_text(str(data.get('text', ''))))
                    else:
                        result = workspace.connect(data)
                self.respond(200, result)
            except (ValueError, TypeError, KeyError):
                self.respond(400, {'error': '无法可靠读取此数据。请检查网址和查询凭据，或导入完整 CSV / JSON 账单。'})
            except Exception:
                self.respond(500, {'error': '本次读取未完成，原报告已保留。可改用整份 CSV / JSON 账单导入。'})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    server.workspace = workspace
    server.workspace_url = f'http://127.0.0.1:{server.server_port}/{token}/'
    return server


def serve(report_path, open_browser=True, session=None):
    server = create_server(report_path, session=session)
    print('RelayLens 本机核账页面：' + server.workspace_url)
    print('无需大模型。关闭此终端或按 Ctrl+C 停止；保存的报告仍可单独打开。')
    if open_browser:
        webbrowser.open(server.workspace_url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
