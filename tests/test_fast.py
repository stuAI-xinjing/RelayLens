import contextlib
import copy
import io
import json
import multiprocessing
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

from relaylens.audit import main,verdict
from relaylens.fast_suite import suite
from relaylens.transport import Client
from relaylens.evidence import compare_reference
from test_evidence import report


class FastTests(unittest.TestCase):
    def test_eight_questions_cover_eight_families_with_exact_oracles(self):
        tasks=suite(442)
        self.assertEqual(len(tasks),8)
        self.assertEqual(len({t.family for t in tasks}),8)
        self.assertEqual([t.prompt_hash for t in tasks],[t.prompt_hash for t in suite(442)])
        for t in tasks:
            answer=json.dumps({'expression':t.metadata['canonical']}) if t.family=='code_repair' else json.dumps(t.expected)
            self.assertTrue(t.grade(answer)['passed'],t.id)

    def test_completed_sse_does_not_wait_for_socket_eof(self):
        fixtures={
            'responses':[{'type':'response.completed','response':{'status':'completed','output_text':'ok'}}],
            'messages':[{'type':'message_start','message':{'content':[]}}, {'type':'message_delta','delta':{'stop_reason':'end_turn'}},{'type':'message_stop'}],
            'chat':[{'choices':[{'delta':{'content':'ok'},'finish_reason':'stop'}]},'[DONE]'],
        }
        for api,events in fixtures.items():
            def never_eof():
                for event in events:
                    yield ('data: '+(event if isinstance(event,str) else json.dumps(event))+'\n').encode()
                    yield b'\n'
                raise AssertionError('read again after the completion marker')
            Client('https://api.example/v1','test',api=api).read_stream(never_eof(),time.perf_counter())

    def test_deadline_stops_live_heartbeat_stream_and_records_unfinished_tasks(self):
        received=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length',0)))
                self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.end_headers()
                received.set()
                until=time.monotonic()+10
                try:
                    while time.monotonic()<until:
                        self.wfile.write(b': heartbeat\n\n'); self.wfile.flush(); time.sleep(.03)
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): pass
            do_GET=do_POST
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        children={p.pid for p in multiprocessing.active_children()}
        try:
            with tempfile.TemporaryDirectory() as root,contextlib.redirect_stdout(io.StringIO()):
                path=Path(root)/'result.json'; started=time.monotonic()
                main(['--base-url',f'http://127.0.0.1:{server.server_port}/v1','--api-key','test-key','--model','gpt-6-astra',
                      '--mode','fast','--time-budget','4','--timeout','60','--route','direct','--out',str(path)])
                elapsed=time.monotonic()-started; result=json.loads(path.read_text(encoding='utf-8'))
            self.assertTrue(received.is_set(),'must exercise real active HTTP, not only process startup')
            self.assertLess(elapsed,6)
            self.assertEqual(result['run_state']['end_reason'],'budget_exhausted')
            self.assertEqual(result['run_state']['planned_requests_max'],12)
            self.assertEqual(result['run_state']['planned_questions'],8)
            self.assertEqual(result['settings']['max_output_tokens'],32768)
            self.assertEqual(result['settings']['task_effort'],'high')
            self.assertEqual(result['verdict']['grade'],'U')
            self.assertEqual(len([r for r in result['cases'] if 'grade' in r]),8)
            self.assertEqual({p.pid for p in multiprocessing.active_children()},children)
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_labels_distinguish_service_failure_doubt_and_calibrated_deficit(self):
        candidate=report()
        self.assertEqual(verdict(candidate)['grade'],'B')
        for row in candidate['cases']: row['completed']=False
        self.assertEqual(verdict(candidate)['grade'],'U')
        candidate=report(); candidate['cases'][0]['grade']['passed']=False
        self.assertEqual(verdict(candidate)['grade'],'C')
        for row in candidate['cases'][:25]: row['grade']['passed']=False
        candidate['reference_comparison']=compare_reference(candidate,report(),trusted=True)
        self.assertEqual(verdict(candidate)['grade'],'D')
        self.assertEqual(verdict(candidate)['identity_claim'],'not established')

    def test_full_reports_from_previous_release_remain_comparable(self):
        candidate=report(); candidate['settings'].update(mode='full',concurrency=1)
        self.assertEqual(compare_reference(candidate,report(),trusted=True)['status'],'within_margin')
        candidate['settings']['concurrency']=4
        self.assertEqual(compare_reference(candidate,report(),trusted=True)['status'],'incompatible')
