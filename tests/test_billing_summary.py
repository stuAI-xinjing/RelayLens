import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from relaylens.billing_assistant import validate_extraction, extract
from relaylens.billing_summary import parse_summary, compare_summary
from relaylens.billing_ui import BillingWorkspace
from relaylens.token_display import format_tokens, token_rows
from relaylens.privacy import private_report

TEXT = '模型 请求 Token 实际 标准\ngpt-6.1-sol 19 75.57K $0.0090 $0.180'
CARDS = '\n总请求数 19\n总 Token 75.57K\n输入: 10.80K / 输出: 15.39K / 缓存: 49.37K\n总消费 $0.0090\n标准 $0.1805'


def report():
    # Nineteen independent calls; amounts distributed to preserve exact totals.
    rows = [{'observed': {'usage': {'input_tokens': 3000, 'output_tokens': 700,
             'input_tokens_details': {'cached_tokens': 2400, 'cache_write_tokens': 0}}}} for _ in range(18)]
    rows.append({'observed': {'usage': {'input_tokens': 6173, 'output_tokens': 2794,
                 'input_tokens_details': {'cached_tokens': 6169, 'cache_write_tokens': 0}}}})
    for i, row in enumerate(rows):
        row['id'] = 'synthetic-' + str(i)
    return {'target_model': 'gpt-6.1-sol', 'api_style': 'responses', 'cases': rows,
            'verdict': {'grade': 'U', 'label': '测试数据'}}


