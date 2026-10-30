"""Optional direct-provider input counter. No generation or model self-report."""
import copy
import json
import os
import urllib.request


def official_input_count(payload, api, model, key_env, opener, timeout, fallback):
    result = copy.deepcopy(fallback)
    key = os.environ.get(key_env, '')
    if not key:
        result['official_counter_status'] = 'key_environment_missing'
        return result
    if api == 'responses' and model.startswith('gpt-'):
        endpoint = 'https://api.openai.com/v1/responses/input_tokens'
        body = {k:v for k,v in payload.items() if k in ('input','instructions','tools','text','reasoning','previous_response_id')}
        headers = {'Authorization':'Bearer '+key}
    elif api == 'messages' and model.startswith('claude-'):
        endpoint = 'https://api.anthropic.com/v1/messages/count_tokens'
        body = {k:v for k,v in payload.items() if k in ('messages','system','tools','tool_choice','thinking')}
        headers = {'x-api-key':key,'anthropic-version':'2023-06-01'}
    else:
        result['official_counter_status'] = 'unsupported_protocol'
        return result
    body['model'] = model
    headers.update({'Content-Type':'application/json','User-Agent':'RelayLens/0.9.0'})
    req = urllib.request.Request(endpoint,data=json.dumps(body).encode(),headers=headers,method='POST')
    try:
        with opener.open(req,timeout=timeout) as response:
            data = json.load(response)
        count = data.get('input_tokens')
        if type(count) is not int or count < 0: raise ValueError('invalid counter')
        result.update(input_tokens=count, method='official_input_count', exact=api=='responses',
                      scope='submitted_payload', model=model, official_counter_status='counted',
                      limitations=['官方计数针对所提交内容；无法看见中转追加的提示词。Claude 计数属于官方估算，实际消息可能有少量差异。'])
    except Exception as exc:
        # Never persist error bodies/URLs which can contain a credential echo.
        result['official_counter_status'] = 'unavailable_' + type(exc).__name__
    return result


def control_prompts(seed, count):
    """Fixed-purpose, differing-length probes; not additional intelligence tasks."""
    import random
    rng = random.Random(seed)
    for i in range(count):
        size = (256,1024,4096)[i % 3]
        words = [''.join(rng.choices('abcdefghjkmnpqrstuvwxyz',k=8)) for _ in range(size//8)]
        yield 'Read this inert list. Reply with ONLY OK.\n' + ' '.join(words)
