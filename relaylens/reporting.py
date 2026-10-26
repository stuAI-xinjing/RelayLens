"""Local HTML report, and secret scrubbing even when an API echoes the key."""
import html
import json
import re
import base64
import urllib.parse
from pathlib import Path


def clean_local(value, secrets=()):
    if isinstance(value,dict):
        return {k:clean_local(v,secrets) for k,v in value.items() if k.lower() not in ('api_key','authorization','cookie','x-api-key')}
    if isinstance(value,list):
        return [clean_local(v,secrets) for v in value]
    if isinstance(value,str):
        for secret in secrets:
            if secret:
                for form in (secret,urllib.parse.quote(secret,safe=''),base64.b64encode(secret.encode()).decode()):
                    value = value.replace(form,'[REDACTED]')
        value = re.sub(r'(?i)Bearer\s+[^\s"<>]+','Bearer [REDACTED]',value)
        value = re.sub(r'\b(?:sk|sess)-[A-Za-z0-9_-]{8,}','[REDACTED]',value)
    return value


def write_html(report,path):
    esc = lambda v: html.escape(str(v))
    verdict = report['verdict']
    summary = report.get('task_summary',{})
    labels = {'logic':'约束逻辑','arithmetic':'基础计算','code_repair':'表达式修复','instruction':'精确指令',
              'algorithm':'路径算法','optimization':'调度优化','long_context':'上下文检索','state_tracking':'状态追踪',
              'constraint_optimization':'多约束最优化','exact_probability':'精确概率','data_reasoning':'数据关联',
              'context_integrity':'上下文版本检索','frontend_state':'前端异步状态','backend_transactions':'后端事务'}
    family_rows = ''.join(f'<tr><td>{esc(labels.get(name,name))}</td><td>{r["passed"]}/{r["planned"]}</td><td>{r["completed"]}</td><td><meter min="0" max="1" value="{r["accuracy"]}"></meter> {r["accuracy"]:.1%}</td></tr>' for name,r in summary.items())
    diagnostics = report.get('diagnostics',{})
    timing_rows = ''.join(f'<tr><td>{esc(name)}</td><td>{esc(r["total_ms"]["median"])}</td><td>{esc(r["total_ms"]["p95"])}</td><td>{esc(r["first_token_ms"]["median"])}</td></tr>' for name,r in diagnostics.get('latency_by_family',{}).items())
    case_rows = []
    for row in report.get('cases',[]):
        obs = row.get('observed',{})
        case_rows.append(f'<tr><td>{esc(row["id"])}</td><td>{esc(obs.get("http_status"))}</td><td>{"通过" if row.get("grade",{}).get("passed") and row.get("completed") else "失败" if "grade" in row else "完成" if row.get("completed") else "失败"}</td><td>{esc(obs.get("model_returned"))}</td><td>{esc(obs.get("error") or "")}</td><td><details><summary>回答</summary><pre>{esc(obs.get("text",""))}</pre></details></td></tr>')
    reasons = ''.join(f'<li>{esc(x)}</li>' for x in verdict.get('reasons',[]) + verdict.get('limitations',[]))
    comparison = esc(json.dumps(report.get('reference_comparison',{'status':'未提供可信官方参考'}),ensure_ascii=False,indent=2))
    stability = esc(json.dumps(diagnostics.get('stability',{}),ensure_ascii=False,indent=2))
    quality = report.get('quality_profile',{})
    def percent(value): return '样本不足' if value is None else f'{value:.1%}'
    metrics = ''.join(f'<div class="card"><span class="muted">{label}</span><div class="grade">{esc(value)}</div></div>' for label,value in (
        ('全部任务正确率',percent(quality.get('strict_accuracy'))),('请求完成率',percent(quality.get('completion_rate'))),
        ('完成后的正确率',percent(quality.get('completed_accuracy'))),('同题每次均通过',percent(quality.get('all_repeats_pass_rate')))))
    status_labels = {'within_margin':'能力差距在容差内','below_reference':'能力低于此参考','service_degradation':'服务失败干扰判断',
                     'inconclusive':'证据不足以定论','insufficient_samples':'有效样本不足','incompatible':'题目或设置不兼容',
                     'invalid_report':'报告记录无效','unsupported_target':'非 GPT/Claude 参考'}
    panel = report.get('reference_panel',{})
    panel_rows = ''
    for row in panel.get('comparisons',[]):
        loss = row.get('mean_loss')
        label = status_labels.get(row.get('status'),row.get('status'))
        if not row.get('trusted_by_operator'): label = '参考未核实 · ' + str(label)
        panel_rows += f'<tr><td>{esc(row.get("target_model"))}</td><td>{esc(label)}</td><td>{esc(row.get("unique_tasks","—"))}</td><td>{"—" if loss is None else f"{loss:+.1%}"}</td></tr>'
    if not panel_rows: panel_rows = '<tr><td colspan="4">尚未导入官方参考。当前只显示本套题表现，不能换算成某个型号的智力。</td></tr>'
    document = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>RelayLens 中转透镜</title>
