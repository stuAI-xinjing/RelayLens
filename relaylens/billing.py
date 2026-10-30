"""Local billing import and conservative per-request reconciliation.

No language model is used. Provider logs remain provider claims, not proof of
upstream computation. Only allowlisted accounting fields survive import.
New API adapter: router/api-router.go GET /api/log/token, TokenAuthReadOnly;
controller/log.go GetLogByKey (recent records, not a full-history guarantee).
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .transport import NoRedirect, normalize_base

MAX_IMPORT_BYTES = 20 * 1024 * 1024
ALIASES = {
    'request_id': ('request_id', 'requestid', 'x-request-id', '请求id', '请求编号', '请求标识'),
    'upstream_request_id': ('upstream_request_id', '上游请求id'),
    'timestamp': ('timestamp', 'created_at', 'createdat', 'time', 'datetime', '时间', '请求时间', '创建时间'),
    'model': ('model', 'model_name', 'modelname', '模型', '模型名称', '型号'),
    'input_tokens': ('input_tokens', 'prompt_tokens', 'inputtokens', 'prompttokens', '输入token', '输入tokens', '输入token数', '输入', '提示词token'),
    'output_tokens': ('output_tokens', 'completion_tokens', 'outputtokens', 'completiontokens', '输出token', '输出tokens', '输出token数', '输出', '补全token'),
    'cached_tokens': ('cached_tokens', 'cache_read_input_tokens', 'cache_read_tokens', 'cachetokens', 'cache_tokens', '缓存token', '缓存tokens', '缓存', '缓存读取'),
    'cache_write_tokens': ('cache_creation_input_tokens', 'cache_write_tokens', '缓存写入'),
    'cost': ('cost', 'cost_usd', 'amount', 'fee', '费用', '扣费', '金额', '消耗金额'),
    'currency': ('currency', '币种', '货币'),
    'quota': ('quota', '配额'),
}


def _key(value):
    return re.sub(r'[\s()（）]', '', str(value).strip().lower()).replace('\ufeff', '')


def _number(value, integral=False):
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(',', '').replace('，', '')
    text = re.sub(r'^(?:USD|CNY|RMB|[$¥￥])\s*', '', text, flags=re.I)
    # Rounded shorthand such as 2.9M cannot support an exact reconciliation.
    if not re.fullmatch(r'\d+(?:\.\d+)?', text):
        return None
    result = float(text)
    if not math.isfinite(result) or result < 0 or (integral and not result.is_integer()):
        return None
    return int(result) if integral else result


def _timestamp(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) or re.fullmatch(r'\d+(?:\.\d+)?', str(value).strip()):
        number = float(value)
        if number > 10**11:
            number /= 1000
        return number if math.isfinite(number) and number >= 0 else None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace('Z', '+00:00').replace('/', '-'))
        # Dashboard exports without offsets use the user's local timezone.
        return parsed.timestamp()
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def normalize_record(raw):
    """Normalize a single export row without retaining unrelated private fields."""
    if not isinstance(raw, dict):
        return None
    values = {_key(k): v for k, v in raw.items()}
    # New API puts cache accounting metadata into JSON-encoded `other`.
    other = raw.get('other', {})
    if isinstance(other, str):
        try:
            other = json.loads(other)
        except (ValueError, TypeError):
            other = {}
    if isinstance(other, dict):
        for field in ('cached_tokens', 'cache_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'):
            if field in other and field not in values:
                values[field] = other[field]
    result = {}
    for field, aliases in ALIASES.items():
        value = next((values[_key(alias)] for alias in aliases if _key(alias) in values), None)
        if field == 'timestamp':
            result[field] = _timestamp(value)
        elif field.endswith('_tokens') or field == 'quota':
            result[field] = _number(value, True)
        elif field == 'cost':
            result[field] = _number(value)
        else:
            result[field] = str(value).strip()[:256] if value is not None else None
    # A common dashboard export combines input / output into the Tokens column.
    pair = values.get('tokens')
    if isinstance(pair, str) and re.fullmatch(r'[\d,， ]+\s*/\s*[\d,， ]+', pair):
        a, b = pair.split('/')
        if result['input_tokens'] is None:
            result['input_tokens'] = _number(a, True)
        if result['output_tokens'] is None:
            result['output_tokens'] = _number(b, True)
    if not result['currency']:
        cost_text = next((str(values[_key(a)]) for a in ALIASES['cost'] if _key(a) in values), '')
        if '$' in cost_text or 'cost_usd' in values or 'USD' in cost_text.upper():
            result['currency'] = 'USD'
        elif '￥' in cost_text or '¥' in cost_text or re.search(r'CNY|RMB', cost_text, re.I):
            result['currency'] = 'CNY'
    if all(result[k] is None for k in ('input_tokens', 'output_tokens', 'cost', 'quota')):
        return None
    return result


def _records(obj):
    if isinstance(obj, list):
        return obj
    if not isinstance(obj, dict):
        return []
    for name in ('items', 'logs', 'records', 'rows', 'data', 'results'):
        if name in obj and isinstance(obj[name], (dict, list)):
            return _records(obj[name])
    return [obj]


def parse_billing_text(text, source_type='auto'):
    """Parse an entire CSV/TSV/JSON/NDJSON export, with no manual field mapping."""
    if len(text.encode('utf-8')) > MAX_IMPORT_BYTES:
        return {'state': 'too_large', 'records': [], 'warnings': ['账单文件超过 20 MiB。'], 'source_type': source_type}
    text = text.lstrip('\ufeff').strip()
    warnings = []
    try:
        if source_type in ('json', 'jsonl', 'ndjson') or (source_type == 'auto' and text[:1] in ('{', '[')):
            try:
                obj = json.loads(text)
            except ValueError:
                obj = [json.loads(line) for line in text.splitlines() if line.strip()]
            if isinstance(obj, dict) and obj.get('success') is False:
                return {'state': 'unavailable', 'records': [], 'warnings': ['账单接口拒绝了查询。'], 'source_type': 'json'}
            rows = _records(obj)
            kind = 'json'
            data = obj.get('data', obj) if isinstance(obj, dict) else None
            if isinstance(data, dict) and _number(data.get('total'), True) is not None and int(data['total']) > len(rows):
                warnings.append('当前导出只有部分分页记录，覆盖率按实际匹配记录计算。')
        else:
            try:
                dialect = csv.Sniffer().sniff(text[:8192], delimiters=',\t;')
            except csv.Error:
                dialect = csv.excel_tab if '\t' in text.partition('\n')[0] else csv.excel
            rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
            kind = 'csv'
        records = [normalized for row in rows if (normalized := normalize_record(row)) is not None]
        if len(records) < len(rows):
            warnings.append('部分行未包含可识别的精确用量或金额，已跳过汇总/无效行。')
        if any(r.get('timestamp') is None for r in records):
            warnings.append('部分记录没有可识别时间，需要请求 ID 才能可靠匹配。')
        if any(r.get('quota') is not None and r.get('cost') is None for r in records):
            warnings.append('配额单位未自动换算为金额；未取得站点单位定义时不推算美元扣费。')
        return {'state': 'ok' if records else 'unrecognized', 'records': records, 'warnings': warnings,
                'source_type': kind}
    except (ValueError, TypeError, csv.Error, OverflowError):
        return {'state': 'invalid', 'records': [], 'warnings': ['无法解析账单格式；请使用完整 CSV/JSON 导出。'], 'source_type': source_type}


def import_billing_file(path):
    path = Path(path)
    if path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp'):
        return import_billing_image(path)
    try:
        if path.stat().st_size > MAX_IMPORT_BYTES:
            return {'state': 'too_large', 'records': [], 'warnings': ['账单文件超过 20 MiB。'], 'source_type': 'file'}
        raw = path.read_bytes()
        text = None
        for encoding in ('utf-8-sig', 'utf-16', 'gb18030'):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeError:
                continue
        if text is None:
            raise ValueError('encoding')
        return parse_billing_text(text)
    except (OSError, ValueError):
        return {'state': 'invalid', 'records': [], 'warnings': ['无法读取账单文件。'], 'source_type': 'file'}


def import_billing_image(path):
    """Optional local OCR, never a claim that arbitrary screenshots are tables.

    OCR text is ephemeral: callers may show it in a local review panel but must
    never persist it in audit reports or public exports.
    """
    if os.name == 'nt':
        try:
            windows = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-File',
                                      str(Path(__file__).with_name('ocr.ps1')), str(Path(path).resolve())],
                                     capture_output=True, timeout=45, check=False)
            if windows.returncode == 0:
                data = json.loads(windows.stdout.decode('utf-8-sig'))
                if data.get('state') == 'ok':
                    candidates = _ocr_table(data.get('lines', []))
                    review_rows = candidates or _ocr_review_rows(data.get('lines',[]))
                    text = _records_csv(candidates) if candidates else data.get('text', '')
                    return {'state': 'needs_review', 'records': [], 'candidate_records': candidates,
                            'source_type': 'image', 'ocr_text': text, 'review_rows':review_rows,
                            'warnings': ['已使用 Windows 本地 OCR 识别；请核对提取数字后确认，截图不上传任何模型。']}
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    executable = shutil.which('tesseract')
    if not executable:
        return {'state': 'ocr_unavailable', 'records': [], 'source_type': 'image',
                'warnings': ['本机 Windows OCR 或 Tesseract 不可用；请拖入后台完整 CSV/JSON 导出，无需挑选字段。']}
    try:
        result = subprocess.run([executable, str(Path(path).resolve()), 'stdout'], capture_output=True,
                                timeout=30, check=False)
        if result.returncode:
            raise ValueError('ocr')
        text = result.stdout.decode('utf-8', errors='replace')
        return {'state': 'needs_review', 'records': [], 'source_type': 'image', 'ocr_text': text,
                'warnings': ['截图文字已在本机识别；表格列和数字尚未核实，不参与自动对账。完整 CSV/JSON 导出可直接对账。']}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'state': 'ocr_failed', 'records': [], 'source_type': 'image',
                'warnings': ['本地 OCR 未能读取截图，请使用完整 CSV/JSON 导出。']}


def _records_csv(records):
    out = io.StringIO()
    fields = ('timestamp', 'model', 'input_tokens', 'output_tokens', 'cached_tokens', 'cost', 'currency')
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(records)
    return out.getvalue()


def _ocr_table(lines):
    """Recognize common log-table headers using OCR word coordinates.

    Result is always review-only: OCR digits are never independent evidence.
    Unknown layouts stay text, instead of guessing which numbers are tokens.
    """
    words = [w for line in lines if isinstance(line, dict) for w in line.get('words', [])
             if isinstance(w, dict) and all(k in w for k in ('text', 'x', 'y', 'width', 'height'))]
    headers = {}
    labels = {'时间': 'timestamp', 'time': 'timestamp', '模型': 'model', 'model': 'model',
              'tokens': 'tokens', '费用': 'cost', 'cost': 'cost', 'fee': 'cost'}
    for word in words:
        field = labels.get(_key(word['text']))
        if field and field not in headers:
            headers[field] = word
    if not all(k in headers for k in ('timestamp', 'model', 'tokens')):
        return []
    header_y = headers['timestamp']['y']
    if any(abs(headers[k]['y'] - header_y) > 25 for k in ('model', 'tokens')):
        return []
    ordered = sorted(headers, key=lambda k: headers[k]['x'])
    date_pattern = re.compile(r'\d{4}[-/]\d{2}[-/]\d{2}')
    time_pattern = re.compile(r'\d{2}:\d{2}:\d{2}')
    time_left = headers['timestamp']['x'] - 20
    time_right = min((h['x'] for k, h in headers.items() if h['x'] > time_left + 30), default=time_left + 230)
    anchors = [w for w in words if w['y'] > header_y + 10 and time_left <= w['x'] < time_right
               and date_pattern.search(w['text'])]
    anchors.sort(key=lambda w: w['y'])
    records = []
    for index, anchor in enumerate(anchors):
        bottom = anchors[index + 1]['y'] - 2 if index + 1 < len(anchors) else anchor['y'] + 45
        band = [w for w in words if anchor['y'] - 5 <= w['y'] < bottom]
        row = {}
        for field in ordered:
            start = headers[field]['x'] - 20
            following = [headers[k]['x'] - 20 for k in ordered if headers[k]['x'] > headers[field]['x']]
            end = min(following) if following else float('inf')
            selected = sorted([w for w in band if start <= w['x'] < end], key=lambda w: (round(w['y'] / 8), w['x']))
            text = ' '.join(w['text'] for w in selected)
            if field == 'timestamp':
                date, clock = date_pattern.search(text), time_pattern.search(text)
                if date and clock:
                    row['timestamp'] = date.group() + ' ' + clock.group()
            elif field == 'model':
                model = re.search(r'(?:gpt|claude)[A-Za-z0-9_.-]+', text, re.I)
                if model:
                    row['model'] = model.group()
            elif field == 'tokens':
                pair = re.search(r'([\d,，]+)\s*/\s*([\d,，]+)', text)
                if pair:
                    row['input_tokens'] = _number(pair.group(1), True)
                    row['output_tokens'] = _number(pair.group(2), True)
                cached = re.search(r'(?:缓存|cache)\D{0,10}([\d,，]+)', text, re.I)
                if cached:
                    row['cached_tokens'] = _number(cached.group(1), True)
            elif field == 'cost':
                money = re.search(r'([$¥￥])\s*(\d+(?:\.\d+)?)', text)
                if money:
                    row['cost'] = _number(money.group(2))
                    row['currency'] = 'USD' if money.group(1) == '$' else 'CNY'
        if all(k in row for k in ('timestamp', 'model', 'input_tokens', 'output_tokens')):
            records.append(row)
    return records


def fetch_key_billing(base_url, key, route='env', proxy='', timeout=10, endpoint=None):
    # Socket timeouts alone do not stop servers trickling bytes forever.
    import queue
    import threading
    results = queue.Queue(maxsize=1)
    def read():
        try:
            results.put(_fetch_key_billing(base_url,key,route,proxy,timeout,endpoint))
        except Exception:
            results.put({'state':'unavailable','records':[],'warnings':['账单读取失败；可导入整份导出文件。'],'source_type':'api'})
    worker = threading.Thread(target=read,daemon=True)
    worker.start()
    try: return results.get(timeout=timeout)
    except queue.Empty:
        return {'state':'timeout','records':[],'warnings':['账单查询超时；检测结果已保留，可稍后刷新账单。'],'source_type':'api'}


def _fetch_key_billing(base_url, key, route='env', proxy='', timeout=10, endpoint=None):
    """Read recent New API logs, or an explicitly supplied same-origin endpoint.

    `key` may be a separately supplied dashboard bearer token for explicit
    endpoints. Credentials never enter URLs, errors, or returned records.
    """
    base = urllib.parse.urlsplit(normalize_base(base_url))
    origin = urllib.parse.urlunsplit((base.scheme, base.netloc, '', '', ''))
    url = urllib.parse.urljoin(origin + '/', endpoint or '/api/log/token')
    target = urllib.parse.urlsplit(url)
    def origin_tuple(parts):
        return (parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80))
    if origin_tuple(target) != origin_tuple(base) or target.username or target.password or target.query or target.fragment:
        return {'state': 'invalid_endpoint', 'records': [], 'warnings': ['账单接口必须与测试地址同源，认证信息通过请求头发送。'], 'source_type': 'api'}
    proxies = {'http': proxy, 'https': proxy} if proxy else ({} if route == 'direct' else None)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies), NoRedirect())
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + key, 'Accept': 'application/json'}, method='GET')
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_IMPORT_BYTES + 1)
        if len(raw) > MAX_IMPORT_BYTES:
            return {'state': 'too_large', 'records': [], 'warnings': ['账单响应超过 20 MiB。'], 'source_type': 'api'}
        result = parse_billing_text(raw.decode('utf-8-sig'), 'json')
        result['source_type'] = 'api'
        result['warnings'].append('账单由中转站提供；与接口用量一致不等于已证明上游真实消耗。')
        if not endpoint:
            result['warnings'].append('自动接口仅返回最近记录；延迟入账或窗口外记录可能未覆盖。')
        return result
    except urllib.error.HTTPError as exc:
        return {'state': 'auth_required' if exc.code in (401, 403) else 'unavailable', 'records': [],
                'http_status': exc.code, 'source_type': 'api', 'warnings': ['本站未允许此 Key 自动读取账单，可导入完整后台导出文件。']}
    except (OSError, ValueError, UnicodeError):
        return {'state': 'unavailable', 'records': [], 'source_type': 'api',
                'warnings': ['自动账单接口不可用，可导入完整后台导出文件。']}


def reconcile_billing(report_or_calls, records):
    """Match only unique IDs or mutually unique time/model candidates.

    Tokens are compared *after* matching, so inflation cannot exclude a record
    from reconciliation. No arbitrary nearest-neighbor or greedy assignment.
    """
    from .token_audit import normalize_usage
    report = report_or_calls if isinstance(report_or_calls, dict) else {'cases': report_or_calls}
    calls = report.get('cases', [])
    api = report.get('api_style', 'responses')
    candidates = {}
    modes = {}
    for index, row in enumerate(calls):
        obs = row.get('observed', row)
        request_id = obs.get('request_id')
        exact = [i for i, r in enumerate(records) if request_id and request_id in (r.get('request_id'), r.get('upstream_request_id'))]
        if exact:
            candidates[index] = exact
            modes[index] = 'request_id'
            continue
        start = _timestamp(obs.get('started_at_utc'))
        latency = _number(obs.get('latency_ms')) or 0
        end = start + latency / 1000 if start is not None else None
        models = {m for m in (obs.get('model_returned'), report.get('model_requested')) if m}
        candidates[index] = [i for i, r in enumerate(records)
                             if start is not None and r.get('timestamp') is not None and r.get('model') in models
                             and start - 2 <= r['timestamp'] <= end + 2
                             # Contradicting IDs must never be overridden by time.
                             and not (request_id and (r.get('request_id') or r.get('upstream_request_id')))]
        modes[index] = 'time_model'
    # Exact-ID claims take precedence over time-only candidates.
    id_claimed = {j for i, matches in candidates.items() if modes[i] == 'request_id' for j in matches}
    for i in candidates:
        if modes[i] != 'request_id':
            candidates[i] = [j for j in candidates[i] if j not in id_claimed]
    claims = {}
    for i, matches in candidates.items():
        for j in matches:
            claims.setdefault(j, []).append(i)
    rows = []
    ambiguous = 0
    for i, options in candidates.items():
        if len(options) != 1 or len(claims.get(options[0], [])) != 1:
            ambiguous += bool(options)
            continue
        j = options[0]
        bill = records[j]
        obs = calls[i].get('observed', calls[i])
        usage = normalize_usage(obs.get('usage', {}), api)
        result = {'call_index': i, 'bill_index': j, 'match_method': modes[i], 'differences': {}}
        for field in ('input_tokens', 'output_tokens', 'cached_tokens'):
            actual = usage.get('cache_read_tokens' if field == 'cached_tokens' else field)
            billed = bill.get(field)
            if actual is not None and billed is not None:
                result['differences'][field] = {'api_reported': actual, 'bill_reported': billed,
                                               'delta': billed - actual, 'ratio': billed / actual if actual > 0 else None}
        result['billed_cost'] = bill.get('cost')
        result['currency'] = bill.get('currency')
        result['billed_quota'] = bill.get('quota')
        rows.append(result)
    matched = len(rows)
    warnings = ['对账核查接口与账单的一致性，不将两者当成独立的上游计数证据。']
    if ambiguous:
        warnings.append('存在同时间/型号或重复请求 ID 的冲突记录，未自动分配。')
    if matched < len(calls):
        warnings.append('账单覆盖不完整，未匹配请求不按零消耗处理。')
    if any(r['match_method'] == 'time_model' for r in rows):
        warnings.append('部分匹配依赖时间和型号；请使用专用测试 Key 并避免并行其他调用。')
    fields = {}
    for field in ('input_tokens','output_tokens','cached_tokens'):
        pairs = [r['differences'][field] for r in rows if field in r['differences']]
        api_total = sum(p['api_reported'] for p in pairs)
        bill_total = sum(p['bill_reported'] for p in pairs)
        fields[field] = {'compared_calls':len(pairs),'api_reported':api_total if pairs else None,
                         'bill_reported':bill_total if pairs else None,
                         'ratio':bill_total/api_total if api_total else None,
                         'different_calls':sum(p['delta']!=0 for p in pairs)}
    costs = {}
    for row in rows:
        if row.get('billed_cost') is not None and row.get('currency'):
            currency=row['currency']
            costs[currency] = costs.get(currency,0) + row['billed_cost']
    return {'comparison_totals':fields,'matched_costs':costs,'state': 'matched' if matched == len(calls) and calls else 'partial' if matched else 'unmatched',
            'matched': matched, 'total_calls': len(calls), 'coverage': matched / len(calls) if calls else 0,
            'ambiguous_calls': ambiguous, 'unmatched_bill_records': len(records) - matched,
            'rows': rows, 'warnings': warnings}


def _ocr_review_rows(lines):
    """Extract editable table cells by geometry, never certify OCR guesses."""
    import unicodedata
    boxes=[]
    for line in lines:
        words=line.get('words',[])
        if not words: continue
        text=unicodedata.normalize('NFKC',''.join(str(w['text']) for w in words))
        boxes.append({'text':text,'x':min(w['x'] for w in words),'y':min(w['y'] for w in words),
                      'right':max(w['x']+w['width'] for w in words)})
    labels={'时间':'timestamp','模型':'model','tokens':'tokens','费用':'cost','耗时':'end'}
    heads={labels[b['text'].lower()]:b for b in boxes if b['text'].lower() in labels}
    if not all(k in heads for k in ('timestamp','model','tokens')): return []
    top=heads['timestamp']['y']
    if any(abs(heads[k]['y']-top)>25 for k in ('model','tokens')): return []
    # The timestamp region contains a date plus time. No use of amounts as anchors.
    anchors=[b for b in boxes if b['y']>top+10 and b['x']<heads['timestamp']['x']+30
             and len(re.findall(r'\d',b['text']))>=6]
    anchors.sort(key=lambda b:b['y'])
    rows=[]
    for i,anchor in enumerate(anchors):
        bottom=anchors[i+1]['y']-2 if i+1<len(anchors) else anchor['y']+45
        band=[b for b in boxes if anchor['y']-5<=b['y']<bottom]
        def cell(left,right):
            return ' '.join(b['text'] for b in sorted(band,key=lambda b:(round(b['y']/8),b['x'])) if left<=b['x']<right)
        stamp=cell(heads['timestamp']['x']-20,heads['timestamp']['x']+220).replace('一','-')
        model=cell(heads['model']['x']-20,heads['tokens']['x']-25)
        cost_x=heads.get('cost',{}).get('x',heads['tokens']['x']+210)
        token_cell=cell(heads['tokens']['x']-20,cost_x-20)
        parts=token_cell.split('/',1)
        cache=re.search(r'(?:缓存|cache)[^0-9]*([0-9,， ]+)',token_cell,re.I)
        money=cell(cost_x-20,heads.get('end',{}).get('x',cost_x+200)-20)
        rows.append({'timestamp':stamp,'model':model,'input_tokens':parts[0] if len(parts)==2 else '',
                     'output_tokens':parts[1].split('缓存')[0] if len(parts)==2 else '',
                     'cached_tokens':cache.group(1) if cache else '', 'cost':money,'currency':'USD' if '$' in money else ''})
    return rows
