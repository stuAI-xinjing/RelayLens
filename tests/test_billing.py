"""Billing imports and real loopback HTTP: no paid API or real credentials."""
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from relaylens.billing import (parse_billing_text, import_billing_file, normalize_record,
                               reconcile_billing, fetch_key_billing, _ocr_table)


class BillingTests(unittest.TestCase):
    def test_chinese_csv_and_combined_tokens(self):
        text = '时间,模型,Tokens,缓存,费用\n2026-10-30 12:00:00,gpt-example,"160,754 / 2,722","140,547",$0.000816\n'
        result = parse_billing_text(text)
        self.assertEqual(result['state'], 'ok')
        row = result['records'][0]
        self.assertEqual((row['input_tokens'], row['output_tokens'], row['cached_tokens']), (160754, 2722, 140547))
        self.assertEqual((row['cost'], row['currency']), (.000816, 'USD'))

    def test_json_envelope_strips_unrelated_private_fields(self):
        result = parse_billing_text(json.dumps({'data': {'total': 2, 'items': [
            {'request_id': 'req-a', 'prompt_tokens': 100, 'completion_tokens': 2, 'quota': 47,
             'other': '{"cache_tokens":30,"secret":"private"}', 'api_key': 'must-not-survive',
             'username': 'private-person', 'ip': 'private-ip'}]}}))
        self.assertEqual(result['records'][0]['cached_tokens'], 30)
        self.assertIsNone(result['records'][0]['cost'])
        self.assertNotIn('must-not-survive', json.dumps(result))
        self.assertNotIn('private-person', json.dumps(result))
        self.assertTrue(any('分页' in w for w in result['warnings']))

    def test_ndjson_export_trailer_and_missing_not_zero(self):
        result = parse_billing_text('{"request_id":"r","prompt_tokens":0}\n{"success":true,"data":{"count":1}}')
        self.assertEqual(len(result['records']), 1)
        self.assertEqual(result['records'][0]['input_tokens'], 0)
        self.assertIsNone(result['records'][0]['output_tokens'])
        self.assertIsNone(normalize_record({'prompt_tokens': '2.9M'}))

    def test_file_utf8_bom_and_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bill.csv'
            path.write_text('request_id,input_tokens,output_tokens\nr,40,6', encoding='utf-8-sig')
            self.assertEqual(import_billing_file(path)['records'][0]['input_tokens'], 40)
            self.assertEqual(import_billing_file(Path(folder) / 'missing.csv')['state'], 'invalid')

    @staticmethod
    def report(calls):
        return {'api_style': 'responses', 'model_requested': 'gpt-example', 'cases': [
            {'observed': {'started_at_utc': '2026-10-30T12:00:00+00:00', 'latency_ms': 1000,
                          'model_returned': 'gpt-example', 'usage': {'input_tokens': 100, 'output_tokens': 20,
                            'input_tokens_details': {'cached_tokens': 60}}, **extra}} for extra in calls]}

    def test_exact_id_exposes_inflation_instead_of_filtering_it(self):
        report = self.report([{'request_id': 'r'}])
        bill = normalize_record({'request_id': 'r', 'input_tokens': 300, 'output_tokens': 60, 'cached_tokens': 180})
        result = reconcile_billing(report, [bill])
        self.assertEqual(result['coverage'], 1)
        self.assertEqual(result['rows'][0]['differences']['input_tokens']['ratio'], 3)
        self.assertEqual(result['rows'][0]['differences']['cached_tokens']['delta'], 120)

    def test_duplicate_ids_never_assigned_greedily(self):
        report = self.report([{'request_id': 'r'}, {'request_id': 'r'}])
        bill = normalize_record({'request_id': 'r', 'input_tokens': 100})
        result = reconcile_billing(report, [bill])
        self.assertEqual(result['matched'], 0)
        self.assertEqual(result['ambiguous_calls'], 2)

    def test_timestamp_matching_requires_mutual_uniqueness(self):
        bill = normalize_record({'timestamp': '2026-10-30T12:00:01Z', 'model': 'gpt-example', 'input_tokens': 900})
        single = reconcile_billing(self.report([{}]), [bill])
        self.assertEqual(single['rows'][0]['match_method'], 'time_model')
        self.assertEqual(single['rows'][0]['differences']['input_tokens']['ratio'], 9)
        self.assertEqual(reconcile_billing(self.report([{}, {}]), [bill])['matched'], 0)
        self.assertEqual(reconcile_billing(self.report([{}]), [bill, dict(bill)])['matched'], 0)

    def test_id_disagreement_not_overridden_and_exact_claim_priority(self):
        bill = normalize_record({'request_id': 'different', 'timestamp': '2026-10-30T12:00:01Z',
                                 'model': 'gpt-example', 'input_tokens': 100})
        self.assertEqual(reconcile_billing(self.report([{'request_id': 'r'}]), [bill])['matched'], 0)
        result = reconcile_billing(self.report([{}, {'request_id': 'different'}]), [bill])
        self.assertEqual(result['matched'], 1)
        self.assertEqual(result['rows'][0]['call_index'], 1)

    def test_ocr_table_candidates_are_only_exactly_recognized_layout(self):
        def word(text, x, y):
            return {'text': text, 'x': x, 'y': y, 'width': 30, 'height': 15}
        words = [word('时间', 20, 10), word('模型', 300, 10), word('Tokens', 500, 10), word('费用', 700, 10),
                 word('2026-10-30', 20, 50), word('12:00:00', 110, 50), word('gpt-example', 300, 50),
                 word('160,754 / 2,722', 500, 50), word('缓存 140,547', 500, 70), word('$0.000816', 700, 50)]
        result = _ocr_table([{'words': words}])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['cached_tokens'], 140547)
        self.assertEqual(_ocr_table([{'words': words[4:]}]), [])

    def test_real_http_auth_redirect_and_no_secret_output(self):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_GET(self):
                seen.append((self.path, self.headers.get('Authorization')))
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/leak')
                    self.end_headers()
                    return
                raw = json.dumps({'success': True, 'data': [{'request_id': 'r', 'prompt_tokens': 120,
                                      'completion_tokens': 10, 'api_key': 'private-example-key'}]}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(raw)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            base = 'http://127.0.0.1:' + str(server.server_port)
            result = fetch_key_billing(base, 'private-example-key', route='direct')
            self.assertEqual(result['state'], 'ok')
            self.assertEqual(seen[0], ('/api/log/token', 'Bearer private-example-key'))
            self.assertNotIn('private-example-key', json.dumps(result))
            denied = fetch_key_billing(base, 'private-example-key', route='direct', endpoint='/redirect')
            self.assertEqual(denied['http_status'], 302)
            self.assertNotIn('/leak', [p for p, _ in seen])
            self.assertEqual(fetch_key_billing(base, 'key', endpoint='https://other.example/log')['state'], 'invalid_endpoint')
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == '__main__':
    unittest.main()
