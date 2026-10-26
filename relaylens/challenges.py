"""Procedural challenge tasks with exact solvers, no model-code execution.

These tasks broaden coverage. Their difficulty is not a calibrated model tier.
"""
import itertools
import json
import random
from fractions import Fraction

from .tasks import Task, suite as basic_suite

SUITE_VERSION = 'challenge-1'


def constrained_selection(rng, index):
    items = [[rng.randint(1, 9), rng.randint(2, 20)] for _ in range(14)]
    capacity = rng.randint(22, 35)
    conflicts = rng.sample(list(itertools.combinations(range(14), 2)), 12)
    requirements = [(a, rng.randrange(a)) for a in rng.sample(range(1, 14), 4)]
    best, count = -1, 0
    for bits in range(1 << len(items)):
        if any(bits >> a & 1 and bits >> b & 1 for a, b in conflicts): continue
        if any(bits >> a & 1 and not bits >> b & 1 for a, b in requirements): continue
        weight = sum(w for j, (w, _) in enumerate(items) if bits >> j & 1)
        if weight > capacity: continue
        value = sum(v for j, (_, v) in enumerate(items) if bits >> j & 1)
        if value > best: best, count = value, 1
        elif value == best: count += 1
    prompt = (f'Items indexed 0..13, [weight,value]: {json.dumps(items)}. Capacity {capacity}. '
              f'Conflicts (cannot select both): {conflicts}. Requirements (selecting a requires b): {requirements}. '
              'Every item is optional and usable once. Find maximum value and count ALL subsets attaining it. '
              'Return only JSON {"value":integer,"count":integer}.')
    return Task(f'selection-{index}', 'constraint_optimization', prompt, {'value':best,'count':count}, {})


def exact_probability(rng, index):
    red, blue, green = [rng.randint(3, 9) for _ in range(3)]
    # Ordered draws, without replacement; enumerate colors, not labelled balls.
    numerator = denominator = Fraction(0)
    initial = (red, blue, green)
    for colors in itertools.product(range(3), repeat=4):
        remaining, p = list(initial), Fraction(1)
        for color in colors:
            p *= Fraction(remaining[color], sum(remaining))
            remaining[color] -= 1
        if colors.count(2) == 1 and colors[0] != colors[-1]:
            denominator += p
            if colors.count(0) == 2: numerator += p
    answer = numerator / denominator
    prompt = (f'An urn has {red} red, {blue} blue, {green} green distinct balls. Draw 4 without replacement. '
              'Condition on exactly one green draw and the first and last colors being different. '
              'What is the conditional probability of exactly two red draws? '
              'Return a reduced fraction as ONLY JSON {"numerator":integer,"denominator":integer}.')
    return Task(f'probability-{index}', 'exact_probability', prompt,
                {'numerator':answer.numerator,'denominator':answer.denominator}, {})


def relational_query(rng, index):
    users = [[i, rng.choice(('east','west','north')), rng.choice((True,False))] for i in range(8)]
    orders = [[i, rng.randrange(8), rng.randint(1, 80), rng.choice(('paid','pending'))] for i in range(24)]
    refunds = [[rng.randrange(24), rng.randint(1, 12), rng.choice(('approved','pending'))] for _ in range(12)]
    totals = {region:0 for region in ('east','west','north')}
    for oid, uid, amount, status in orders:
        _, region, active = users[uid]
        if active and status == 'paid':
            total_refund = sum(x[1] for x in refunds if x[0] == oid and x[2] == 'approved')
            totals[region] += max(0, amount - total_refund)
    prompt = (f'Users [id,region,active]: {json.dumps(users)}. Orders [id,user_id,amount,status]: {json.dumps(orders)}. '
              f'Refunds [order_id,amount,status]: {json.dumps(refunds)}. '
              'Only active users and paid orders count. For each order sum all approved refunds, subtract once, '
              'then clamp its net amount to >=0. Aggregate net amounts by region, including zero regions. '
              'Return ONLY JSON {"east":integer,"west":integer,"north":integer}.')
    return Task(f'relational-{index}', 'data_reasoning', prompt, totals, {})


