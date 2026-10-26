"""Multi-signal evidence with explicit reference and sample-size boundaries."""
import math
import random
import statistics
from collections import Counter, defaultdict

from .stats import wilson


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


def compare_fingerprints(candidate, reference, seed=0):
    """Descriptive JSD plus permutation tests; no borrowed model-ID thresholds."""
    left, right = defaultdict(list), defaultdict(list)
    hashes = defaultdict(set)
    for rows, dest in ((candidate, left), (reference, right)):
        for row in rows:
            if row.get('family') == 'fingerprint' and row.get('completed'):
                dest[row['case_id']].append(row['observed'].get('text', '').strip().casefold())
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
    drift = any(r['permutation_p'] < .05/max(len(usable), 1) for r in usable)
    return {"status": 'distribution_shift' if drift else 'no_shift_detected' if usable else 'insufficient_samples',
            "cells": results, "minimum_per_cell": 20, "multiple_test_correction": 'Bonferroni',
            "note": 'Same prompts and sampling settings required; this is behavior evidence, not model identity probability.'}


def compare_reference(candidate, reference, *, trusted=False, margin=.10):
    keys = ('suite_version', 'suite_commitment', 'seed', 'api_style', 'target_model', 'settings')
    compatible = {k: k in candidate and k in reference and candidate[k] == reference[k] for k in keys}
    compatible['target_selected'] = bool(candidate.get('target_model'))
    # Trust is an explicit operator assertion, never accepted from an imported report.
    result = {"compatible": compatible, "trusted_by_operator": bool(trusted), "margin": margin,
              "status": 'incompatible', "identity": 'not_established'}
    if not all(compatible.values()):
        return result
    a = {r['id']: r for r in candidate.get('cases', []) if 'grade' in r}
    b = {r['id']: r for r in reference.get('cases', []) if 'grade' in r}
    if not a or set(a) != set(b) or any(not a[k].get('prompt_hash') or a[k]['prompt_hash'] != b[k].get('prompt_hash') for k in a):
        result['case_set_match'] = False
        return result
    result['case_set_match'] = True
    clusters = defaultdict(list)
    for key, row in a.items():
        other = b[key]
        score = int(bool(row.get('completed') and row['grade'].get('passed')))
        ref_score = int(bool(other.get('completed') and other['grade'].get('passed')))
        clusters[row['prompt_hash']].append(ref_score-score)
    loss = [statistics.mean(v) for v in clusters.values()]
    n = len(loss)
    rng = random.Random(candidate['seed'])
    boot = sorted(statistics.mean(rng.choices(loss, k=n)) for _ in range(2000))
    mean = statistics.mean(loss)
    # A conservative sufficient condition: even the fraction of tasks regressing
    # (ignoring helpful gains and partial loss sizes) is below the loss margin.
    regressions = sum(x > 0 for x in loss)
    regression_upper = wilson(regressions, n, z=1.6448536269514722)[1]
    ref_graded = list(b.values())
    ref_accuracy = sum(bool(r.get('completed') and r['grade'].get('passed')) for r in ref_graded)/len(ref_graded)
    reference_usable = ref_accuracy >= .5 and bool(reference.get('tool_summary', {}).get('result_used'))
    status = 'insufficient_samples'
    if n >= 30 and reference_usable:
        status = 'below_reference' if boot[50] > margin else 'within_margin' if regression_upper <= margin else 'inconclusive'
    result.update(status=status, unique_tasks=n, paired_attempts=len(a), mean_loss=mean,
                  bootstrap_95=[boot[50], boot[1949]], regression_fraction_upper_95=regression_upper,
                  reference_accuracy=ref_accuracy, reference_usable=reference_usable,
                  capability_calibrated=bool(trusted and reference_usable and n >= 30),
                  minimum_unique_tasks=30,
                  note='Positive loss means candidate worse. Within-margin evidence applies only to this suite and configuration; never proves weights.')
    result['fingerprint'] = compare_fingerprints(candidate.get('cases', []), reference.get('cases', []), candidate['seed'])
    return result
