"""Request-level statistical and integration checks; no live model claims."""
import contextlib
import copy
import io
import itertools
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from relaylens.audit import main, verdict
from relaylens.comparison import apply_comparisons
from relaylens.numeric_fingerprint import VERSION, prompts, features, describe, compare_numeric, paired_test
from relaylens.privacy import private_report
from test_evidence import report


def numeric_report(n=30,value=7,run_id='reference'):
    result = report()
    result['run_id'] = run_id
    result['settings'].update(numeric_samples=n,numeric_version=VERSION,max_output_tokens=4096,
                              stream=False,fingerprint_temperature=None)
    for probe in prompts(result['seed'],n):
        result['cases'].append({'id':f'numeric-{probe["index"]}@0','case_id':f'numeric-{probe["index"]}',
            'family':'numeric_fingerprint','numeric_index':probe['index'],'prompt_hash':probe['prompt_hash'],
            'completed':True,'observed':{'completed':True,'transport_state':'ok',
            'text':json.dumps([value]*probe['length'])}})
    return result


class NumericFingerprintTests(unittest.TestCase):
    def test_generator_reproducible_distinct_and_seeded(self):
        a=prompts(917,100)
        self.assertEqual(a,prompts(917,100))
        self.assertNotEqual(a,prompts(918,100))
        self.assertEqual(len({p['prompt_hash'] for p in a}),100)

    def test_parser_preserves_types_and_rejects_partial_prose(self):
        for text in ('[true,2]','[1.0,2]','[0,2]','[356,2]','[1]','[1,2,3]',
                     '[NaN,2]','{"a":1,"a":2}','```json\n[1,2]\n```','1 2'):
            self.assertIsNone(features(text,2)[0],text)
        vector,error=features('[1,355]',2)
        self.assertIsNone(error)
        self.assertEqual(len(vector),429)
        self.assertAlmostEqual(sum(x*x for x in vector),1)

    def test_small_number_of_requests_not_inflated_by_numbers(self):
        result=compare_numeric(numeric_report(3,200,'candidate'),numeric_report(3))
        self.assertEqual(result['status'],'insufficient_samples')
        self.assertEqual(result['paired_requests'],3)
        self.assertNotIn('permutation_p',result)

    def test_same_responses_do_not_prove_identity(self):
        result=compare_numeric(numeric_report(run_id='candidate'),numeric_report(),trusted=True)
        self.assertEqual(result['status'],'no_shift_detected')
        self.assertEqual(result['permutation_p'],1)
        self.assertEqual(result['identity'],'not_established')

    def test_separated_synthetic_distributions_and_mixture(self):
        reference=numeric_report()
        for altered in (30,15):
            candidate=numeric_report(run_id='candidate')
            for row in candidate['cases'][-30:][:altered]:
                row['observed']['text']=json.dumps([200]*len(json.loads(row['observed']['text'])))
            result=compare_numeric(candidate,reference,trusted=True)
            self.assertEqual(result['status'],'distribution_shift')
            self.assertLess(result['permutation_p'],.05)
            self.assertNotIn('mixing_fraction',result)

    def test_invalid_counts_and_failures_not_silently_discarded(self):
        candidate=numeric_report(run_id='candidate')
        candidate['cases'][-1]['completed']=False
        candidate['cases'][-2]['observed']['text']='[]'
        result=compare_numeric(candidate,numeric_report())
        self.assertEqual(result['status'],'invalid_or_incomplete_samples')
        self.assertEqual(result['candidate_invalid'],{'unfinished_request':1,'wrong_length':1})
        self.assertNotIn('permutation_p',result)

    def test_duplicate_missing_and_changed_prompts_rejected(self):
        for mutation in ('duplicate','missing','hash'):
            candidate=numeric_report(run_id='candidate')
            if mutation=='duplicate': candidate['cases'].append(copy.deepcopy(candidate['cases'][-1]))
            elif mutation=='missing': candidate['cases'].pop()
            else: candidate['cases'][-1]['prompt_hash']='forged'
            self.assertEqual(compare_numeric(candidate,numeric_report())['status'],'invalid_report')

    def test_settings_self_reference_and_public_text_boundaries(self):
        reference=numeric_report(); candidate=numeric_report(run_id='candidate')
        self.assertEqual(compare_numeric(reference,reference)['status'],'invalid_report')
        candidate['settings']['fingerprint_temperature']=.7
        self.assertEqual(compare_numeric(candidate,reference)['status'],'incompatible_settings')
        public=private_report(reference)
        self.assertEqual(compare_numeric(public,reference)['status'],'answer_text_unavailable')
        self.assertEqual(describe(public)['status'],'answer_text_unavailable')
        self.assertTrue(all('text' not in r['observed'] for r in public['cases']))

    def test_paired_swap_statistic_against_small_exhaustive_oracle(self):
        # Recompute all possible label swaps using a separate direct formula.
        left=[[0.0],[.2],[.4],[.6]]; right=[[.7],[.8],[1.1],[1.2]]
        def kernel(a,b): return sum(math.exp(-(a[0]-b[0])**2/s) for s in (.05,.2,1.0))/3
        def statistic(a,b):
            return sum(kernel(a[i],a[j])+kernel(b[i],b[j])-kernel(a[i],b[j])-kernel(b[i],a[j])
                       for i in range(4) for j in range(4) if i!=j)/12
        observed=statistic(left,right); exact=0
        for swaps in itertools.product((False,True),repeat=4):
            a=[right[i] if swaps[i] else left[i] for i in range(4)]
            b=[left[i] if swaps[i] else right[i] for i in range(4)]
            exact+=statistic(a,b)>=observed-1e-12
        result=paired_test(left,right,66)
        self.assertAlmostEqual(result['mmd_statistic'],observed)
        self.assertAlmostEqual(result['permutation_p'],exact/16,delta=.035)

    def test_offline_panel_has_multiplicity_and_no_api_access(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root); refs=root/'refs'; refs.mkdir()
            reference=numeric_report(); candidate=numeric_report(30,200,'candidate')
            for i,target in enumerate(('gpt-6-astra','claude-opus-5-5')):
                reference['target_model']=target
                (refs/f'{i}.json').write_text(json.dumps(reference),encoding='utf-8')
            path=root/'candidate.json'; path.write_text(json.dumps(candidate),encoding='utf-8')
            out=root/'output.json'
            with patch('relaylens.audit.Client',side_effect=AssertionError('offline mode called API')),contextlib.redirect_stdout(io.StringIO()):
                main(['--compare-report',str(path),'--reference-dir',str(refs),'--trust-reference','--out',str(out)])
            result=json.loads(out.read_text(encoding='utf-8'))
            rows=result['numeric_reference_panel']['comparisons']
            self.assertEqual(len(rows),2)
            self.assertTrue(all(r['alpha']==.025 and r['status']=='distribution_shift' for r in rows))
            self.assertEqual(result['verdict']['identity_claim'],'not established')
            self.assertEqual(result['verdict']['task_accuracy'],1)
            self.assertEqual(result['verdict']['grade'],'A')

    def test_numeric_setting_does_not_break_existing_task_comparison(self):
        from relaylens.evidence import compare_reference
        candidate=numeric_report(run_id='candidate'); reference=copy.deepcopy(candidate)
        reference['run_id']='reference'; reference['settings'].pop('numeric_samples'); reference['settings'].pop('numeric_version')
        reference['cases']=[r for r in reference['cases'] if 'grade' in r]
        self.assertEqual(compare_reference(candidate,reference,trusted=True)['status'],'within_margin')

    def test_offline_numeric_only_report(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root); reference=numeric_report(); candidate=numeric_report(run_id='candidate')
            for obj in (candidate,reference): obj['cases']=[r for r in obj['cases'] if 'grade' not in r]
            for name,obj in (('candidate',candidate),('reference',reference)):
                (root/f'{name}.json').write_text(json.dumps(obj),encoding='utf-8')
            with patch('relaylens.audit.Client',side_effect=AssertionError('offline')),contextlib.redirect_stdout(io.StringIO()):
                main(['--compare-report',str(root/'candidate.json'),'--reference-report',str(root/'reference.json'),'--out',str(root/'out.json')])
            output=json.loads((root/'out.json').read_text(encoding='utf-8'))
            self.assertEqual(output['numeric_reference_panel']['comparisons'][0]['status'],'no_shift_detected')
            self.assertFalse(output['numeric_reference_panel']['comparisons'][0]['trusted_by_operator'])
