"""Offline reference-panel comparisons. No network or keys are needed."""
import hashlib
import json
from pathlib import Path

from .evidence import compare_reference
from .grading import strict_json
from .model_targets import profile


def read_report(path):
    report = strict_json(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(report, dict): raise ValueError('report root must be an object')
    return report


def compare_panel(candidate, references, *, trusted=False, margin=.10):
    """Return all compatible anchors, never force a nearest-model identity."""
    rows, seen = [], set()
    unique = []
    for reference in references:
        commitment = hashlib.sha256(json.dumps(reference,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if commitment not in seen:
            seen.add(commitment); unique.append((reference, commitment))
    # Correct for every attempted reference, including later-incompatible ones.
    alpha = .05/max(1,len(unique))
    for reference, commitment in unique:
        target = reference.get('target_model')
        if not isinstance(target,str): target = None
        if not profile(target):
            rows.append({'target_model':target,'status':'unsupported_target','reference_sha256':commitment})
            continue
        result = compare_reference(candidate,reference,trusted=trusted,margin=margin,match_target=False,alpha=alpha)
        rows.append(dict(result,target_model=target,reference_sha256=commitment,
                         reference_date=reference.get('started_at_utc')))
    models = {r.get('target_model') for r in rows}
    matches = sorted(model for model in models if model and all(r.get('capability_calibrated') and r['status']=='within_margin' for r in rows if r.get('target_model')==model))
    below = sorted({r['target_model'] for r in rows if r.get('capability_calibrated') and r['status']=='below_reference'})
    status = 'overlapping_references' if len(matches)>1 else 'compatible_reference_found' if matches else 'below_some_references' if below else 'insufficient_evidence'
    return {'status':status,'within_margin_models':matches,'below_reference_models':below,'comparisons':rows,
            'familywise_alpha':.05,'per_comparison_alpha':alpha,'identity':'not_established',
            'note':'These are capability anchors on identical tasks/settings, not a classifier. Multiple matches mean the suite cannot separate them. A higher score alone does not establish a stronger underlying model.'}


def apply_comparisons(report, paths=(), directory=None, *, trusted=False, margin=.10):
    references, errors, seen = [], [], set()
    source_paths = [Path(p) for p in paths]
    if directory:
        folder = Path(directory)
        if not folder.is_dir(): errors.append({'status':'error','error':'reference directory not found'})
        else: source_paths += sorted(folder.glob('*.json'))
    for path in source_paths:
        if path.resolve() in seen: continue
        seen.add(path.resolve())
        try: references.append(read_report(path))
        except (ValueError,TypeError,OSError,RecursionError) as exc:
            errors.append({'status':'error','error':f'{type(exc).__name__}: {exc}'})
    if references:
        panel = compare_panel(report,references,trusted=trusted,margin=margin)
        panel['load_errors'] = errors
        report['reference_panel'] = panel
        same = [r for r in panel['comparisons'] if r.get('target_model')==report.get('target_model')]
        if len(same)==1:
            report['reference_comparison'] = same[0]
        elif len(same)>1:
            # Conflicting runs for one target must not be silently cherry-picked.
            usable = [r for r in same if r.get('capability_calibrated')]
            statuses = {r['status'] for r in usable}
            report['reference_comparison'] = (usable[0] if len(usable)==len(same) and len(statuses)==1 else
                                             {'status':'conflicting_or_incomplete_references','trusted_by_operator':trusted})
    elif errors:
        report['reference_comparison'] = {'status':'error','errors':errors}
    return report
