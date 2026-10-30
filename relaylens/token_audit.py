"""Independent counting evidence; consumption grades never affect intelligence grades.

All usage counters remain supplier claims. Official input counting establishes the
submitted payload size only, not hidden upstream prompts or private reasoning.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics

from .content_review import content_passed
from .evidence import checked_rows

VERSION = 'token-audit-1'
GRADE_LABELS = {'甲+':'极少', '甲':'少很多', '乙':'少一些', '丙':'平均',
                '丁':'多一些', '戊':'多很多', '戊+':'极多'}


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def normalize_usage(usage, api='responses'):
    """Normalize disjoint totals. None means unknown, including omitted cache fields."""
    usage = usage if isinstance(usage, dict) else {}
    issues = []
    def read(obj, key):
        value = obj.get(key)
        result = _number(value)
        if value is not None and result is None: issues.append('invalid_' + key)
        return result
    def detail(key):
        return usage.get(key) if isinstance(usage.get(key), dict) else {}
    if api == 'messages':
        ordinary = read(usage, 'input_tokens')
        cached = read(usage, 'cache_read_input_tokens')
        written = read(usage, 'cache_creation_input_tokens')
        total_input = sum((ordinary, cached, written)) if None not in (ordinary, cached, written) else None
        output = read(usage, 'output_tokens')
        reasoning = read(usage, 'reasoning_tokens')
        reported_total = read(usage, 'total_tokens')
    else:
        input_key = 'prompt_tokens' if api in ('chat', 'chat_completions') else 'input_tokens'
        output_key = 'completion_tokens' if input_key == 'prompt_tokens' else 'output_tokens'
        total_input, output = read(usage, input_key), read(usage, output_key)
        details = detail('prompt_tokens_details' if input_key == 'prompt_tokens' else 'input_tokens_details')
        cached = read(details, 'cached_tokens')
        written = read(details, 'cache_write_tokens')
        # A zero write count is only assumed for explicitly absent write details on
        # legacy APIs when deriving ordinary tokens is not needed; keep it unknown.
        ordinary = total_input - cached - written if None not in (total_input, cached, written) else None
        reasoning = read(detail('completion_tokens_details' if input_key == 'prompt_tokens' else 'output_tokens_details'), 'reasoning_tokens')
        reported_total = read(usage, 'total_tokens')
        if total_input is not None and cached is not None and cached > total_input:
            issues.append('cache_read_exceeds_input')
        if total_input is not None and written is not None and written > total_input:
            issues.append('cache_write_exceeds_input')
        if ordinary is not None and ordinary < 0:
            issues.append('cache_parts_exceed_input'); ordinary = None
    if reasoning is not None and output is not None and reasoning > output:
        issues.append('reasoning_exceeds_output')
    total = total_input + output if None not in (total_input, output) else None
    if total is not None and reported_total is not None and total != reported_total:
        issues.append('total_mismatch')
    return {'input_tokens':total_input, 'output_tokens':output, 'total_tokens':total,
            'ordinary_input_tokens':ordinary, 'cache_read_tokens':cached, 'cache_write_tokens':written,
            'reasoning_tokens':reasoning, 'reported_total_tokens':reported_total, 'issues':issues,
            'source':'provider_reported', 'cache_state':'unknown' if cached is None else 'read' if cached else 'no_read'}


def measure_payload(payload, api='responses', counter_model=None):
    """Offline estimate, with exact tokenizer only for explicitly registered models.

    Even a supported tokenizer counts serialized content, not private API framing.
    Never promote this estimate to exact whole-request evidence.
    """
    payload = payload if isinstance(payload, dict) else {}
    model = counter_model or payload.get('model') or ''
    subset = {k:payload[k] for k in ('input','messages','instructions','system','tools','tool_choice',
                                   'response_format','text') if k in payload}
    serialized = json.dumps(subset, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    result = {'input_tokens':max(1, math.ceil(len(serialized)/3)), 'method':'character_estimate',
              'exact':False, 'scope':'serialized_content_estimate', 'model':model, 'encoding':None,
              'text_chars':len(serialized), 'payload_hash':hashlib.sha256(canonical.encode()).hexdigest(),
              'limitations':['Unknown API framing and gateway-added content; not a billing ground truth.']}
    try:
        import tiktoken
        from tiktoken.model import MODEL_TO_ENCODING
        # No prefix fallback: new model names must not silently inherit an older tokenizer.
        if model in MODEL_TO_ENCODING:
            encoding = tiktoken.get_encoding(MODEL_TO_ENCODING[model])
            result.update(input_tokens=len(encoding.encode(serialized, disallowed_special=())),
                          method='local_text_tokenizer', encoding=encoding.name)
    except Exception:
        # Optional packages may fail while loading/downloading encoding assets.
        # Accounting must never discard an otherwise completed generation.
        pass
    return result


def fit_multiplier(observations):
    """OLS descriptive slope separates constant overhead from proportional changes.

    Only controlled probes with exact official input counts can yield an anomaly
    signal. This is not a fraud test or a model-identity probability.
    """
    pairs = [r for r in observations if isinstance(r, dict) and _number(r.get('input_tokens')) is not None
             and _number(r.get('reported_input_tokens')) is not None and r['input_tokens'] > 0]
    result = {'status':'insufficient_samples', 'n':len(pairs), 'slope':None, 'intercept_tokens':None,
              'r_squared':None, 'slope_standard_error':None, 'billing_truth':'not_established'}
    if len(pairs) < 3 or len({r['input_tokens'] for r in pairs}) < 3: return result
    xs, ys = [r['input_tokens'] for r in pairs], [r['reported_input_tokens'] for r in pairs]
    xbar, ybar = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x-xbar)**2 for x in xs)
    slope = sum((x-xbar)*(y-ybar) for x,y in zip(xs,ys))/sxx
    intercept = ybar-slope*xbar
    residual = sum((y-slope*x-intercept)**2 for x,y in zip(xs,ys))
    syy = sum((y-ybar)**2 for y in ys)
    stderr = math.sqrt(residual/(len(xs)-2)/sxx)
    controlled = all(r.get('controlled') is True for r in pairs)
    exact = all(r.get('exact') is True and r.get('method') == 'official_input_count' for r in pairs)
    span_ok = max(xs)/min(xs) >= 4
    status = 'descriptive_only'
    if controlled and exact and span_ok:
        # A conservative diagnostic guard, not a statistical confidence claim.
        status = 'proportional_excess_signal' if slope - 4*stderr > 1.15 else 'no_proportional_excess_observed'
    result.update(status=status, slope=slope, intercept_tokens=intercept,
                  r_squared=1-residual/syy if syy else None, slope_standard_error=stderr,
                  exact_input_counts=exact, controlled=controlled, adequate_length_span=span_ok,
                  diagnostic_threshold=1.15,
                  note='Slope is descriptive; fixed overhead, rewriting and upstream hidden content remain possible. No signal does not prove honest billing.')
    return result


def consumption_grade(ratio):
    ratio = _number(ratio)
    if ratio is None or ratio <= 0: return None
    if ratio < .2: return '甲+'
    if ratio < .6: return '甲'
    if ratio < .9: return '乙'
    if ratio <= 1.1: return '丙'
    if ratio <= 2: return '丁'
    if ratio < 3: return '戊'
    return '戊+'


def summarize_report(report):
    api = report.get('api_style', 'responses')
    rows, observations, controlled_observations = [], [], []
    for case in report.get('cases', []):
        observed = case.get('observed', {})
        normalized = normalize_usage(observed.get('usage'), api)
        measurement = observed.get('token_measurement') or {}
        rows.append({'id':case.get('id'), 'usage':normalized,
                     'measurement':measurement, 'request_id':observed.get('request_id')})
        if not normalized['issues']:
            observations.append(dict(measurement, reported_input_tokens=normalized['input_tokens'], controlled=False))
        if case.get('family') == 'token_control' and not normalized['issues']:
            controlled_observations.append(dict(measurement, reported_input_tokens=normalized['input_tokens'], controlled=True))
    controls = report.get('token_controls') or controlled_observations
    if controls: observations = controls
    sums, coverage = {}, {}
    for field in ('input_tokens','output_tokens','total_tokens','cache_read_tokens','cache_write_tokens','reasoning_tokens'):
        values = [r['usage'][field] for r in rows if r['usage'][field] is not None]
        sums[field] = sum(values) if len(values) == len(rows) and rows else None
        coverage[field] = {'known_requests':len(values), 'total_requests':len(rows),
                           'known_subtotal':sum(values) if values else None}
    measured = [r['measurement'] for r in rows if _number(r['measurement'].get('input_tokens')) is not None]
    independent = {'input_tokens':sum(m['input_tokens'] for m in measured) if measured else None,
                   'known_requests':len(measured),'total_requests':len(rows),
                   'all_official_counts':bool(measured) and all(m.get('method')=='official_input_count' for m in measured),
                   'all_exact':bool(measured) and all(m.get('exact') is True for m in measured),
                   'methods':sorted({m.get('method','unknown') for m in measured})}
    return {'independent_input':independent,'version':VERSION, 'status':'recorded' if rows else 'no_requests', 'source':'provider_reported',
            'request_count':len(rows), 'totals':sums, 'coverage':coverage, 'requests':rows,
            'multiplier':fit_multiplier(observations), 'consumption_grade':None,
            'grade_status':'official_matched_reference_required',
            'note':'Token consumption and money are separate. Hidden reasoning is already included in output; cached tokens are part of raw input. Intelligence grades are unaffected.'}


def compare_consumption(candidate, reference, *, trusted=False):
    """Equal-weight matched-task ratios avoid letting a single large task dominate.

    Full task coverage and passing answers on both sides are required, so a
    truncated or failed cheap answer cannot receive a favorable grade. Cache
    cohorts must match; this report does not certify paid charges.
    """
    result = {'status':'incompatible', 'grade':None, 'ratio':None, 'trusted_by_operator':bool(trusted),
              'scope':'reported_raw_tokens_on_matched_successful_tasks', 'price_grade':None,
              'threshold_policy':'product-bands-v1', 'thresholds_are_calibrated':False,
              'note':'Descriptive consumption comparison, not model intelligence, identity or a proof of actual upstream usage.'}
    if not isinstance(candidate, dict) or not isinstance(reference, dict): return result
    keys = ('suite_version','suite_commitment','seed','api_style','target_model')
    compatible = {k:candidate.get(k) is not None and candidate.get(k) == reference.get(k) for k in keys}
    ignored = {'efforts','fingerprint_samples','fingerprint_temperature','numeric_samples','numeric_version','mode'}
    def settings(report):
        value = report.get('settings')
        if not isinstance(value, dict): return None
        return {k:v for k,v in value.items() if k not in ignored}
    compatible['settings'] = settings(candidate) is not None and settings(candidate) == settings(reference)
    compatible['distinct_run'] = not (candidate.get('run_id') and candidate.get('run_id') == reference.get('run_id'))
    result['compatible'] = compatible
    if not all(compatible.values()): return result
    if not trusted:
        result['status'] = 'untrusted_reference'; return result
    try:
        left, right = checked_rows(candidate), checked_rows(reference)
    except (ValueError, TypeError):
        result['status'] = 'invalid_report'; return result
    if left.keys() != right.keys():
        result['status'] = 'task_coverage_mismatch'; return result
    ratios, pairs, cache_cohorts = [], [], {}
    for key in sorted(left):
        a, b = left[key], right[key]
        if a['prompt_hash'] != b['prompt_hash'] or a.get('family') != b.get('family'):
            result['status'] = 'task_mismatch'; return result
        if not content_passed(a) or not content_passed(b):
            result['status'] = 'quality_not_comparable'; return result
        ua = normalize_usage(a['observed'].get('usage'), candidate['api_style'])
        ub = normalize_usage(b['observed'].get('usage'), reference['api_style'])
        if ua['issues'] or ub['issues'] or ua['total_tokens'] is None or ub['total_tokens'] is None:
            result['status'] = 'missing_or_inconsistent_usage'; return result
        if ua['total_tokens'] <= 0 or ub['total_tokens'] <= 0:
            result['status'] = 'invalid_zero_usage'; return result
        if ua['cache_state'] == 'unknown' or ub['cache_state'] == 'unknown':
            result['status'] = 'cache_evidence_missing'; return result
        if ua['cache_state'] != ub['cache_state']:
            result['status'] = 'cache_cohort_mismatch'; return result
        ratio = ua['total_tokens']/ub['total_tokens']
        ratios.append(ratio)
        cache_cohorts.setdefault(ua['cache_state'], []).append(ratio)
        pairs.append({'id':key,'ratio':ratio, 'candidate_tokens':ua['total_tokens'],
                      'reference_tokens':ub['total_tokens'], 'cache_state':ua['cache_state']})
    # Geometric mean gives each matched task the same weight independent of size.
    ratio = math.exp(statistics.mean(math.log(r) for r in ratios))
    grade = consumption_grade(ratio)
    result.update(status='compared', grade=grade, label=GRADE_LABELS[grade], ratio=ratio,
                  matched_tasks=len(pairs), unique_tasks=len({r['prompt_hash'] for r in left.values()}),
                  aggregation='equal_task_geometric_mean', pairs=pairs,
                  cache_cohorts={k:{'n':len(v),'ratio':math.exp(statistics.mean(math.log(x) for x in v))} for k,v in cache_cohorts.items()},
                  generalization='this_fixed_suite_and_run_only')
    return result
