import copy
import unittest

from relaylens.audit import verdict
from relaylens.evidence import compare_reference, diagnostics, compare_fingerprints
from relaylens.stats import summary
from relaylens.tasks import suite


def report(n=40):
    rows = [{'id':f'task-{i}@0','case_id':f'task-{i}','family':'logic','completed':True,
             'prompt_hash':str(i),'grade':{'passed':True},'observed':{'model_returned':'alias','latency_ms':100}}
            for i in range(n)]
    return {'suite_version':'test','suite_commitment':'test-hash','seed':123,'api_style':'responses',
            'target_model':'gpt-6-astra','model_requested':'alias','settings':{'task_effort':'high'},
            'cases':rows,'tool_summary':{'call_detected':True,'followup_completed':True,'result_used':True},
            'models':{'transport_state':'ok','ids':['alias']}}


class EvidenceTests(unittest.TestCase):
    def test_failures_are_counted_in_task_denominator(self):
        rows = report(2)['cases']
        rows[1]['completed'] = False
        self.assertEqual(summary(rows)['logic']['accuracy'],.5)

    def test_same_scores_with_wrong_config_never_calibrate(self):
        candidate, reference = report(),report()
        reference['settings']['task_effort'] = 'low'
        result = compare_reference(candidate,reference,trusted=True)
        self.assertEqual(result['status'],'incompatible')
        self.assertFalse(result['compatible']['settings'])

    def test_imported_trust_flag_is_not_accepted(self):
        candidate, reference = report(),report()
        reference['trusted'] = True
        candidate['reference_comparison'] = compare_reference(candidate,reference)
        self.assertEqual(verdict(candidate)['grade'],'B')
        self.assertEqual(verdict(candidate)['identity_claim'],'not established')

    def test_small_perfect_sample_stays_uncertain(self):
        candidate = report(3)
        candidate['reference_comparison'] = compare_reference(candidate,report(3),trusted=True)
        self.assertEqual(candidate['reference_comparison']['status'],'insufficient_samples')
        self.assertEqual(verdict(candidate)['grade'],'B')

    def test_relabeling_one_prompt_does_not_inflate_sample_size(self):
        candidate,reference = report(),report()
        for row in candidate['cases'] + reference['cases']:
            row['prompt_hash'] = 'one-question'
        result = compare_reference(candidate,reference,trusted=True)
        self.assertEqual(result['unique_tasks'],1)
        self.assertEqual(result['status'],'insufficient_samples')

    def test_missing_or_changed_prompt_rejected(self):
        candidate, reference = report(),report()
        reference['cases'][0]['prompt_hash'] = 'changed'
        self.assertEqual(compare_reference(candidate,reference,trusted=True)['status'],'incompatible')
        reference = report()
        reference['cases'].pop()
        self.assertEqual(compare_reference(candidate,reference,trusted=True)['status'],'incompatible')

    def test_clear_dilution_identified_against_reference(self):
        candidate, reference = report(),report()
        for row in candidate['cases'][:20]:
            row['grade']['passed'] = False
        candidate['reference_comparison'] = compare_reference(candidate,reference,trusted=True)
        self.assertEqual(candidate['reference_comparison']['status'],'below_reference')
        self.assertEqual(verdict(candidate)['capability_status'],'below_reference')

    def test_broad_paired_agreement_does_not_claim_identity(self):
        candidate = report()
        candidate['reference_comparison'] = compare_reference(candidate,report(),trusted=True)
        self.assertEqual(verdict(candidate)['grade'],'A')
        self.assertEqual(verdict(candidate)['identity_claim'],'not established')

    def test_same_task_flips_are_weak_mixture_signal(self):
        rows = report(1)['cases']
        other = copy.deepcopy(rows[0]); other['id'] += '-repeat'; other['grade']['passed'] = False
        result = diagnostics(rows+[other])['stability']
        self.assertEqual(result['mixture_status'],'signals_detected')
        self.assertEqual(result['flip_rate'],1)

    def test_fingerprint_distribution_drift_and_small_sample(self):
        def samples(text,n):
            return [{'case_id':'fp','family':'fingerprint','prompt_hash':'same','completed':True,'observed':{'text':text}} for _ in range(n)]
        self.assertEqual(compare_fingerprints(samples('red',3),samples('blue',3))['status'],'insufficient_samples')
        self.assertEqual(compare_fingerprints(samples('red',25),samples('blue',25))['status'],'distribution_shift')

    def test_all_task_ground_truths_and_format_contracts(self):
        tasks = suite(7654,2)
        self.assertEqual(len({t.family for t in tasks}),8)
        import json
        for task in tasks:
            if task.family == 'instruction':
                answer = task.expected
            elif task.family == 'code_repair':
                answer = json.dumps({'expression':task.metadata['canonical']})
            else:
                answer = json.dumps(task.expected)
            self.assertTrue(task.grade(answer)['passed'],task.id)
            self.assertFalse(task.grade('not an answer')['passed'],task.id)
