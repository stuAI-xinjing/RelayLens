"""Multi-signal evidence with explicit reference and sample-size boundaries."""
import math
import hashlib
import random
import statistics
from collections import Counter, defaultdict

from .model_targets import tool_expected


def distribution(values):
    values = sorted(float(x) for x in values if isinstance(x, (int, float)) and math.isfinite(x) and x >= 0)
    if not values:
        return {"n": 0, "median": None, "p95": None, "mad": None}
    median = statistics.median(values)
    return {"n": len(values), "median": median, "p95": values[math.ceil(.95 * len(values)) - 1],
            "mad": statistics.median(abs(x - median) for x in values)}


def diagnostics(cases):
    groups, families = defaultdict(list), defaultdict(list)
    for row in cases:
        families[row['family']].append(row)
        if 'grade' in row:
            groups[row['case_id']].append(row)
    timing, styles = {}, {}
    for family, rows in families.items():
        # Never pool failed, short protocol and long reasoning requests together.
        successful = [r.get('observed', {}) for r in rows if r.get('completed')]
        timing[family] = {"total_ms": distribution([r.get('latency_ms') for r in successful]),
                          "first_token_ms": distribution([r.get('first_token_ms') for r in successful])}
        texts = [r.get('text','') for r in successful if r.get('text')]
        styles[family] = {'n':len(texts), 'mean_chars':statistics.mean(map(len,texts)) if texts else None,
                          'json_like_rate':sum(x.lstrip().startswith(('{','[')) for x in texts)/len(texts) if texts else None,
                          'markdown_fence_rate':sum('```' in x for x in texts)/len(texts) if texts else None,
                          'note':'Prompt-sensitive descriptive features; never scored as model identity.'}
    flips = [key for key, rows in groups.items() if len(rows) >= 2 and
             len({bool(r.get('completed') and r['grade'].get('passed')) for r in rows}) > 1]
    comparable = sum(len(rows) >= 2 for rows in groups.values())
    models = Counter(r.get('observed', {}).get('model_returned') for r in cases if r.get('completed'))
    models.pop(None, None)
    signals = []
    if flips:
        signals.append('same_task_pass_fail_changes')
    if len(models) > 1:
        signals.append('returned_model_label_changes')
    return {"latency_by_family": timing, 'answer_style_by_family':styles, "returned_models": dict(models),
            "stability": {"repeated_tasks": comparable, "pass_fail_flip_tasks": flips,
                          "flip_rate": len(flips)/comparable if comparable else None,
                          "mixture_status": 'signals_detected' if signals else 'no_signal_observed' if comparable else 'insufficient_samples',
                          "signals": signals,
                          "note": 'Stochastic answers, limits and caching also cause changes. No observed change does not rule out mixing.'}}


def js_divergence(a, b):
    a, b = Counter(a), Counter(b)
    na, nb = sum(a.values()), sum(b.values())
    if not na or not nb:
        return None
    total = 0.0
    for key in a.keys() | b.keys():
        p, q = a[key]/na, b[key]/nb
        mid = (p+q)/2
        if p:
            total += .5*p*math.log2(p/mid)
        if q:
            total += .5*q*math.log2(q/mid)
    return total


def compare_fingerprints(candidate, reference, seed=0, alpha=.05):
    """Descriptive JSD plus permutation tests; no borrowed model-ID thresholds."""
    left, right = defaultdict(list), defaultdict(list)
    hashes = defaultdict(set)
    for rows, dest in ((candidate, left), (reference, right)):
        for row in rows:
            text = row.get('observed', {}).get('text')
            if row.get('family') == 'fingerprint' and row.get('completed') and isinstance(text, str) and text.strip():
                dest[row['case_id']].append(text.strip().casefold())
                hashes[row['case_id']].add(row.get('prompt_hash'))
    results = []
    rng = random.Random(seed)
    cells = sorted(left.keys() & right.keys())
    for key in cells:
        a, b = left[key], right[key]
        observed = js_divergence(a, b)
        p = None
        if min(len(a), len(b)) >= 20 and len(hashes[key]) == 1 and None not in hashes[key]:
            pool = a + b
            greater = 1
            for _ in range(399):
                rng.shuffle(pool)
                greater += js_divergence(pool[:len(a)], pool[len(a):]) >= observed - 1e-12
            p = greater/400
        results.append({"probe": key, "candidate_n": len(a), "reference_n": len(b),
                        "jsd_bits": observed, "permutation_p": p, 'prompt_match':len(hashes[key]) == 1 and None not in hashes[key]})
    usable = [r for r in results if r['permutation_p'] is not None]
    drift = any(r['permutation_p'] < alpha/max(len(usable), 1) for r in usable)
    return {"status": 'distribution_shift' if drift else 'no_shift_detected' if usable else 'insufficient_samples',
            "cells": results, "minimum_per_cell": 20, "multiple_test_correction": 'Bonferroni',
            'alpha':alpha,'minimum_resolvable_p':1/400,
            "note": 'Same prompts and sampling settings required; this is behavior evidence, not model identity probability.'}