class SummaryTests(unittest.TestCase):
    def test_pasted_model_table_rounding(self):
        parsed = parse_summary(TEXT)
        self.assertEqual(parsed['status'], 'recognized')
        f = parsed['aggregates'][0]['fields']['total_tokens']
        self.assertEqual((f['lower'], f['upper']), (75565, 75575))
        comparison = compare_summary(report(), parsed)
        self.assertEqual(comparison['status'], 'within_display_precision')
        self.assertTrue(comparison['scope_not_verified'])
        self.assertNotIn('matched', comparison)

    def test_cards_cache_semantics_dedup(self):
        parsed = parse_summary(CARDS + '\n' + TEXT + '\n' + TEXT)
        self.assertEqual(len(parsed['aggregates']), 1)
        self.assertEqual(parsed['status'], 'recognized')
        row = parsed['aggregates'][0]
        self.assertEqual(row['fields']['standard_cost']['value'], .1805)
        self.assertIn('input_uncached_tokens', row['fields'])
        comparison = compare_summary(report(), parsed)
        for name in ('input_uncached_tokens', 'total_tokens', 'output_tokens', 'cache_read_tokens'):
            self.assertEqual(comparison['comparisons'][0]['fields'][name]['status'], 'within_display_precision')

    def test_different_and_mismatched_scope(self):
        self.assertEqual(compare_summary(report(), parse_summary(TEXT.replace('75.57K', '200K')))['status'], 'aggregate_difference')
        self.assertEqual(compare_summary(report(), parse_summary(TEXT.replace('19', '20')))['status'], 'not_comparable')
        self.assertEqual(compare_summary(report(), parse_summary(TEXT.replace('gpt-6.1-sol', 'claude-opus')))['status'], 'not_comparable')

    def test_conflicting_rows_not_added(self):
        parsed = parse_summary(TEXT + '\n' + TEXT.replace('75.57K', '100K'))
        self.assertEqual(parsed['status'], 'ambiguous')
        self.assertEqual(compare_summary(report(), parsed)['status'], 'not_comparable')

    def test_million_and_integer_exact(self):
        f = parse_summary(TEXT.replace('75.57K', '1.234M'))['aggregates'][0]['fields']['total_tokens']
        self.assertEqual((f['lower'], f['upper']), (1233500,1234500))
        f = parse_summary(TEXT.replace('75.57K', '75,567'))['aggregates'][0]['fields']['total_tokens']
        self.assertEqual(f['lower'], f['upper'])

    def test_display_no_duplicate_cache(self):
        from relaylens.token_audit import summarize_report
        rows = {r['field']:r for r in token_rows(summarize_report(report()))}
        self.assertEqual(rows['ordinary_input_tokens']['value'],10804)
        self.assertIn('75.567K', rows['total_tokens']['display'])
        self.assertIn('0.075567M', rows['total_tokens']['display'])
        self.assertEqual(format_tokens(None), '未记录')

    def test_unknown_cache_not_invented(self):
        rows=token_rows({'totals':{'input_tokens':100,'cache_read_tokens':10}})
        self.assertIsNone(next(r for r in rows if r['field']=='ordinary_input_tokens')['value'])

    def test_summary_import_source_preserved_and_public_scrub(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'r.json';p.write_text(json.dumps(report()),encoding='utf-8')
            original=p.read_bytes()
            w=BillingWorkspace(p)
            result=w.import_text(TEXT)
            self.assertEqual(result['state']['billing_summary']['status'],'within_display_precision')
            self.assertEqual(p.read_bytes(),original)
            self.assertNotIn('billing_summary',private_report(w.report))
            self.assertIn('75.567K',w.output.with_suffix('.html').read_text(encoding='utf-8'))
            result=w.import_file('page.txt',base64.b64encode(TEXT.encode()).decode())
            self.assertEqual(result['import']['state'],'aggregate')


class AssistantTests(unittest.TestCase):
    def extraction(self):
        return {'aggregates':[{'model':'gpt-6.1-sol','fields':{
            'request_count':{'raw':'19','quote':'gpt-6.1-sol 19'},
            'total_tokens':{'raw':'75.57K','quote':'19 75.57K'}}}]}

    def test_evidence_validation(self):
        r=validate_extraction(TEXT,self.extraction())
        self.assertTrue(r['requires_review'])
        self.assertEqual(compare_summary(report(),r)['status'],'within_display_precision')
        for field,value in [('total_tokens','90K'),('request_count','19K')]:
            bad=self.extraction();bad['aggregates'][0]['fields'][field]['raw']=value
            with self.assertRaises(ValueError):validate_extraction(TEXT,bad)
        bad=self.extraction();bad['aggregates'][0]['model']='gpt-fake'
        with self.assertRaises(ValueError):validate_extraction(TEXT,bad)
        bad=self.extraction();bad['aggregates'][0]['fields']='malformed'
        with self.assertRaises(ValueError):validate_extraction(TEXT,bad)

    def test_image_evidence_is_provisional(self):
        extracted=self.extraction()
        extracted['transcript']=TEXT
        data={'choices':[{'message':{'content':json.dumps(extracted)},'finish_reason':'stop'}]}
        with patch('relaylens.billing_assistant.config',return_value={'key':'analysis-private','base_url':'https://analysis.example/v1','model':'qwen3.7-plus'}):
            with patch('relaylens.billing_assistant.Client.request',return_value={'transport_state':'ok','data':data}):
                result=extract('',image=b'image',mime='image/png')
        self.assertEqual(result['source'],'assistant_image_extraction')
        self.assertTrue(result['requires_review'])
        self.assertIn('image_digits_require_visual_review',result['issues'])

    def test_image_analysis_works_when_local_ocr_unavailable(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'r.json';p.write_text(json.dumps(report()),encoding='utf-8')
            summary=validate_extraction(TEXT,self.extraction())
            summary['source']='assistant_image_extraction'
            with patch('relaylens.billing.import_billing_image',return_value={'state':'ocr_unavailable','records':[]}):
                with patch('relaylens.billing_assistant.status',return_value={'available':True}):
                    with patch('relaylens.billing_assistant.extract',return_value=summary):
                        result=BillingWorkspace(p).import_file('bill.png',base64.b64encode(b'image').decode())
            self.assertTrue(result['state']['billing_summary']['image_digits_require_review'])

    def test_stream_result_parser_and_redaction(self):
        data={'choices':[{'message':{'content':json.dumps(self.extraction())},'finish_reason':'stop'}]}
        with patch('relaylens.billing_assistant.config',return_value={'key':'analysis-private','base_url':'https://analysis.example/v1','model':'qwen3.7-plus'}):
            with patch('relaylens.billing_assistant.Client.request',return_value={'transport_state':'ok','data':data}) as req:
                self.assertEqual(extract(TEXT+'\nBearer a-private-secret')['status'],'recognized')
                sent=json.dumps(req.call_args.args[1])
                self.assertNotIn('a-private-secret',sent)
                self.assertNotIn('analysis-private',sent)

    def test_no_network_for_supported_paste(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'r.json';p.write_text(json.dumps(report()),encoding='utf-8')
            with patch('relaylens.billing_assistant.extract') as ai:
                BillingWorkspace(p).import_text(TEXT)
                ai.assert_not_called()

    def test_failed_assistant_keeps_report(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'r.json';p.write_text(json.dumps(report()),encoding='utf-8')
            w=BillingWorkspace(p)
            with patch('relaylens.billing_assistant.extract',side_effect=ValueError('HTTP 401')):
                result=w.import_text('unrecognized text',use_assistant=True)
                self.assertIn('HTTP 401',result['import']['warnings'])
                self.assertFalse(w.output.exists())


if __name__ == '__main__':
    unittest.main()
