"""Local HTML report, and secret scrubbing even when an API echoes the key."""
import html
import json
import re
from pathlib import Path


def clean_local(value, secrets=()):
    if isinstance(value,dict):
        return {k:clean_local(v,secrets) for k,v in value.items() if k.lower() not in ('api_key','authorization','cookie','x-api-key')}
    if isinstance(value,list):
        return [clean_local(v,secrets) for v in value]
    if isinstance(value,str):
        for secret in secrets:
            if secret:
                value = value.replace(secret,'[REDACTED]')
        value = re.sub(r'(?i)Bearer\s+[^\s"<>]+','Bearer [REDACTED]',value)
        value = re.sub(r'\b(?:sk|sess)-[A-Za-z0-9_-]{8,}','[REDACTED]',value)
    return value


def write_html(report,path):
    esc = lambda v: html.escape(str(v))
    verdict = report['verdict']
    summary = report.get('task_summary',{})
    family_rows = ''.join(f'<tr><td>{esc(name)}</td><td>{r["passed"]}/{r["planned"]}</td><td>{r["completed"]}</td><td>{r["accuracy"]:.1%}</td></tr>' for name,r in summary.items())
    diagnostics = report.get('diagnostics',{})
    timing_rows = ''.join(f'<tr><td>{esc(name)}</td><td>{esc(r["total_ms"]["median"])}</td><td>{esc(r["total_ms"]["p95"])}</td><td>{esc(r["first_token_ms"]["median"])}</td></tr>' for name,r in diagnostics.get('latency_by_family',{}).items())
    case_rows = []
    for row in report.get('cases',[]):
        obs = row.get('observed',{})
        case_rows.append(f'<tr><td>{esc(row["id"])}</td><td>{esc(obs.get("http_status"))}</td><td>{"通过" if row.get("grade",{}).get("passed") and row.get("completed") else "失败" if "grade" in row else "完成" if row.get("completed") else "失败"}</td><td>{esc(obs.get("model_returned"))}</td><td>{esc(obs.get("error") or "")}</td><td><details><summary>回答</summary><pre>{esc(obs.get("text",""))}</pre></details></td></tr>')
    reasons = ''.join(f'<li>{esc(x)}</li>' for x in verdict.get('reasons',[]) + verdict.get('limitations',[]))
    comparison = esc(json.dumps(report.get('reference_comparison',{'status':'未提供可信官方参考'}),ensure_ascii=False,indent=2))
    stability = esc(json.dumps(diagnostics.get('stability',{}),ensure_ascii=False,indent=2))
    document = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>RelayLens 中转透镜</title>
<style>body{{font:15px/1.6 system-ui,"Microsoft YaHei",sans-serif;background:#f3f6fa;color:#203049;margin:0}}main{{max-width:1200px;margin:auto;padding:28px}}.card{{background:white;padding:24px;border:1px solid #dce3ec;border-radius:14px;margin:16px 0}}h1{{margin-bottom:4px}}h2{{font-size:18px}}.grade{{font-size:28px;color:#2254aa}}.muted{{color:#627087}}table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;padding:10px;border-bottom:1px solid #e4e9f0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}.scroll{{overflow:auto}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}}.grid>.card{{margin:0}}@media(max-width:600px){{main{{padding:10px}}.card{{padding:15px}}}}</style>
<main><h1>RelayLens · 中转透镜</h1><p class="muted">目标 {esc(report.get('target_model'))} · 请求 ID {esc(report.get('model_requested'))} · {esc(report.get('api_style'))} · seed {esc(report.get('seed'))}</p>
<section class="card"><div class="grade">{esc(verdict['grade'])} · {esc(verdict['label'])}</div><p>能力状态：{esc(verdict.get('capability_status'))}　身份：尚未证明</p><ul>{reasons}</ul></section>
<section class="card"><h2>任务能力 · 失败和截断计入总数</h2><div class="scroll"><table><tr><th>类别</th><th>通过/计划</th><th>完成</th><th>正确率</th></tr>{family_rows}</table></div></section>
<div class="grid"><section class="card"><h2>可信参考与能力差距</h2><pre>{comparison}</pre></section><section class="card"><h2>多轮稳定性与混用线索</h2><pre>{stability}</pre><p class="muted">同题波动、名称变化可能由路由、采样、缓存或限额引起，需复测。</p></section></div>
<section class="card"><h2>延迟分布 · 单位毫秒</h2><p>按任务类别统计成功请求；延迟不能单独鉴定身份。</p><div class="scroll"><table><tr><th>类别</th><th>总耗时中位</th><th>P95</th><th>首文本 token 中位</th></tr>{timing_rows}</table></div></section>
<section class="card"><h2>逐次请求证据</h2><div class="scroll"><table><tr><th>测试</th><th>HTTP</th><th>结果</th><th>返回名称</th><th>错误</th><th>原文</th></tr>{''.join(case_rows)}</table></div></section><p class="muted">本页含本地回答内容；分享时使用 --public-out 导出的脱敏 JSON。</p></main></html>'''
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(document,encoding='utf-8')