def checked_rows(report):
    """Reject duplicate IDs and malformed grading records before inference."""
    rows = report.get('cases')
    if not isinstance(rows, list): raise ValueError('cases must be a list')
    indexed = {}
    for row in rows:
        if not isinstance(row, dict): raise ValueError('case must be an object')
        if 'grade' not in row: continue
        key = row.get('id')
        if not isinstance(key, str) or not key or key in indexed:
            raise ValueError('missing or duplicate graded case ID')
        if not isinstance(row.get('prompt_hash'), str) or not row['prompt_hash']:
            raise ValueError('missing prompt hash')
        if not isinstance(row.get('family'), str) or not isinstance(row.get('grade'), dict):
            raise ValueError('missing family or grade')
        if type(row.get('completed')) is not bool or type(row['grade'].get('passed')) is not bool:
            raise ValueError('completed and grade.passed must be boolean')
        obs = row.get('observed', {})
        if not isinstance(obs, dict): raise ValueError('observed must be an object')
        if row['completed'] and (obs.get('completed') is False or obs.get('incomplete') is True or
                                 obs.get('transport_state', 'ok') != 'ok'):
            raise ValueError('completed conflicts with transport evidence')
        indexed[key] = row
    if not indexed: raise ValueError('no graded tasks')
    return indexed


def regression_upper_bound(k, n, alpha=.05):
    """One-sided exact binomial upper bound, not the Wilson approximation."""
    if k == n: return 1.0
    def cdf(p):
        return sum(math.exp(math.lgamma(n+1)-math.lgamma(i+1)-math.lgamma(n-i+1) +
                            i*math.log(p)+(n-i)*math.log1p(-p)) for i in range(k+1))
    lo, hi = 0.0, 1.0
    for _ in range(55):
        mid = (lo+hi)/2
        if cdf(mid) > alpha: lo = mid
        else: hi = mid
    return hi


