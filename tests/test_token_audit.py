import copy
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch

from relaylens.token_audit import (normalize_usage, measure_payload, fit_multiplier,
                                   consumption_grade, summarize_report, compare_consumption)


def fixture():
    return {'run_id':'candidate','suite_version':'test','suite_commitment':'hash','seed':3,
            'api_style':'responses','target_model':'gpt-6.1-sol','settings':{'task_effort':'high'},
            'cases':[{'id':str(i),'case_id':str(i),'family':'logic','prompt_hash':str(i),
                      'completed':True,'grade':{'passed':True},
                      'observed':{'usage':{'input_tokens':n,'output_tokens':n,
                                          'input_tokens_details':{'cached_tokens':0}}}}
                     for i,n in enumerate((100,1000,10000))]}


class TokenAuditTests(unittest.TestCase):
    def test_openai_cached_and_reasoning_are_subsets(self):
        result = normalize_usage({'input_tokens':12000,'output_tokens':1186,'total_tokens':13186,
                                  'input_tokens_details':{'cached_tokens':4000,'cache_write_tokens':7000},
                                  'output_tokens_details':{'reasoning_tokens':1024}})
        self.assertEqual(result['total_tokens'],13186)
        self.assertEqual(result['ordinary_input_tokens'],1000)
        self.assertEqual(result['issues'],[])

    def test_claude_total_is_disjoint_sum(self):
        result = normalize_usage({'input_tokens':50,'cache_read_input_tokens':200000,
                                  'cache_creation_input_tokens':500,'output_tokens':75},'messages')
        self.assertEqual(result['input_tokens'],200550)
        self.assertEqual(result['total_tokens'],200625)

    def test_unknown_is_not_zero(self):
        self.assertIsNone(normalize_usage({})['total_tokens'])
        self.assertIsNone(normalize_usage({'input_tokens':50,'output_tokens':10},'messages')['input_tokens'])
        self.assertIsNone(normalize_usage({'input_tokens':50,'output_tokens':10})['cache_read_tokens'])
        self.assertEqual(normalize_usage({'input_tokens':0,'output_tokens':0})['total_tokens'],0)

    def test_invalid_usage_detected(self):
        result = normalize_usage({'input_tokens':100,'output_tokens':20,'total_tokens':150,
                                  'input_tokens_details':{'cached_tokens':101},
                                  'output_tokens_details':{'reasoning_tokens':30}})
        self.assertEqual(set(result['issues']),{'total_mismatch','cache_read_exceeds_input','reasoning_exceeds_output'})
        for value in (True,-1,float('nan'),'4'):
            self.assertIsNone(normalize_usage({'input_tokens':value})['input_tokens'])

    def test_chat_usage(self):
        result = normalize_usage({'prompt_tokens':12,'completion_tokens':8,'total_tokens':20,
                                  'prompt_tokens_details':{'cached_tokens':3}},'chat')
        self.assertEqual(result['total_tokens'],20)
        self.assertEqual(result['cache_read_tokens'],3)

    def test_unknown_model_never_exact(self):
        payload = {'model':'unknown-private-model','input':'hello private content'}
        result = measure_payload(payload)
        self.assertFalse(result['exact'])
        self.assertEqual(result['method'],'character_estimate')
        self.assertNotIn('hello private content',str(result))
        self.assertEqual(len(result['payload_hash']),64)

    def test_optional_tokenizer_runtime_failure_keeps_estimate(self):
        def broken(name):
            raise RuntimeError('optional package unavailable')
        modules = {'tiktoken':SimpleNamespace(get_encoding=broken),
                   'tiktoken.model':SimpleNamespace(MODEL_TO_ENCODING={'known':'encoding'})}
        with patch.dict(sys.modules,modules):
            result = measure_payload({'model':'known','input':'hello'})
        self.assertEqual(result['method'],'character_estimate')
        self.assertFalse(result['exact'])

    def controls(self, slope=1, overhead=3000):
        return [{'input_tokens':n,'reported_input_tokens':n*slope+overhead,'exact':True,
                 'method':'official_input_count','controlled':True} for n in (1000,4000,16000,32000)]

    def test_fixed_overhead_not_multiplier(self):
        result = fit_multiplier(self.controls())
        self.assertAlmostEqual(result['slope'],1)
        self.assertAlmostEqual(result['intercept_tokens'],3000)
        self.assertEqual(result['status'],'no_proportional_excess_observed')

    def test_threefold_increment_signal(self):
        result = fit_multiplier(self.controls(3,200))
        self.assertAlmostEqual(result['slope'],3)
        self.assertAlmostEqual(result['intercept_tokens'],200)
        self.assertEqual(result['status'],'proportional_excess_signal')

    def test_estimated_or_ordinary_tasks_cannot_certify_multiplier(self):
        for field,value in (('exact',False),('controlled',False),('method','character_estimate')):
            controls = self.controls(3)
            controls[0][field] = value
            self.assertEqual(fit_multiplier(controls)['status'],'descriptive_only')
        self.assertEqual(fit_multiplier(self.controls()[:2])['status'],'insufficient_samples')

    def test_grade_boundaries_and_missing(self):
        expected = [(0,None),(.1,'甲+'),(.2,'甲'),(.6,'乙'),(.9,'丙'),(1.1,'丙'),
                    (1.11,'丁'),(2,'丁'),(2.1,'戊'),(3,'戊+'),(10,'戊+')]
        for value,grade in expected:
            self.assertEqual(consumption_grade(value),grade)
        self.assertIsNone(consumption_grade(None))

    def test_partial_usage_keeps_coverage_and_no_total(self):
        report = fixture()
        report['cases'][0]['observed']['usage'] = {}
        result = summarize_report(report)
        self.assertIsNone(result['totals']['total_tokens'])
        self.assertEqual(result['coverage']['input_tokens']['known_requests'],2)
        self.assertEqual(result['coverage']['input_tokens']['known_subtotal'],11000)
        self.assertIsNone(result['consumption_grade'])

    def test_invalid_usage_not_fitted(self):
        report = fixture()
        for row in report['cases']:
            row['family'] = 'token_control'
            row['observed']['token_measurement'] = {'input_tokens':row['observed']['usage']['input_tokens'],
                'method':'official_input_count','exact':True}
        report['cases'][0]['observed']['usage']['total_tokens'] = 999999
        result = summarize_report(report)
        self.assertEqual(result['multiplier']['n'],2)
        self.assertEqual(result['multiplier']['status'],'insufficient_samples')

    def paired(self):
        candidate,reference = fixture(),fixture()
        reference['run_id'] = 'reference'
        return candidate,reference

    def test_matched_reference_grade_independent(self):
        candidate,reference = self.paired()
        for row in candidate['cases']:
            row['observed']['usage']['input_tokens'] *= 3
            row['observed']['usage']['output_tokens'] *= 3
        before = copy.deepcopy(candidate)
        result = compare_consumption(candidate,reference,trusted=True)
        self.assertEqual(result['grade'],'戊+')
        self.assertAlmostEqual(result['ratio'],3)
        self.assertEqual(candidate,before)

    def test_task_sizes_do_not_determine_weight(self):
        candidate,reference = self.paired()
        for row,factor in zip(candidate['cases'],(.5,1,2)):
            for key in ('input_tokens','output_tokens'): row['observed']['usage'][key] *= factor
        result = compare_consumption(candidate,reference,trusted=True)
        self.assertAlmostEqual(result['ratio'],1)
        self.assertEqual(result['grade'],'丙')

    def test_no_untrusted_or_incomplete_or_failed_good_grade(self):
        candidate,reference = self.paired()
        self.assertIsNone(compare_consumption(candidate,reference)['grade'])
        candidate['cases'][0]['grade']['passed'] = False
        result = compare_consumption(candidate,reference,trusted=True)
        self.assertEqual(result['status'],'quality_not_comparable')
        self.assertIsNone(result['grade'])
        candidate,reference = self.paired()
        candidate['cases'].pop()
        self.assertEqual(compare_consumption(candidate,reference,trusted=True)['status'],'task_coverage_mismatch')

    def test_no_cache_or_config_mismatch_grade(self):
        candidate,reference = self.paired()
        candidate['cases'][0]['observed']['usage']['input_tokens_details']['cached_tokens'] = 50
        self.assertEqual(compare_consumption(candidate,reference,trusted=True)['status'],'cache_cohort_mismatch')
        candidate,reference = self.paired()
        candidate['settings']['task_effort'] = 'low'
        self.assertEqual(compare_consumption(candidate,reference,trusted=True)['status'],'incompatible')
        candidate,reference = self.paired()
        candidate['cases'][0]['observed']['usage'].pop('input_tokens_details')
        self.assertEqual(compare_consumption(candidate,reference,trusted=True)['status'],'cache_evidence_missing')


if __name__ == '__main__':
    unittest.main()