<style>body{{font:15px/1.6 system-ui,"Microsoft YaHei",sans-serif;background:#f3f6fa;color:#203049;margin:0}}main{{max-width:1200px;margin:auto;padding:28px}}.card{{background:white;padding:24px;border:1px solid #dce3ec;border-radius:14px;margin:16px 0}}h1{{margin-bottom:4px}}h2{{font-size:18px}}.grade{{font-size:28px;color:#2254aa}}.muted{{color:#627087}}table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;padding:10px;border-bottom:1px solid #e4e9f0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}.scroll{{overflow:auto}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}}.grid>.card{{margin:0}}meter{{width:100px}}summary{{cursor:pointer}}@media(max-width:600px){{main{{padding:10px}}.card{{padding:15px}}}}</style>
<main><h1>RelayLens · 中转透镜</h1><p class="muted">目标 {esc(report.get('target_model'))} · 请求 ID {esc(report.get('model_requested'))} · {esc(report.get('api_style'))} · seed {esc(report.get('seed'))}</p>
<section class="card"><div class="grade">{esc(verdict['grade'])} · {esc(verdict['label'])}</div><p>能力状态：{esc(verdict.get('capability_status'))}　身份：尚未证明</p><ul>{reasons}</ul></section>
<div class="grid">{metrics}</div>
<section class="card"><h2>GPT / Claude 能力参考对照</h2><p>差距为“参考正确率 − 本次正确率”，正数表示本次更低。多个型号都相符时，题库尚不能区分它们。</p><div class="scroll"><table><tr><th>参考型号</th><th>比较结果</th><th>独立题数</th><th>平均差距</th></tr>{panel_rows}</table></div></section>
<section class="card"><h2>任务能力 · 失败和截断计入总数</h2><div class="scroll"><table><tr><th>类别</th><th>通过/计划</th><th>完成</th><th>正确率</th></tr>{family_rows}</table></div></section>
<div class="grid"><section class="card"><h2>可信参考与能力差距</h2><details><summary>查看统计依据</summary><pre>{comparison}</pre></details></section><section class="card"><h2>多轮稳定性与混用线索</h2><details><summary>查看重复结果</summary><pre>{stability}</pre></details><p class="muted">同题波动、名称变化可能由路由、采样、缓存或限额引起，需复测。</p></section></div>
<section class="card"><h2>延迟分布 · 单位毫秒</h2><p>按任务类别统计成功请求；延迟不能单独鉴定身份。</p><div class="scroll"><table><tr><th>类别</th><th>总耗时中位</th><th>P95</th><th>首文本 token 中位</th></tr>{timing_rows}</table></div></section>
<section class="card"><h2>逐次请求证据</h2><div class="scroll"><table><tr><th>测试</th><th>HTTP</th><th>结果</th><th>返回名称</th><th>错误</th><th>原文</th></tr>{''.join(case_rows)}</table></div></section><p class="muted">本页含本地回答内容；分享时使用 --public-out 导出的脱敏 JSON。</p></main></html>'''
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(document,encoding='utf-8')