def compare_reference(candidate, reference, *, trusted=False, margin=.10, match_target=True, alpha=.05):
    if not isinstance(candidate, dict) or not isinstance(reference, dict):
        return {'status':'invalid_report','error':'report root must be an object','identity':'not_established'}
    if candidate.get('run_id') and candidate['run_id']==reference.get('run_id'):
        return {'status':'invalid_report','error':'candidate cannot be its own reference','identity':'not_established'}
    keys = ('suite_version', 'suite_commitment', 'seed', 'api_style')
    compatible = {k: k in candidate and k in reference and candidate[k] == reference[k] for k in keys}
    # Parameter probes and fingerprint sample counts do not change task calls.
    def task_settings(report):
        settings = report.get('settings')
        if not isinstance(settings, dict): return None
        return {k:v for k,v in settings.items() if k not in ('efforts','fingerprint_samples','fingerprint_temperature')}
    compatible['settings'] = task_settings(candidate) is not None and task_settings(candidate) == task_settings(reference)
    compatible['target_selected'] = bool(candidate.get('target_model') and reference.get('target_model'))
    if match_target: compatible['target_model'] = candidate.get('target_model') == reference.get('target_model')
    # Trust is an explicit operator assertion, never accepted from an imported report.
    result = {"compatible": compatible, "trusted_by_operator": bool(trusted), "margin": margin,
              "status": 'incompatible', "identity": 'not_established', 'alpha':alpha}
    if not all(compatible.values()):
        return result
    try:
        a, b = checked_rows(candidate), checked_rows(reference)
    except ValueError as exc:
        result.update(status='invalid_report', error=str(exc))
        return result
    def public_keys(indexed, report):
        if report.get('export_kind') == 'public_measurements': return indexed
        return {hashlib.sha256(key.encode()).hexdigest():row for key,row in indexed.items()}
    a, b = public_keys(a,candidate), public_keys(b,reference)
    if set(a) != set(b) or any(a[k]['prompt_hash'] != b[k]['prompt_hash'] or a[k]['family'] != b[k]['family'] for k in a):
        result['case_set_match'] = False
        return result
    result['case_set_match'] = True
    clusters, completed_clusters, families = defaultdict(list), defaultdict(list), defaultdict(list)
    for key, row in a.items():
        other = b[key]
        score = int(bool(row.get('completed') and row['grade'].get('passed')))
        ref_score = int(bool(other.get('completed') and other['grade'].get('passed')))
        clusters[row['prompt_hash']].append(ref_score-score)
        families[row['family']].append((score, ref_score))
        if row['completed'] and other['completed']:
            completed_clusters[row['prompt_hash']].append(ref_score-score)
    loss = [statistics.mean(v) for v in clusters.values()]
    n = len(loss)
    rng = random.Random(candidate['seed'])
    boot = sorted(statistics.mean(rng.choices(loss, k=n)) for _ in range(2000))
    mean = statistics.mean(loss)
    # A conservative sufficient condition: even the fraction of tasks regressing
    # (ignoring helpful gains and partial loss sizes) is below the loss margin.
    regressions = sum(x > 0 for x in loss)
    regression_upper = regression_upper_bound(regressions, n, alpha)
    # Bounded differences lie in [-1,1]. Hoeffding gives a conservative lower
    # bound even when the bootstrap has zero variance (e.g. all tasks failed).
    loss_lower = mean - math.sqrt(2*math.log(1/alpha)/n)
    completed_loss = [statistics.mean(v) for v in completed_clusters.values()]
    completed_lower = (statistics.mean(completed_loss) - math.sqrt(2*math.log(1/alpha)/len(completed_loss))) if completed_loss else None
    ref_graded = list(b.values())
    ref_accuracy = sum(bool(r.get('completed') and r['grade'].get('passed')) for r in ref_graded)/len(ref_graded)
    reference_completion = sum(r['completed'] for r in ref_graded)/len(ref_graded)
    tools_ok = not tool_expected(reference.get('target_model'),reference.get('api_style')) or reference.get('tool_summary',{}).get('result_used') is True
    reference_usable = ref_accuracy >= .5 and reference_completion >= .95 and tools_ok
    status = 'insufficient_samples'
    if n >= 30 and reference_usable:
        if loss_lower > margin:
            status = 'below_reference' if len(completed_loss) >= 30 and completed_lower > margin else 'service_degradation'
        elif regression_upper <= margin:
            status = 'within_margin'
        else:
            status = 'inconclusive'
    result.update(status=status, unique_tasks=n, paired_attempts=len(a), mean_loss=mean,
                  bootstrap_95=[boot[50], boot[1949]], regression_fraction_upper_bound=regression_upper,
                  loss_lower_bound=loss_lower, completed_only_loss_lower_bound=completed_lower,
                  confidence=1-alpha, completed_pair_unique_tasks=len(completed_loss),
                  reference_accuracy=ref_accuracy, reference_usable=reference_usable,
                  reference_completion=reference_completion,
                  by_family={k:{'attempts':len(v),'candidate_accuracy':statistics.mean(x[0] for x in v),
                                'reference_accuracy':statistics.mean(x[1] for x in v),
                                'mean_loss':statistics.mean(x[1]-x[0] for x in v)} for k,v in families.items()},
                  capability_calibrated=bool(trusted and reference_usable and n >= 30),
                  minimum_unique_tasks=30,
                  note='Positive loss means candidate worse. Within-margin evidence applies only to this suite and configuration; never proves weights.')
    fp_keys = ('task_effort','max_output_tokens','stream','fingerprint_temperature')
    same_fp = all(k in candidate.get('settings',{}) and k in reference.get('settings',{}) and
                  candidate['settings'][k] == reference['settings'][k] for k in fp_keys)
    result['fingerprint'] = compare_fingerprints(candidate.get('cases', []), reference.get('cases', []), candidate['seed'],alpha) if same_fp else {'status':'incompatible_settings'}
    return result


def quality_profile(cases):
    """Separate availability, strict format and reasoning; expose repeat reliability."""
    graded = [r for r in cases if 'grade' in r]
    groups = defaultdict(list)
    errors = Counter()
    for index, row in enumerate(graded):
        groups[row.get('prompt_hash') or row.get('case_id') or f'unlabelled-{index}'].append(row)
        if not row.get('completed'):
            obs = row.get('observed',{})
            state = obs.get('transport_state')
            errors['truncated_or_unfinished' if obs.get('incomplete') else state if state and state!='ok' else 'no_output'] += 1
    complete = [r for r in graded if r.get('completed')]
    def passed(row): return bool(row.get('completed') and row['grade'].get('passed'))
    repeated = [rs for rs in groups.values() if len(rs)>1]
    return {'attempts':len(graded),'unique_prompts':len(groups),'completed':len(complete),
            'completion_rate':len(complete)/len(graded) if graded else None,
            'strict_accuracy':sum(map(passed,graded))/len(graded) if graded else None,
            'completed_accuracy':sum(map(passed,complete))/len(complete) if complete else None,
            'format_only_failures':sum(bool(r['grade'].get('content_passed')) and not r['grade'].get('passed') for r in complete),
            'failures_by_cause':dict(errors),'repeated_unique_prompts':len(repeated),
            'all_repeats_pass_rate':sum(all(map(passed,rs)) for rs in repeated)/len(repeated) if repeated else None,
            'any_repeat_pass_rate':sum(any(map(passed,rs)) for rs in repeated)/len(repeated) if repeated else None,
            'difficulty':{d:{'attempts':len(rs),'accuracy':sum(map(passed,rs))/len(rs)} for d in sorted({r.get('difficulty','standard') for r in graded})
                          if (rs := [r for r in graded if r.get('difficulty','standard')==d])},
            'note':'Task coverage is not IQ. all/any repeat rates describe sampled reliability, not identity or pass@k estimates.'}
