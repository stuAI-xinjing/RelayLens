"""Local HTML report, and secret scrubbing even when an API echoes the key."""
import html
import json
import re
import base64
import urllib.parse
from pathlib import Path
from .content_review import content_passed


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
    family_rows = ''.join(f'<tr><td>{esc(labels.get(name,name))}</td><td>{r.get("content_passed",r["passed"])}/{r["planned"]}（严格 {r["passed"]}）</td><td>{r["completed"]}</td><td><meter min="0" max="1" value="{r.get("content_accuracy",r["accuracy"])}"></meter> {r.get("content_accuracy",r["accuracy"]):.1%}</td></tr>' for name,r in summary.items())
    diagnostics = report.get('diagnostics',{})
    timing_rows = ''.join(f'<tr><td>{esc(name)}</td><td>{esc(r["total_ms"]["median"])}</td><td>{esc(r["total_ms"]["p95"])}</td><td>{esc(r["first_token_ms"]["median"])}</td></tr>' for name,r in diagnostics.get('latency_by_family',{}).items())
    case_rows = []
    for row in report.get('cases',[]):
        obs = row.get('observed',{})
        grade = row.get('grade',{})
        diagnosis = ('内容正确 / 格式不符' if content_passed(row) and not grade.get('passed') else
                     '内容及格式通过' if content_passed(row) else '内容未完全正确' if row.get('completed') else '未完成') if grade else '接口检查'
        component = grade.get('component_score')
        diagnosis += '' if component is None else f'；分项 {component:.1%}（仅诊断）'
        case_rows.append(f'<tr><td>{esc(row["id"])}</td><td>{esc(obs.get("http_status"))}</td><td>{"通过" if row.get("grade",{}).get("passed") and row.get("completed") else "失败" if "grade" in row else "完成" if row.get("completed") else "失败"}</td><td>{esc(diagnosis)}</td><td>{esc(obs.get("model_returned"))}</td><td>{esc(obs.get("error") or "")}</td><td><details><summary>回答</summary><pre>{esc(obs.get("text",""))}</pre></details></td></tr>')
    reasons = ''.join(f'<li>{esc(x)}</li>' for x in verdict.get('reasons',[]))
    limitations = ''.join(f'<li>{esc(x)}</li>' for x in verdict.get('limitations',[]))
    grade_guide = ''.join(f'<p><b>{esc(k if k!="U" else "未完成")}</b> · {esc(v)}</p>' for k,v in verdict.get('grade_guide',{}).items())
    usability = verdict.get('usability',{})
    usability_notes = ''.join(f'<li>{esc(x)}</li>' for x in usability.get('notes',[]))
    usability_text = {'checks_passed':'本轮参数与受支持的工具检查通过。','issues_found':'有接口功能需要复核，能力分数单独保留。',
                      'partially_checked':'部分接口检查未记录，请结合实际用途确认。'}.get(usability.get('status'),'未记录接口检查。')
    identity = verdict.get('identity_signal',{})
    elapsed=report.get('run_state',{}).get('elapsed_seconds')
    mode_label='限时快速检查' if report.get('run_state',{}).get('mode')=='fast' else '完整检测'
    screening=verdict.get('screen_grade',verdict['grade'])
    grade_name=screening if screening!='U' else '—'
    screen_label=({'A':'本轮能力达标，值得试用','B':'基本可用，仍有短板','C':'本轮答题存在失误',
                   'D':'本轮答题明显不足','U':'检测未完成'}.get(screening,screening)
                  if verdict.get('evidence_basis')=='official_reference' else verdict['label'])
    comparison = esc(json.dumps(report.get('reference_comparison',{'status':'未提供可信官方参考'}),ensure_ascii=False,indent=2))
    stability = esc(json.dumps(diagnostics.get('stability',{}),ensure_ascii=False,indent=2))
    quality = report.get('quality_profile',{})
    def percent(value): return '样本不足' if value is None else f'{value:.1%}'
    metrics = ''.join(f'<div class="card"><span class="muted">{label}</span><div class="grade">{esc(value)}</div></div>' for label,value in (
        ('内容完全正确率',percent(quality.get('content_accuracy'))),('严格格式正确率',percent(quality.get('strict_accuracy'))),('题目完成率',percent(quality.get('completion_rate'))),
        ('已完成 / 计划题数',f'{quality.get("completed",0)} / {quality.get("attempts",0)}'),('本轮用时','—' if elapsed is None else f'{elapsed:.1f} 秒')))
    status_labels = {'above_reference':'本套题充分支持优于此参考','within_margin':'能力差距在容差内','below_reference':'能力低于此参考','service_degradation':'服务失败干扰判断',
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
    numeric = report.get('numeric_summary',{})
    numeric_labels = {'not_requested':'未启用或参考未采集','collected':'已采集',
        'distribution_shift':'行为分布有差异','no_shift_detected':'本次未检出差异（不证明相同）',
        'answer_text_unavailable':'脱敏报告无原文，不能重算行为指纹','invalid_report':'记录不完整或无效',
        'incompatible_settings':'探针或采样参数不一致','invalid_or_incomplete_samples':'完整有效回答不足，暂不检验',
        'insufficient_samples':'配对请求不足30次'}
    numeric_rows = ''
    for row in report.get('numeric_reference_panel',{}).get('comparisons',[]):
        label = numeric_labels.get(row.get('status'),row.get('status'))
        if not row.get('trusted_by_operator'): label = '参考未核实 · '+str(label)
        pvalue = row.get('permutation_p')
        numeric_rows += f'<tr><td>{esc(row.get("target_model"))}</td><td>{esc(label)}</td><td>{esc(row.get("paired_requests","—"))}</td><td>{"—" if pvalue is None else f"{pvalue:.4f}"}</td></tr>'
    if not numeric_rows: numeric_rows = '<tr><td colspan="4">尚无可比较的数字序列参考。</td></tr>'
    numeric_evidence = esc(json.dumps(report.get('numeric_reference_panel',numeric),ensure_ascii=False,indent=2))
    token_section = token_html(report)
    document = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>RelayLens 中转透镜</title>
<style>body{{font:15px/1.6 system-ui,"Microsoft YaHei",sans-serif;background:#f3f6fa;color:#203049;margin:0}}main{{max-width:1200px;margin:auto;padding:28px}}.card{{background:white;padding:24px;border:1px solid #dce3ec;border-radius:14px;margin:16px 0}}h1{{margin-bottom:4px}}h2{{font-size:18px}}.grade{{font-size:28px;color:#2254aa}}.muted{{color:#627087}}table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;padding:10px;border-bottom:1px solid #e4e9f0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}.scroll{{overflow:auto}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}}.grid>.card{{margin:0}}meter{{width:100px}}summary{{cursor:pointer;font-weight:600}}.hero{{border-left:6px solid #d29a16}}.status-S,.status-A,.status-B{{border-left-color:#16815b}}.status-D{{border-left-color:#c93a3a}}.status-U{{border-left-color:#79859a}}.status-S .grade,.status-A .grade,.status-B .grade{{color:#126b4b}}.status-D .grade{{color:#ac2929}}.action{{background:#f3f6fa;padding:14px;border-radius:9px}}@media(max-width:600px){{main{{padding:10px}}.card{{padding:15px}}}}</style>
<main><h1>RelayLens · 中转透镜</h1><p class="muted">{esc(mode_label)} · 目标 {esc(report.get('target_model'))}</p>
<section class="card hero status-{esc(verdict.get('target_grade','U'))}"><div class="grade">目标能力：{esc(verdict.get("target_label","尚未验证"))}</div><p>目标等级：{esc(verdict.get("target_grade","U"))} · {esc(report.get("target_model"))}。U 表示未验证，不表示能力差。</p><hr><p class="muted">本轮答题筛查（不能单独换算为型号档位）</p><div class="grade">{esc(grade_name)} · {esc(screen_label)}</div><p>{esc(verdict.get('summary',''))}</p><p class="muted">依据：{esc(verdict.get('basis_label','旧版评级'))} · {esc(verdict.get('target_assessment',''))}</p><ul>{reasons}</ul><p class="action"><b>下一步：</b>{esc(verdict.get('action','查看下方依据'))}</p><details><summary>等级是什么意思？</summary>{grade_guide}<ul>{limitations}</ul></details></section>
<div class="grid">{metrics}</div><p class="muted">{esc(verdict.get("sample_note",""))} 内容全对率的首轮 Wilson 95% 描述区间：{esc("—" if not quality.get("content_wilson_95_first_attempt") else " ～ ".join(percent(v) for v in quality["content_wilson_95_first_attempt"]))}。同类题可能相关；这不是达到目标的概率。</p>
<div class="grid"><section class="card"><h2>接口可用性</h2><p>{esc(usability_text)}</p><ul>{usability_notes}</ul></section><section class="card"><h2>身份与行为线索 · 不计入能力等级</h2><p>{esc(identity.get('summary','未记录身份线索。'))}</p></section></div>
<section class="card"><details {"open" if panel.get('comparisons') else ""}><summary>官方参考对照 · {"已提供" if panel.get('comparisons') else "未提供"}</summary><p>正式对照保留严格整题评分（含格式），不使用分项分数。差距为“参考正确率 − 本次正确率”，正数表示本次更低。多个型号都相符时，题库尚不能区分它们。</p><div class="scroll"><table><tr><th>参考型号</th><th>比较结果</th><th>独立题数</th><th>平均差距</th></tr>{panel_rows}</table></div></details></section>
{token_section}
<section class="card"><h2>任务能力 · 失败和截断计入总数</h2><div class="scroll"><table><tr><th>类别</th><th>内容全对/计划（严格通过）</th><th>完成</th><th>正确率</th></tr>{family_rows}</table></div></section>
<section class="card" {"hidden" if numeric.get('status') in (None,'not_requested') else ""}><h2>数字序列行为指纹 · 可选辅助证据</h2><p>{esc(numeric_labels.get(numeric.get('status'), '未启用'))}；有效回答 {esc(numeric.get('valid_requests',0))} / {esc(numeric.get('planned_requests',0))} 次。一次回答是一个样本，数组中的整数不算独立请求。该项不计入能力分数。</p><div class="scroll"><table><tr><th>参考型号</th><th>行为结果</th><th>配对请求</th><th>置换 p 值</th></tr>{numeric_rows}</table></div><p class="muted">p 值不是“真模型概率”。提示词、采样、时间变化也可能造成差异；没有检出差异不能排除混用。</p><details><summary>查看检验依据与无效回答原因</summary><pre>{numeric_evidence}</pre></details></section>
<div class="grid"><section class="card"><h2>可信参考与能力差距</h2><details><summary>查看统计依据</summary><pre>{comparison}</pre></details></section><section class="card"><h2>多轮稳定性与混用线索</h2><details><summary>查看重复结果</summary><pre>{stability}</pre></details><p class="muted">同题波动、名称变化可能由路由、采样、缓存或限额引起，需复测。</p></section></div>
<section class="card"><details><summary>耗时明细</summary><p>单位毫秒；按任务类别统计成功请求；延迟不能单独鉴定身份。</p><div class="scroll"><table><tr><th>类别</th><th>总耗时中位</th><th>P95</th><th>首文本 token 中位</th></tr>{timing_rows}</table></div></details></section>
<section class="card"><details><summary>逐次请求证据与原始回答</summary><p>请求 ID {esc(report.get('model_requested'))} · {esc(report.get('api_style'))} · seed {esc(report.get('seed'))}</p><div class="scroll"><table><tr><th>测试</th><th>HTTP</th><th>结果</th><th>内容诊断</th><th>返回名称</th><th>错误</th><th>原文</th></tr>{''.join(case_rows)}</table></div></details></section><p class="muted">本页含本地回答内容；分享时使用 --public-out 导出的脱敏 JSON。</p></main></html>'''
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(document,encoding='utf-8')


def token_html(report):
    """Independent raw-token accounting; deliberately separate from capability."""
    esc = lambda v: html.escape(str(v))
    audit = report.get('token_audit',{})
    from .token_display import format_tokens, token_rows
    totals = audit.get('totals',{})
    coverage = audit.get('coverage',{})
    def amount(key):
        value = totals.get(key)
        if value is not None: return format_tokens(value)
        known = coverage.get(key,{})
        subtotal = known.get('known_subtotal')
        return '未上报' if subtotal is None else f'已知 {subtotal:,.0f}（{known.get("known_requests",0)}/{known.get("total_requests",0)} 次）'
    table = ''.join(f'<tr><td>{esc(row["label"])}</td><td>{esc(row["display"] if row["value"] is not None else amount(row["field"]))}</td></tr>'
                    for row in token_rows(audit))
    statuses = {'compared':'已完成同题对照','incompatible':'题目、型号或配置不一致','untrusted_reference':'官方参考来源尚未核实',
        'task_coverage_mismatch':'两侧任务覆盖不一致','task_mismatch':'任务内容不一致','quality_not_comparable':'两侧答案质量尚不可比',
        'missing_or_inconsistent_usage':'用量字段缺失或自相矛盾','invalid_zero_usage':'存在零用量异常',
        'cache_evidence_missing':'缓存证据缺失','cache_cohort_mismatch':'缓存状态不同','invalid_report':'参考报告无效'}
    comparisons = report.get('token_reference_panel',{}).get('comparisons',[])
    grades = ''.join(f'<p><b>{esc(r.get("grade") or "待对照")} · {esc(r.get("label") or statuses.get(r.get("status"),r.get("status")))}</b>'
        + (f' · 官方同题消耗的 {r["ratio"]:.2f} 倍 · {r.get("matched_tasks",0)} 次配对' if r.get('ratio') is not None else '') + '</p>' for r in comparisons)
    if not grades: grades = '<p><b>Token 消耗评级：待对照</b> · 尚无可信同题官方用量参考。</p>'
    independent = audit.get('independent_input',{})
    independent_text = '独立输入计数尚不可用。'
    if independent.get('input_tokens') is not None:
        source = '官方计数接口' if independent.get('all_official_counts') else '本机估算，不能据此认定虚报'
        independent_text = f'独立输入计数：{independent["input_tokens"]:,.0f}（{source}；覆盖 {independent.get("known_requests",0)}/{independent.get("total_requests",0)} 次）。'
    slope = audit.get('multiplier',{})
    slope_labels = {'insufficient_samples':'有效长度样本不足','descriptive_only':'仅描述趋势；计数或控制条件不足',
        'proportional_excess_signal':'检出输入随长度成比例偏高的线索，需结合账单复核',
        'no_proportional_excess_observed':'本次未检出比例偏高；不等于证明账单真实'}
    slope_text = slope_labels.get(slope.get('status'),'尚未采集')
    if slope.get('slope') is not None:
        slope_text += f'；斜率 {slope["slope"]:.3f}，固定差额估计 {slope["intercept_tokens"]:.0f} token'
    bill = report.get('billing',{})
    bill_text = '尚未完成后台对账；在本地账单页面连接支持的接口，或导入整份账单。'
    if bill:
        cov = bill.get('coverage')
        bill_text = f'账单匹配：{bill.get("matched",0)} 次'
        if isinstance(cov,(int,float)): bill_text += f'，覆盖 {cov:.0%}'
        bill_text += '。接口和后台同属站方数据，彼此一致仍不代表上游真实计量。'
    summary = report.get('billing_summary') or {}
    if summary:
        summary_label = {'within_display_precision':'汇总数值在显示精度范围内一致',
                         'aggregate_difference':'汇总数值存在差异',
                         'not_comparable':'汇总范围或字段不足，暂不能比较'}.get(summary.get('status'), '汇总待核对')
        bill_text += ' 汇总核对：' + summary_label + '。仅比较汇总值，时间和 Key 范围未独立核实。'
    return f'''<section class="card" id="token-audit"><h2>Token 消耗 · 独立于能力 S/A/B/C/D</h2>{grades}
<p class="muted">甲＋极少 / 甲少很多 / 乙少一些 / 丙平均 / 丁多一些 / 戊多很多 / 戊＋极多。比较原始 token 数量，缓存折扣和实际金额单列。</p>
<div class="scroll"><table><tr><th>接口上报用量</th><th>本轮合计</th></tr>{table}</table></div>
<p>{esc(independent_text)}</p><p>{esc(slope_text)}</p><p>{esc(bill_text)}</p><p class="muted">本机计数无需大模型；未知 tokenizer 为估算，不能当成真实计费值。隐藏推理和中转追加内容无法从可见回答完全还原。</p>
<details><summary>消费等级标准与完整证据</summary><p>同题配对比值的几何平均 R：甲＋ 0&lt;R&lt;0.2；甲 0.2≤R&lt;0.6；乙 0.6≤R&lt;0.9；丙 0.9≤R≤1.1；丁 1.1&lt;R≤2；戊 2&lt;R&lt;3；戊＋ R≥3。这是公开的产品分段，不是科学认证标准。缺数据、零用量、截断或答案质量不足不会评成甲＋。</p>
<pre>{esc(json.dumps({'accounting':audit,'consumption':comparisons,'billing':bill},ensure_ascii=False,indent=2))}</pre></details></section>'''
