import contextlib
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from relaylens.usage_diagnostics import analyze
from relaylens.token_counter import control_prompts
from relaylens.audit import main


def fixture(multiplier=1, overhead=250, exact=True):
    cases=[]
    for level,size in enumerate((100,1000,10000)):
        for repeat in range(3):
            amount=size*multiplier+overhead
            cases.append({'id':str(len(cases)), 'family':'token_control','completed':True,
                'observed':{'text':'OK','payload_hash':str(level),
                    'token_measurement':{'input_tokens':size, 'exact':exact,
                        'method':'official_input_count' if exact else 'character_estimate'},
                    'usage':{'input_tokens':amount,'output_tokens':2,
                        'input_tokens_details':{'cached_tokens':0},
                        'output_tokens_details':{'reasoning_tokens':0}}}})
    return {'api_style':'responses','cases':cases}


class UsageTests(unittest.TestCase):
    def test_fixed_overhead_not_misclassified_as_multiplier(self):
        result=analyze(fixture(overhead=3000))
        self.assertEqual(result['status'],'no_input_signal')
        self.assertAlmostEqual(result['fit']['slope'],1)
        self.assertAlmostEqual(result['fit']['intercept_tokens'],3000)

    def test_proportional_signal_requires_independent_counts(self):
        result=analyze(fixture(multiplier=3))
        self.assertEqual(result['status'],'input_excess_signal')
        self.assertAlmostEqual(result['fit']['slope'],3)
        self.assertEqual(result['upstream_truth'],'not_independently_verified')
        self.assertEqual(analyze(fixture(multiplier=3,exact=False))['status'],'independent_reference_needed')

    def test_cache_change_not_input_inflation(self):
        data=fixture()
        for case in data['cases'][1::3]:
            case['observed']['usage']['input_tokens_details']['cached_tokens']=50
        result=analyze(data)
        self.assertEqual(result['material_variation_groups'],0)
        self.assertEqual(result['cache_changed_groups'],3)

    def test_same_payload_variation_and_invalid_arithmetic(self):
        data=fixture();data['cases'][1]['observed']['usage']['input_tokens']+=100
        self.assertEqual(analyze(data)['status'],'unstable_input_counts')
        data['cases'][0]['observed']['usage']['total_tokens']=999999
        self.assertEqual(analyze(data)['status'],'inconsistent_fields')

    def test_missing_failed_or_noncompliant_probes_are_not_evidence(self):
        data=fixture()
        for row in data['cases'][3:]:
            row['observed']['text']='not OK'
        self.assertEqual(analyze(data)['status'],'incomplete_controls')
        self.assertEqual(analyze(data)['usable_controls'],3)
        for row in data['cases']:
            row['observed']['usage']={}
        self.assertEqual(analyze(data)['missing_usage_requests'],9)
        self.assertEqual(analyze(data)['invalid_usage_requests'],0)

    def test_control_seed_repeats_order_and_span(self):
        prompts=list(control_prompts(123,9))
        self.assertEqual(len(set(prompts)),3)
        self.assertTrue(all(prompts.count(p)==3 for p in prompts))
        self.assertGreater(max(map(len,prompts))/min(map(len,prompts)),40)
        self.assertEqual(prompts,list(control_prompts(123,9)))
        self.assertNotEqual(prompts,list(control_prompts(124,9)))

    def test_usage_only_real_http_no_capability_questions(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                self.respond({'data':[]})
            def respond(self, data):
                body=json.dumps(data).encode()
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(payload)
                self.respond({'status':'completed','output_text':'OK',
                    'usage':{'input_tokens':len(payload['input'])//3+400,'output_tokens':2,
                        'input_tokens_details':{'cached_tokens':0},
                        'output_tokens_details':{'reasoning_tokens':0}}})
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as d,contextlib.redirect_stdout(io.StringIO()):
                out=Path(d)/'result.json'
                rc=main(['--base-url',f'http://127.0.0.1:{server.server_port}/v1',
                    '--api-key','test-key','--model','gpt-6-astra','--usage-only',
                    '--no-stream','--no-billing-auto','--route','direct','--time-budget','40',
                    '--seed','123','--out',str(out),'--html-out',str(out.with_suffix('.html'))])
                result=json.loads(out.read_text(encoding='utf-8'))
                rendered=out.with_suffix('.html').read_text(encoding='utf-8')
            self.assertEqual(rc,0)
            self.assertEqual(len(requests),9)
            self.assertTrue(all(p['reasoning']['effort']=='high' for p in requests))
            self.assertTrue(all(p['max_output_tokens']==32768 for p in requests))
            self.assertEqual(result['audit_purpose'],'token_usage')
            self.assertEqual(result['run_state']['planned_questions'],0)
            self.assertEqual(result['run_state']['planned_requests_max'],10)
            self.assertEqual(result['verdict']['target_grade'],'U')
            self.assertEqual(result['token_audit']['usage_checks']['repeated_payload_groups'],3)
            self.assertIn('用量专项（未测试能力）',rendered)
            self.assertIsNone(result['token_audit']['consumption_grade'])
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()

