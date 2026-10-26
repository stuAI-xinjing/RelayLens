"""Optional numeric-response fingerprints; one request is one sampling unit.

Inspired by lm-detector's numeric-preference idea, implemented independently.
No upstream classifier, reference bank, confidence scores or proxy is used.
"""
import hashlib
import math
import random
from collections import Counter

from .grading import strict_json

VERSION = 'numeric-sequence-1'
MINIMUM_PAIRS = 30
PERMUTATIONS = 1999


def prompts(seed, count):
    rng = random.Random(seed ^ 0x4E554D31)
    result = []
    for index in range(count):
        length = rng.randrange(224, 321)
        tag = f'{index:x}-{rng.getrandbits(64):016x}'
        if index % 2:
            text = (f'样本标记 {tag}（不要复述）。凭直觉逐个选择 {length} 个 1 到 355 的整数。'
                    '允许重复，不要使用工具、代码、排序、计数或预设循环。只返回一个 JSON 整数数组，不要解释。')
        else:
            text = (f'Sample label {tag} (do not repeat it). Choose {length} integers from 1 to 355, '
                    'one at a time by intuition. Repetitions are allowed. Do not use tools, code, sorting, '
                    'counting or a preset cycle. Return only a JSON array of integers, without explanation.')
        result.append({'index':index, 'length':length, 'prompt':text,
                       'prompt_hash':hashlib.sha256(text.encode()).hexdigest()})
    return result


