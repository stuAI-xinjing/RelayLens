import copy
import json
from pathlib import Path
import tempfile
import unittest

from relaylens.audit import verdict, finalize_report
from relaylens.content_review import review_grade, review_report, structured_answer, content_passed
from relaylens.evidence import compare_reference
from relaylens.comparison import apply_comparisons
from relaylens.fast_suite import suite
from relaylens.privacy import private_report
from relaylens.tasks import Task
from test_rating import fast_report
from test_evidence import report


class ContentReviewTests(unittest.TestCase):
    def task(self):
        return Task('demo','data_reasoning','Only JSON',{'east':3,'west':5,'north':7},{})

    def test_correct_prose_is_diagnosed_without_rewriting_strict_grade(self):
        task=self.task(); text='Here is the result. '+json.dumps(task.expected)
        old=task.grade(text); result=review_grade(task,text,old)
        self.assertFalse(result['passed']); self.assertFalse(result['format_passed'])
        self.assertTrue(result['content_passed']); self.assertFalse(old['content_passed'])

    def test_multiple_answers_and_malformed_containers_are_not_cherry_picked(self):
        for text in ('{} [1]', '{} {}', 'first {bad} then {}', 'prefix {"a":1', '{"a":1]'):
            with self.assertRaises(ValueError,msg=text): structured_answer(text)

    def test_types_duplicate_fields_and_extra_keys_still_fail(self):
        task=self.task()
        for text in ('{"east":3,"west":5,"north":true}', '{"east":3,"west":5,"north":7.0}',
                     '{"east":3,"west":5,"north":7,"extra":1}',
                     '{"east":3,"west":5,"north":2,"north":7}'):
            self.assertFalse(review_grade(task,text,task.grade(text))['content_passed'])

    def test_partial_credit_cannot_turn_a_wrong_answer_into_a_pass(self):
        task=self.task(); text='{"east":3,"west":5,"north":8}'
        grade=review_grade(task,text,task.grade(text))
        self.assertAlmostEqual(grade['component_score'],2/3)
        self.assertFalse(grade['passed']);self.assertFalse(grade['content_passed'])
        sample=fast_report()
        for row in sample['cases']:
            row['grade']=dict(grade,component_score=.999)
        self.assertEqual(verdict(sample)['grade'],'D')

    def test_indivisible_probability_and_ordering_do_not_get_fractional_credit(self):
        for task,text in ((Task('p','exact_probability','',{'numerator':2,'denominator':3},{}),'{"numerator":2,"denominator":4}'),
                          (Task('l','logic','',['A','B','C'],{}),'["A","C","B"]')):
            self.assertEqual(review_grade(task,text,task.grade(text))['component_score'],0)

    def test_private_custom_semantics_are_preserved(self):
        class Custom(Task): pass
        task=Custom('x','logic','','secret',{});grade={'passed':True}
        self.assertIs(review_grade(task,'custom format',grade),grade)

    def test_two_rounds_are_sixteen_distinct_prompts(self):
        tasks=suite(44,2)
        self.assertEqual(len(tasks),16); self.assertEqual(len({t.prompt_hash for t in tasks}),16)
        self.assertTrue(all(sum(t.family==family for t in tasks)==2 for family in {t.family for t in tasks}))

    def test_offline_review_checks_prompt_and_answer_integrity(self):
        from relaylens.suite_loader import load_suite
        sample=fast_report(); sample['seed']=442
        _,version,source,commitment=load_suite(pack='fast',context_records=128)
        sample.update(suite_version=version,suite_source=source,suite_commitment=commitment,
                      settings={'pack':'fast','task_rounds':1,'context_records':128})
        original=copy.deepcopy(sample); reviewed=review_report(sample)
        self.assertEqual(sample,original)
        self.assertEqual(reviewed['content_review']['network_calls'],0)
        for row in reviewed['cases']: self.assertTrue(content_passed(row))
        for field,value in (('prompt_hash','changed'),('answer_sha256','changed')):
            changed=copy.deepcopy(sample); changed['cases'][0][field]=value
            with self.assertRaises(ValueError): review_report(changed)
        with self.assertRaises(ValueError): review_report(private_report(sample))

    def test_public_content_diagnostics_do_not_expose_answers(self):
        sample=finalize_report(fast_report()); exported=private_report(sample)
        for row in exported['cases']:
            self.assertNotIn('text',row['observed']);self.assertNotIn('expected',row['grade'])
            self.assertNotIn('parsed',row['grade']);self.assertNotIn('content_reason',row['grade'])
            self.assertIn('component_score',row['grade'])

    def test_imported_content_types_are_validated(self):
        from relaylens.evidence import checked_rows
        for field,value in (('content_passed','false'),('component_score',float('nan')),
                            ('component_score',2),('component_score',True)):
            sample=fast_report();sample['cases'][0]['grade'][field]=value
            with self.assertRaises(ValueError):checked_rows(sample)


class TargetRatingTests(unittest.TestCase):
    def test_perfect_screen_does_not_certify_selected_model(self):
        for target in ('gpt-6-luna','gpt-6-astra','claude-opus-5-5'):
            sample=fast_report();sample['target_model']=target
            result=verdict(sample)
            self.assertEqual(result['grade'],'A');self.assertEqual(result['target_grade'],'U')

    def test_strong_superiority_can_earn_s_but_not_from_identity_or_raw_score(self):
        candidate,reference=report(),report()
        for row in reference['cases'][:20]:row['grade']['passed']=False
        comp=compare_reference(candidate,reference,trusted=True)
        self.assertEqual(comp['status'],'above_reference');self.assertLess(comp['loss_upper_bound'],0)
        candidate['reference_comparison']=comp
        self.assertEqual(verdict(candidate)['target_grade'],'S')
        candidate['reference_comparison']=compare_reference(candidate,reference,trusted=False)
        self.assertEqual(verdict(candidate)['target_grade'],'U')

    def test_a_luna_reference_cannot_certify_astra(self):
        candidate,reference=report(),report();reference['target_model']='gpt-6-luna'
        self.assertEqual(compare_reference(candidate,reference,trusted=True)['status'],'incompatible')

    def test_moderate_gain_is_not_automatically_superiority(self):
        candidate,reference=report(),report()
        for row in reference['cases'][:10]:row['grade']['passed']=False
        candidate['reference_comparison']=compare_reference(candidate,reference,trusted=True)
        self.assertEqual(verdict(candidate)['target_grade'],'A')

    def test_reference_network_failure_does_not_award_s(self):
        candidate,reference=report(),report()
        for row in reference['cases'][:20]:row['completed']=False
        candidate['reference_comparison']=compare_reference(candidate,reference,trusted=True)
        self.assertEqual(verdict(candidate)['target_grade'],'U')

    def test_multiple_target_references_use_weakest_supported_conclusion(self):
        candidate,reference,strong=report(),report(),report()
        for row in reference['cases'][:20]:row['grade']['passed']=False
        with tempfile.TemporaryDirectory() as root:
            paths=[]
            for i,r in enumerate((reference,strong)):
                path=Path(root)/f'{i}.json';path.write_text(json.dumps(r),encoding='utf-8');paths.append(path)
            apply_comparisons(candidate,paths,trusted=True)
        self.assertEqual(verdict(candidate)['target_grade'],'A')