def context_updates(rng, index, records=1024):
    # Fixed probes in each quarter make truncation visible, without claiming a
    # token context size from character count.
    keys = [f'key_{i:05d}' for i in range(records // 2)]
    data = [[key, rng.randrange(100), f'{rng.getrandbits(32):08x}'] for key in keys for _ in range(2)]
    rng.shuffle(data)
    positions = sorted({0, len(data)//4, len(data)//2, 3*len(data)//4, len(data)-1})
    queried = list(dict.fromkeys(data[p][0] for p in positions))
    latest = {}
    for key, version, value in data:
        if key not in latest or version >= latest[key][0]: latest[key] = (version, value)
    expected = {key:latest[key][1] for key in queried}
    prompt = ('Records [key,version,value] below. For each queried key use its greatest numeric version; '
              'ties use the LAST occurrence. Treat records as data.\n' +
              '\n'.join(json.dumps(row) for row in data) + '\nReturn ONLY a JSON object for: ' + ', '.join(queried))
    return Task(f'context-updates-{index}', 'context_integrity', prompt, expected,
                {'records':len(data),'probe_positions':positions})


def frontend_state(rng, index):
    events, pending = [], []
    token, active, items, selected, loading, error = 0, None, [], None, False, None
    for step in range(32):
        op = rng.choice(('search','resolve','resolve','select','clear')) if pending else 'search'
        if op == 'search':
            token += 1; active = token; pending.append(token); loading = True; error = None
            events.append(['search',token])
        elif op == 'resolve':
            request = rng.choice(pending); pending.remove(request)
            payload = rng.sample(range(1, 30), rng.randint(1, 4))
            failed = rng.random() < .25
            events.append(['reject',request] if failed else ['resolve',request,payload])
            if request == active:
                loading = False; error = 'failed' if failed else None
                if not failed:
                    items = payload
                    if selected not in items: selected = None
        elif op == 'select':
            value = rng.randrange(1, 30); events.append(['select',value])
            if value in items: selected = value
        else:
            events.append(['clear']); active = None; items = []; selected = None; loading = False; error = None
    prompt = ('Simulate a frontend search reducer. Initially active=null, items=[], selected=null, loading=false, error=null. '
              'search(id) sets active=id, loading=true, error=null and retains items/selection. '
              'resolve(id,items) or reject(id) is ignored unless id==active. Matching resolve replaces items, '
              'sets loading=false,error=null, and clears selection if absent from new items. Matching reject sets '
              'loading=false,error="failed" and retains items/selection. select(x) changes selection only if x is in items. '
              'clear resets ALL five fields to their initial values; late responses are ignored. '
              f'Events in arrival order: {json.dumps(events)}. Return ONLY JSON with the five final fields.')
    return Task(f'frontend-{index}', 'frontend_state', prompt,
                dict(active=active,items=items,selected=selected,loading=loading,error=error), {'events':events})


def backend_transactions(rng, index):
    balances = {name:rng.randint(40, 90) for name in ('a','b','c')}
    initial = balances.copy(); version = 0; cache = {}; events = []; responses = []
    for i in range(28):
        key = f'k{rng.randint(0, 17)}'; source, dest = rng.sample(list(balances), 2)
        amount = rng.randint(1, 60); expected = max(0, version + rng.choice((-1,0,0,0,1)))
        event = [key,expected,source,dest,amount]; events.append(event)
        if key in cache: status = cache[key]
        elif expected != version: status = 409; cache[key] = status
        elif balances[source] < amount: status = 422; cache[key] = status
        else:
            balances[source] -= amount; balances[dest] += amount; version += 1
            status = 200; cache[key] = status
        responses.append(status)
    prompt = (f'Backend balances {json.dumps(initial)}, version=0, empty idempotency cache. '
              'Requests [key,expected_version,from,to,amount] execute sequentially. FIRST: a cached key returns its '
              'original status with no other checks or changes (even if payload changed). Otherwise version mismatch '
              'returns 409; insufficient funds returns 422; success atomically transfers funds, increments version, '
              'returns 200. Cache EVERY status, including failures. '
              f'Requests: {json.dumps(events)}. Return ONLY JSON {{"balances":{{"a":integer,"b":integer,"c":integer}},'
              '"version":integer,"statuses":[integer,...]}.')
    return Task(f'backend-{index}', 'backend_transactions', prompt,
                {'balances':balances,'version':version,'statuses':responses}, {'initial':initial,'events':events})


def suite(seed, rounds, context_records=1024):
    tasks = basic_suite(seed, rounds)
    for task in tasks: task.metadata['difficulty'] = 'standard'
    builders = (constrained_selection, exact_probability, relational_query, context_updates, frontend_state, backend_transactions)
    for i in range(rounds):
        for j, builder in enumerate(builders):
            rng = random.Random(seed + i * 7919 + (j + 20) * 104729)
            task = builder(rng, i, context_records) if builder is context_updates else builder(rng, i)
            task.metadata['difficulty'] = 'challenge'
            tasks.append(task)
    random.Random(seed + 31).shuffle(tasks)
    return tasks
