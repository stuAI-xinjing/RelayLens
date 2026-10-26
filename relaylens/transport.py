"""Standard-library OpenAI-compatible Responses and Chat adapters."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request


def normalize_base(raw):
    raw = raw.strip().rstrip("/")
    if "://" not in raw: raw = "https://" + raw
    parts = urllib.parse.urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Use an HTTP(S) API base URL")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Keep credentials and query strings out of the base URL")
    path = parts.path.rstrip("/")
    for suffix in ("/chat/completions", "/responses", "/messages", "/models", "/docs", "/help"):
        if path.endswith(suffix): path = path[:-len(suffix)]; break
    # Preserve custom versioned API paths; only root URLs get /v1.
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path or "/v1", "", ""))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # Never forward Authorization on an automatic redirect.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def classify(status, error=""):
    if status is None: return "network_error"
    if status in (401,403): return "auth_or_access_error"
    if status == 429: return "rate_or_quota_error"
    if status >= 500: return "upstream_error"
    if not 200 <= status < 300: return "request_rejected"
    return "ok"


class Client:
    def __init__(self, base, key, api="responses", route="env", proxy="", timeout=60, max_tokens=4096, effort="", chat_token_field='max_completion_tokens'):
        self.base = normalize_base(base)
        self.key, self.api = key, api
        proxies = {"http": proxy,"https": proxy} if proxy else ({} if route == "direct" else None)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxies), NoRedirect())
        self.timeout, self.max_tokens, self.effort = timeout, max_tokens, effort
        self.chat_token_field = chat_token_field

    def request(self, path, payload=None):
        url = self.base + path
        headers = {"Content-Type":"application/json", "User-Agent":"RelayLens/0.5"}
        if self.api == "messages":
            headers.update({"x-api-key":self.key,"anthropic-version":"2023-06-01"})
        else:
            headers["Authorization"] = "Bearer " + self.key
        body = None if payload is None else json.dumps(payload,ensure_ascii=False).encode()
        req = urllib.request.Request(url,data=body,headers=headers,method="GET" if body is None else "POST")
        start = time.perf_counter()
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                status = resp.status
                first_byte = None
                if payload and payload.get("stream"):
                    data, events, first_byte = self.read_stream(resp, start)
                else:
                    raw = resp.read()
                    data = json.loads(raw.decode("utf-8"))
                    events = []
            return {"http_status":status,"transport_state":"ok","latency_ms":round((time.perf_counter()-start)*1000,1),
                    "first_token_ms":first_byte,"stream_events":events,"data":data}
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8",errors="replace")[:2000]
            try: message = json.loads(message).get("error", message)
            except (ValueError, AttributeError): pass
            return {"http_status":exc.code,"transport_state":classify(exc.code),"error":message,
                    "latency_ms":round((time.perf_counter()-start)*1000,1),"data":{}}
        except (ValueError, UnicodeError) as exc:
            return {"http_status":locals().get("status"),"transport_state":"malformed_response",
                    "error":str(exc),"latency_ms":round((time.perf_counter()-start)*1000,1),"data":{}}
        except Exception as exc:
            return {"http_status":None,"transport_state":"network_error","error":f"{type(exc).__name__}: {exc}",
                    "latency_ms":round((time.perf_counter()-start)*1000,1),"data":{}}

    def read_stream(self, resp, start):
        final = None; chunks = []; event_types = []; first = None; done = False; model = None; usage = None; finish_reason = None
        event_data = []
        def consume(lines):
            nonlocal final,first,done,model,usage,finish_reason
            if not lines: return
            raw = "\n".join(lines)
            if raw == "[DONE]": done = True; return
            obj = json.loads(raw)
            typ = obj.get("type", "chat.chunk")
            event_types.append(typ)
            if self.api == "messages":
                if typ == 'message_start':
                    final = obj.get('message', {})
                    final['content'] = []
                elif typ == 'content_block_start':
                    final['content'].append(obj['content_block'])
                elif typ == 'content_block_delta':
                    block = final['content'][obj['index']]
                    delta = obj.get('delta', {})
                    if delta.get('type') == 'text_delta':
                        if first is None: first = round((time.perf_counter()-start)*1000,1)
                        block['text'] = block.get('text','') + delta.get('text','')
                    elif delta.get('type') == 'input_json_delta':
                        block['_json'] = block.get('_json','') + delta.get('partial_json','')
                    elif delta.get('type') == 'thinking_delta':
                        block['thinking'] = block.get('thinking','') + delta.get('thinking','')
                    elif delta.get('type') == 'signature_delta':
                        block['signature'] = block.get('signature','') + delta.get('signature','')
                elif typ == 'message_delta':
                    final.update(obj.get('delta',{}))
                    final.setdefault('usage',{}).update(obj.get('usage',{}))
                elif typ == 'message_stop':
                    done = True
                elif typ == 'error':
                    raise ValueError('stream error: ' + str(obj.get('error')))
                return
            if typ in ("response.failed","error"):
                raise ValueError("stream error: " + str(obj.get("error") or (obj.get("response") or {}).get("error")))
            if typ in ("response.completed","response.incomplete"):
                final = obj.get("response"); done = True
            if typ == "response.output_text.delta":
                if first is None: first = round((time.perf_counter()-start)*1000,1)
                chunks.append(obj.get("delta", ""))
            if self.api == "chat":
                model = obj.get("model", model); usage = obj.get("usage") or usage
                for choice in obj.get("choices", []):
                    finish_reason = choice.get('finish_reason') or finish_reason
                    delta = choice.get("delta",{}).get("content")
                    if delta:
                        if first is None: first = round((time.perf_counter()-start)*1000,1)
                        chunks.append(delta)
        for raw_line in resp:
            line = raw_line.decode("utf-8").rstrip("\r\n")
            if not line:
                consume(event_data); event_data=[]
            elif line.startswith("data:"):
                event_data.append(line[5:].lstrip())
        consume(event_data)
        if not done: raise ValueError("SSE ended before a completion marker")
        if self.api == 'chat' and finish_reason is None:
            raise ValueError('Chat stream ended without finish_reason')
        if self.api in ("responses", "messages"):
            if not isinstance(final, dict): raise ValueError("Missing final Responses object")
            if self.api == 'messages':
                for block in final.get('content',[]):
                    if '_json' in block: block['input'] = json.loads(block.pop('_json'))
            return final,event_types,first
        return {"model":model,"usage":usage,"choices":[{"message":{"content":"".join(chunks)},'finish_reason':finish_reason}]},event_types,first

    def call(self, model, prompt=None, *, context=None, tools=None, effort=None, stream=False, temperature=None):
        effort = self.effort if effort is None else effort
        if self.api == "responses":
            payload = {"model":model,"input":context if context is not None else prompt,
                       "store":False,"max_output_tokens":self.max_tokens}
            if effort and effort != 'omit': payload["reasoning"]={"effort":effort}
            if tools: payload["tools"]=tools
            path = "/responses"
        elif self.api == 'messages':
            payload = {'model':model, 'messages':context if context is not None else [{'role':'user','content':prompt}],
                       'max_tokens':self.max_tokens}
            if effort and effort != 'omit':
                if effort == 'none':
                    payload['thinking'] = {'type':'disabled'}
                else:
                    payload['thinking'] = {'type':'adaptive'}
                    payload['output_config'] = {'effort':effort}
            if tools:
                payload['tools'] = [{'name':t['name'],'description':t.get('description',''),
                                     'input_schema':t['parameters']} for t in tools]
            path = '/messages'
        else:
            payload = {"model":model,"messages":context if context is not None else [{"role":"user","content":prompt}],
                       self.chat_token_field:self.max_tokens}
            if effort and effort != 'omit': payload["reasoning_effort"]=effort
            if tools: payload["tools"]=[{"type":"function","function":{k:v for k,v in t.items() if k != "type"}} for t in tools]
            path = "/chat/completions"
        if stream: payload["stream"]=True
        if temperature is not None: payload['temperature'] = temperature
        result = self.request(path, payload)
        result["payload_hash"] = __import__("hashlib").sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        return result


def extract(result, api):
    try:
        return _extract(result,api)
    except (TypeError,ValueError,KeyError,AttributeError,IndexError) as exc:
        row = {k:result.get(k) for k in ('http_status','latency_ms','first_token_ms','payload_hash')}
        row.update(transport_state='malformed_response',completed=False,incomplete=False,text='',
                   error='Response shape invalid: ' + type(exc).__name__)
        return row, [], None


def _extract(result, api):
    data = result.get("data")
    if not isinstance(data, dict): data = {}
    usage = data.get("usage")
    text = ""; calls = []; context_item = None
    if api == "responses":
        output = data.get("output") or []
        text = "".join(part.get("text","") for item in output if isinstance(item,dict)
                       for part in item.get("content",[]) if isinstance(part,dict) and part.get("type") == "output_text")
        if not text and isinstance(data.get("output_text"),str): text = data["output_text"]
        calls = [item for item in output if isinstance(item,dict) and item.get("type") == "function_call"]
        incomplete = data.get("status") != 'completed'
        context_item = output
    elif api == 'messages':
        content = data.get('content') or []
        text = ''.join(x.get('text','') for x in content if isinstance(x,dict) and x.get('type') == 'text')
        calls = [{'name':x.get('name'),'arguments':json.dumps(x.get('input',{})), 'call_id':x.get('id')}
                 for x in content if isinstance(x,dict) and x.get('type') == 'tool_use']
        context_item = {'role':'assistant','content':content}
        incomplete = data.get('stop_reason') not in ('end_turn','tool_use','stop_sequence')
    else:
        choices = data.get("choices") or []
        choice = choices[0] if choices else {}
        message = choice.get("message") or {}
        text = message.get("content") or ""
        calls = [{"name":x.get("function",{}).get("name"),"arguments":x.get("function",{}).get("arguments"),
                  "call_id":x.get("id")} for x in message.get("tool_calls",[])]
        context_item = message
        incomplete = choice.get("finish_reason") not in ('stop','tool_calls','function_call')
    if not isinstance(text,str):
        raise ValueError('text must be a string')
    if data.get('model') is not None and not isinstance(data['model'],str):
        raise ValueError('model must be a string')
    incomplete = incomplete and result.get('transport_state') == 'ok'
    rt = None
    if isinstance(usage,dict):
        for details in (usage.get("output_tokens_details"),usage.get("completion_tokens_details"),usage):
            if isinstance(details,dict) and type(details.get("reasoning_tokens")) is int: rt = details["reasoning_tokens"]; break
    row = {k:result.get(k) for k in ("http_status","transport_state","error","latency_ms","first_token_ms","stream_events","payload_hash")}
    row.update(model_returned=data.get("model"),usage=usage,reasoning_tokens=rt,text=text,
               completed=result.get("transport_state") == "ok" and not incomplete and bool(text or calls),
               incomplete=incomplete)
    return row, calls, context_item
