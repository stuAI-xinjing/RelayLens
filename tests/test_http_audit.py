"""Real loopback HTTP smoke tests; no paid external endpoint or credential."""
import contextlib
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from relaylens.audit import main
from relaylens.challenges import suite
from relaylens.transport import extract


class HttpAuditTests(unittest.TestCase):
    def test_three_wire_protocols_tool_roundtrip_and_reports(self):
        expected = {}
        for task in suite(789,1,64):
            answer = (task.expected if task.family == 'instruction' else
                      json.dumps({'expression':task.metadata['canonical']}) if task.family == 'code_repair' else json.dumps(task.expected))
            expected[task.prompt] = answer
        owner = self
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass

            def respond(self,data):
                raw = json.dumps(data).encode()
                self.send_response(200); self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)

            def stream(self,data):
                if self.path.endswith('/responses'):
                    text = data['output'][0]['content'][0]['text']
                    events = [{'type':'response.output_text.delta','delta':text},{'type':'response.completed','response':data}]
                elif self.path.endswith('/messages'):
                    text = data['content'][0]['text']
                    events = [{'type':'message_start','message':{'role':'assistant','model':'actual-alias','content':[]}},
                              {'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}},
                              {'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':text}},
                              {'type':'message_delta','delta':{'stop_reason':'end_turn'}},{'type':'message_stop'}]
                else:
                    text = data['choices'][0]['message']['content']
                    events = [{'model':'actual-alias','choices':[{'delta':{'content':text},'finish_reason':None}]},
                              {'model':'actual-alias','choices':[{'delta':{},'finish_reason':'stop'}]}]
                raw = ''.join('data: ' + json.dumps(x) + '\n\n' for x in events)
                if self.path.endswith('/chat/completions'):
                    raw += 'data: [DONE]\n\n'
                raw = raw.encode()
                self.send_response(200); self.send_header('Content-Type','text/event-stream')
                self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)

            def do_GET(self):
                self.respond({'data':[{'id':'gateway-alias'}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                seen.append((self.path,body))
                messages = body.get('messages',[])
                if self.path.endswith('/responses'):
                    prompt = body['input'] if isinstance(body['input'],str) else ''
                    context = body['input'] if isinstance(body['input'],list) else []
                    is_follow = bool(context)
                    tools = body.get('tools',[])
                    tool_name = tools[0]['name'] if tools else ''
                else:
                    owner.assertEqual(messages[0]['role'],'user')
                    prompt = messages[0]['content'] if isinstance(messages[0]['content'],str) else ''
                    is_follow = len(messages) > 1
                    tools = body.get('tools',[])
                    tool_name = (tools[0].get('name') or tools[0].get('function',{}).get('name')) if tools else ''
                tool = bool(tools) and not is_follow
                text = expected.get(prompt,'RELAYLENS_OK')
                if is_follow:
                    if self.path.endswith('/responses'):
                        text = next(x['output'] for x in context if x.get('type') == 'function_call_output')
                    elif self.path.endswith('/messages'):
                        text = messages[-1]['content'][0]['content']
                    else:
                        text = messages[-1]['content']
                city = prompt.split(' for ')[-1].split(',')[0] if tool else ''
                if self.path.endswith('/messages'):
                    owner.assertEqual(self.headers.get('x-api-key'),'test-secret-key')
                    owner.assertNotIn('Authorization',self.headers)
                    content = [{'type':'tool_use','id':'call1','name':tool_name,'input':{'city':city}}] if tool else [{'type':'text','text':text}]
                    data = {'type':'message','role':'assistant','model':'actual-alias','content':content,'stop_reason':'tool_use' if tool else 'end_turn'}
                elif self.path.endswith('/responses'):
                    output = [{'type':'function_call','name':tool_name,'call_id':'call1','arguments':json.dumps({'city':city})}] if tool else [{'type':'message','content':[{'type':'output_text','text':text}]}]
                    data = {'model':'actual-alias','status':'completed','output':output}
                else:
                    msg = {'role':'assistant','content':text}
                    if tool:
                        msg = {'role':'assistant','content':None,'tool_calls':[{'id':'call1','type':'function','function':{'name':tool_name,'arguments':json.dumps({'city':city})}}]}
                    data = {'model':'actual-alias','choices':[{'message':msg,'finish_reason':'tool_calls' if tool else 'stop'}]}
                if body.get('stream'):
                    self.stream(data)
                else:
                    self.respond(data)

        server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                for api in ('responses','chat','messages'):
                    with self.subTest(api=api),contextlib.redirect_stdout(io.StringIO()):
                        output = Path(directory)/f'{api}.json'
                        public = Path(directory)/f'{api}-public.json'
                        html = Path(directory)/f'{api}.html'
                        self.assertEqual(main(['--base-url',f'http://127.0.0.1:{server.server_port}/v1','--model','gateway-alias',
                              '--target-model','gpt-6-astra' if api != 'messages' else 'claude-opus-5-5',
                              '--api',api,'--api-key','test-secret-key','--seed','789','--task-rounds','1','--efforts','high',
                              '--pack','challenge','--context-records','64',
                              '--repeats','2','--stream','--route','direct','--out',str(output),'--public-out',str(public),'--html-out',str(html)]),0)
                        report = json.loads(output.read_text(encoding='utf-8'))
                        self.assertTrue(report['tool_summary']['result_used'])
                        self.assertEqual(len(report['task_summary']),14)
                        self.assertTrue(all(x['accuracy'] == 1 for x in report['task_summary'].values()))
                        self.assertEqual(report['verdict']['grade'],'B')
                        self.assertNotIn('test-secret-key',output.read_text(encoding='utf-8'))
                        sanitized = json.loads(public.read_text(encoding='utf-8'))
                        self.assertTrue(all('text' not in x['observed'] for x in sanitized['cases']))
                        self.assertNotIn('<script>',html.read_text(encoding='utf-8'))
        finally:
            server.shutdown(); server.server_close(); thread.join()
        self.assertTrue(seen)

    def test_truncated_answers_cannot_pass(self):
        for api,data in (
            ('chat',{'choices':[{'message':{'content':'OK'},'finish_reason':'length'}]}),
            ('messages',{'content':[{'type':'text','text':'OK'}],'stop_reason':'max_tokens'}),
            ('responses',{'output_text':'OK','status':'incomplete'}),
        ):
            row,_,_ = extract({'transport_state':'ok','data':data},api)
            self.assertFalse(row['completed'],api)
