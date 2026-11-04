"""Evidence-separated usage checks; no inferred hidden-token ground truth."""
import statistics


def analyze(report):
    from .token_audit import normalize_usage, fit_multiplier
    api = report.get('api_style', 'responses')
    cases = report.get('cases') or []
    groups, samples = {}, []
    invalid, missing, controls, usable = 0, 0, 0, 0
    hidden, output = 0, 0
    hidden_known = True
    for case in cases:
        obs = case.get('observed') or {}
        usage = normalize_usage(obs.get('usage'), api)
        invalid += bool(usage['issues'])
        missing += usage['input_tokens'] is None or usage['output_tokens'] is None
        if usage['reasoning_tokens'] is None or usage['output_tokens'] is None or usage['issues']:
            hidden_known = False
        else:
            hidden += usage['reasoning_tokens']; output += usage['output_tokens']
        if case.get('family') != 'token_control':
            continue
        controls += 1
        if not case.get('completed') or usage['issues'] or usage['input_tokens'] is None or obs.get('text', '').strip() != 'OK':
            continue
        usable += 1
        key = obs.get('payload_hash')
        measurement = obs.get('token_measurement') or {}
        if key:
            group = groups.setdefault(key, {'inputs': [], 'cache': [], 'reference': []})
            group['inputs'].append(usage['input_tokens'])
            if usage['cache_read_tokens'] is not None: group['cache'].append(usage['cache_read_tokens'])
            if type(measurement.get('input_tokens')) in (int,float):
                group['reference'].append(measurement['input_tokens'])
        samples.append(dict(measurement, reported_input_tokens=usage['input_tokens'], controlled=True))
    repeated, varying, material, cache_changes = 0, 0, 0, 0
    summaries = []
    for group in groups.values():
        values = group['inputs']
        delta = max(values)-min(values)
        median = statistics.median(values)
        repeated += len(values) >= 2
        varying += len(values) >= 2 and delta > 0
        # Diagnostic tolerance, not a fraud probability or confidence interval.
        material += len(values) >= 2 and delta > max(2, .01*median)
        cache_changes += len(set(group['cache'])) > 1
        summaries.append({'repeats':len(values), 'input_min':min(values), 'input_max':max(values),
                          'input_median':median, 'cache_varied':len(set(group['cache']))>1})
    fit = fit_multiplier(samples)
    adequate = repeated >= 3 and usable >= 6 and fit.get('adequate_length_span') is True
    exact = fit.get('exact_input_counts') is True
    if invalid:
        status, label = 'inconsistent_fields', '接口用量字段存在自相矛盾'
    elif material:
        status, label = 'unstable_input_counts', '相同请求的输入计数明显波动'
    elif adequate and exact and fit['status'] == 'proportional_excess_signal':
        status, label = 'input_excess_signal', '受控输入增量偏高，需核查追加内容或计数倍率'
    elif adequate and exact:
        status, label = 'no_input_signal', '本轮未检出明显输入计数异常'
    elif adequate:
        status, label = 'independent_reference_needed', '已测重复计数与长度变化；真实倍率仍缺独立基准'
    elif controls:
        status, label = 'incomplete_controls', '受控样本不足，不能可靠判断输入倍率'
    else:
        status, label = 'ordinary_task_usage', '当前是任务用量记录，尚未执行用量专项'
    reasons = []
    if not controls: reasons.append('普通能力题的提示、工具和输出各不相同；混合题目的斜率不能直接当作收费倍率。')
    if controls and not adequate: reasons.append('需要至少3档不同长度，每档至少2次完整且回答 OK 的相同请求，并有足够输入跨度。')
    if not exact: reasons.append('当前缺少独立且精确的官方输入计数；字符估算和中转自己的计数接口都不能证明真实倍率。')
    if material: reasons.append('同一 payload 的总输入计数变化可能来自动态前置提示、路由或计数错误；不是恶意收费的直接证明。')
    if invalid: reasons.append('请核查 total、input、output、缓存和推理字段的口径；协议适配错误也会造成自相矛盾。')
    if missing: reasons.append(f'{missing} 次请求缺少完整输入或输出计数，缺失不按零处理。')
    return {'status':status,'label':label,'invalid_usage_requests':invalid,'missing_usage_requests':missing,
            'control_requests':controls,'usable_controls':usable,'repeated_payload_groups':repeated,
            'varying_input_groups':varying,'material_variation_groups':material,'cache_changed_groups':cache_changes,
            'groups':summaries,'fit':fit,'adequate_controls':adequate,'reasons':reasons,
            'hidden_output_fraction':hidden/output if hidden_known and output else None,
            'upstream_truth':'not_independently_verified',
            'note':'只核验本轮可观察证据；输入未见异常不证明隐藏推理、后台扣费或上游全部真实。消耗等级与能力等级均不由这些检查代替。'}

