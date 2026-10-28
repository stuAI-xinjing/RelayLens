"""Deterministic content diagnostics; partial credit never turns a task into a pass.

Strict grades are retained. A single complete JSON answer with surrounding prose
can be content-correct, but still fails the original format contract.
"""
import copy
import hashlib
import json

from .grading import exact, strict_json
from .tasks import Task, grade_expression

POLICY = 'content-exact-1'


def structured_answer(text):
    try:
        return strict_json(text)
    except (ValueError, TypeError):
        pass
    # Scan top-level balanced containers, not nested snippets or the answer key.
    # Multiple answers, mismatched brackets and unfinished JSON are ambiguous.
    spans, stack, quoted, escaped, start = [], [], False, False, None
    for i, char in enumerate(text):
        if not stack:
            if char in '{[':
                stack.append(char); start = i; quoted = False; escaped = False
            elif char in '}]':
                raise ValueError('unmatched JSON delimiter')
            continue
        if quoted:
            if escaped: escaped = False
            elif char == '\\': escaped = True
            elif char == '"': quoted = False
            continue
        if char == '"': quoted = True
        elif char in '{[': stack.append(char)
        elif char in '}]':
            if stack.pop() != ('{' if char == '}' else '['):
                raise ValueError('mismatched JSON delimiter')
            if not stack: spans.append(text[start:i+1])
    if stack or len(spans) != 1:
        raise ValueError('one unambiguous complete JSON answer required')
    return strict_json(spans[0])


def component_score(actual, expected):
    """Equal root-field weights, recursively; wrong types/shapes receive zero."""
    if type(actual) is not type(expected): return 0.0
    if isinstance(expected, dict):
        if actual.keys() != expected.keys(): return 0.0
        values = [component_score(actual[k], v) for k, v in expected.items()]
    elif isinstance(expected, list):
        if len(actual) != len(expected): return 0.0
        values = [component_score(a, b) for a, b in zip(actual, expected)]
    else:
        return float(exact(actual, expected))
    return sum(values)/len(values) if values else 1.0


def review_grade(task, text, grade):
    # Custom graders retain their own semantics. Never override a subclass.
    if type(task) is not Task: return grade
    result = dict(grade)
    correct = bool(grade.get('passed'))
    score = float(correct)
    reason = 'exact_content'
    try:
        if task.family == 'instruction':
            correct = text.strip() == task.expected
            score = float(correct)
        else:
            parsed = structured_answer(text)
            if task.family == 'code_repair':
                checks = grade_expression(parsed, task.metadata)
                correct = checks['passed']
                score = checks.get('cases_passed', 0)/max(1, checks.get('cases_total', 1))
            else:
                correct = exact(parsed, task.expected)
                # Ordering and a probability are indivisible answers. Other
                # structured tasks expose component accuracy only for diagnosis.
                score = float(correct) if task.family in ('logic','exact_probability') else component_score(parsed, task.expected)
    except (ValueError, TypeError, KeyError, RecursionError):
        correct = False; score = 0.0; reason = 'no_unambiguous_structured_answer'
    result.update(content_passed=bool(correct), content_policy=POLICY,
                  component_score=score, content_reason=reason)
    return result


def content_passed(row):
    grade = row['grade']
    return bool(row.get('completed') and
                (grade.get('content_passed') if grade.get('content_policy') == POLICY else grade.get('passed')))


def review_report(report):
    """Offline, all-or-nothing replay. Never load code named by an imported file."""
    from .suite_loader import load_suite
    from .evidence import checked_rows
    checked_rows(report)
    if report.get('suite_source') != 'builtin' or report.get('export_kind') == 'public_measurements':
        raise ValueError('offline review requires a local built-in report with original answers')
    settings = report['settings']
    factory, version, _, _ = load_suite(pack=settings['pack'], context_records=settings.get('context_records') or 1024)
    if version != report.get('suite_version'):
        raise ValueError('suite version changed; cannot reconstruct this report')
    tasks = {task.id:task for task in factory(report['seed'], settings['task_rounds'])}
    result = copy.deepcopy(report)
    for row in result['cases']:
        if 'grade' not in row: continue
        task = tasks.get(row.get('case_id'))
        if task is None or task.prompt_hash != row.get('prompt_hash'):
            raise ValueError('prompt hash mismatch; report was not reviewed')
        text = row.get('observed', {}).get('text')
        if row.get('completed') and not isinstance(text, str):
            raise ValueError('original answer unavailable')
        text = text or ''
        if row.get('answer_sha256') and hashlib.sha256(text.encode()).hexdigest() != row['answer_sha256']:
            raise ValueError('answer hash mismatch')
        row['grade'] = review_grade(task, text, row['grade'])
    result['content_review'] = {'policy':POLICY, 'network_calls':0,
        'original_report_sha256':hashlib.sha256(json.dumps(report,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        'strict_grades_preserved':True}
    return result