def features(text, length):
    """Reject partial/malformed arrays; never mine numbers from prose/errors."""
    try:
        values = strict_json(text)
    except (ValueError, TypeError, RecursionError):
        return None, 'invalid_json'
    if not isinstance(values, list) or len(values) != length:
        return None, 'wrong_length'
    if any(type(x) is not int or not 1 <= x <= 355 for x in values):
        return None, 'invalid_integer'

    def embedding(indices, bins):
        counts = Counter(indices)
        denom = sum(counts.values()) + .5*bins
        return [math.sqrt((counts.get(i, 0)+.5)/denom) for i in range(bins)]

    # Six equal-weight Hellinger blocks, frozen before looking at any endpoint.
    blocks = [embedding([v-1 for v in values],355), embedding([v % 10 for v in values],10)]
    for quarter in range(4):
        segment = values[quarter*length//4:(quarter+1)*length//4]
        blocks.append(embedding([(v-1)*16//355 for v in segment],16))
    return [x/math.sqrt(6) for block in blocks for x in block], None


def paired_test(left, right, seed=0):
    """Multiscale RBF MMD with within-prompt label swaps, not per-number tests.

    Under the null, the two complete responses to each prompt must be
    exchangeable; prompt pairs must be independent. All coordinates move
    together when swapping a label. No endpoint-trained hyperparameters.
    """
    n = len(left)
    if n != len(right) or n < 2:
        raise ValueError('at least two paired vectors required')
    def kernel(a,b):
        distance = sum((x-y)**2 for x,y in zip(a,b))
        return sum(math.exp(-distance/scale) for scale in (.05,.2,1.0))/3
    gram = [(i,j,kernel(left[i],left[j])+kernel(right[i],right[j])-
             kernel(left[i],right[j])-kernel(right[i],left[j])) for i in range(n) for j in range(i)]
    observed = sum(value for _,_,value in gram)
    rng = random.Random(seed)
    greater = 1
    for _ in range(PERMUTATIONS):
        signs = [rng.choice((-1,1)) for _ in range(n)]
        statistic = sum(signs[i]*signs[j]*value for i,j,value in gram)
        greater += statistic >= observed-1e-12
    return {'mmd_statistic':2*observed/(n*(n-1)), 'permutation_p':greater/(PERMUTATIONS+1),
            'permutations':PERMUTATIONS, 'minimum_resolvable_p':1/(PERMUTATIONS+1)}


def _measure(report):
    config = report.get('settings',{})
    if not isinstance(config,dict) or not isinstance(report.get('cases'),list):
        raise ValueError('settings must be an object and cases must be a list')
    count = config.get('numeric_samples',0)
    if type(count) is not int or count < 0 or type(report.get('seed')) is not int:
        raise ValueError('invalid numeric sample count or seed')
    if config.get('numeric_version') != VERSION:
        raise ValueError('numeric probe version missing or unsupported')
    expected = prompts(report['seed'],count)
    indexed = {}
    for row in report.get('cases',[]):
        if not isinstance(row,dict): raise ValueError('case must be an object')
        if row.get('family') != 'numeric_fingerprint': continue
        index = row.get('numeric_index')
        if type(index) is not int or not 0 <= index < count or index in indexed:
            raise ValueError('duplicate or invalid numeric index')
        if row.get('prompt_hash') != expected[index]['prompt_hash']:
            raise ValueError('numeric prompt does not match the frozen generator')
        if type(row.get('completed')) is not bool or not isinstance(row.get('observed'),dict):
            raise ValueError('invalid numeric observation')
        indexed[index] = row
    if len(indexed) != count:
        raise ValueError('missing numeric attempts; do not discard failures')
    measured, errors = {}, Counter()
    for index,row in indexed.items():
        obs = row['observed']
        if not row['completed'] or obs.get('incomplete') or obs.get('completed') is False or obs.get('transport_state','ok') != 'ok':
            errors['unfinished_request'] += 1
            continue
        vector,error = features(obs.get('text'),expected[index]['length'])
        if error: errors[error] += 1
        else: measured[index] = vector
    return measured, dict(errors), count


def describe(report):
    config = report.get('settings',{})
    if not isinstance(config,dict): return {'status':'invalid_report','error':'invalid settings'}
    if not config.get('numeric_samples'):
        return {'status':'not_requested'}
    if report.get('export_kind') == 'public_measurements':
        return {'status':'answer_text_unavailable'}
    try:
        vectors,errors,count = _measure(report)
    except (ValueError,TypeError,KeyError) as exc:
        return {'status':'invalid_report','error':str(exc)}
    return {'status':'collected','planned_requests':count,'valid_requests':len(vectors),
            'invalid_by_reason':errors,'minimum_paired_requests':MINIMUM_PAIRS,
            'note':'Numeric preferences are behavior, not IQ or proof of model identity.'}


def compare_numeric(candidate,reference,*,trusted=False,alpha=.05):
    result = {'status':'not_requested','trusted_by_operator':bool(trusted),'alpha':alpha,
              'identity':'not_established','minimum_pairs':MINIMUM_PAIRS,
              'note':'A shift can reflect prompts, sampling, backend changes or substitution. No detected shift is not equivalence. No mixing fraction is estimated.'}
    a,b = candidate.get('settings',{}),reference.get('settings',{})
    if not isinstance(a,dict) or not isinstance(b,dict):
        return dict(result,status='invalid_report',error='invalid settings')
    if not a.get('numeric_samples') or not b.get('numeric_samples'): return result
    if candidate.get('export_kind')=='public_measurements' or reference.get('export_kind')=='public_measurements':
        return dict(result,status='answer_text_unavailable')
    if candidate.get('run_id') and candidate['run_id']==reference.get('run_id'):
        return dict(result,status='invalid_report',error='candidate cannot be its own reference')
    keys = ('numeric_samples','numeric_version','task_effort','max_output_tokens','stream','fingerprint_temperature','chat_token_field')
    if (any(a.get(k)!=b.get(k) for k in keys) or candidate.get('seed')!=reference.get('seed') or
            candidate.get('api_style')!=reference.get('api_style')):
        return dict(result,status='incompatible_settings')
    required = ('task_effort','max_output_tokens','stream','fingerprint_temperature')
    if any(k not in a or k not in b for k in required):
        return dict(result,status='incompatible_settings')
    try:
        left,le,count = _measure(candidate)
        right,re,_ = _measure(reference)
    except (ValueError,TypeError,KeyError) as exc:
        return dict(result,status='invalid_report',error=str(exc))
    pairs = sorted(left.keys() & right.keys())
    result.update(paired_requests=len(pairs),planned_requests=count,candidate_valid=len(left),reference_valid=len(right),
                  candidate_invalid=le,reference_invalid=re)
    if min(len(left),len(right))/count < .95:
        return dict(result,status='invalid_or_incomplete_samples')
    if len(pairs) < MINIMUM_PAIRS:
        return dict(result,status='insufficient_samples')
    result.update(paired_test([left[i] for i in pairs],[right[i] for i in pairs],candidate['seed']))
    result['status'] = 'distribution_shift' if result['permutation_p'] < alpha else 'no_shift_detected'
    result['resolution_sufficient'] = result['minimum_resolvable_p'] < alpha
    result['assumptions'] = 'Independent prompt pairs; honest reference and candidate responses exchangeable under the null; missingness not response-dependent. Repeated peeking is not corrected.'
    return result
