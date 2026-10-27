"""Capability-first policy tests; these fixtures are not live-model evidence."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from relaylens.audit import record_case,finalize_report,verdict
from relaylens.fast_suite import suite
from relaylens.evidence import compare_reference
from relaylens.reporting import write_html
from test_evidence import report


def fast_report():
    result=report();result['cases']=[]
    for task in suite(442):
        answer=json.dumps({'expression':task.metadata['canonical']}) if task.family=='code_repair' else json.dumps(task.expected)
        row,_,_=record_case(task.id,task.family,task.prompt,{'transport_state':'ok','http_status':200,
            'data':{'status':'completed','output_text':answer}},'responses',task)
        result['cases'].append(row)
    return result


class CapabilityRatingTests(unittest.TestCase):
    def test_default_fast_suite_can_earn_a_without_reference(self):
        result=verdict(fast_report())
        self.assertEqual(result['grade'],'A')
        self.assertEqual(result['evidence_basis'],'task_screen')
        self.assertEqual(result['coverage'],{'unique_questions':8,'families':8,'challenge_questions':6})
        self.assertEqual(result['identity_claim'],'not established')
        self.assertIn('尚无充分',result['target_assessment'])

    def test_disclosed_fast_grade_boundaries(self):
        for passed,expected in ((8,'A'),(7,'B'),(6,'B'),(5,'C'),(4,'C'),(3,'D'),(0,'D')):
            sample=fast_report()
            for row in sample['cases'][passed:]:row['grade']['passed']=False
            self.assertEqual(verdict(sample)['grade'],expected,(passed,expected))

    def test_network_failure_and_repeats_do_not_become_capability_proofs(self):
        sample=fast_report();sample['cases'][0]['completed']=False
        self.assertEqual(verdict(sample)['grade'],'U')
        sample=fast_report();sample['cases']=[copy.deepcopy(sample['cases'][0]) for _ in range(8)]
        for i,row in enumerate(sample['cases']):row['id']=str(i)
        self.assertEqual(verdict(sample)['grade'],'U')

    def test_a_needs_broad_advanced_coverage_or_a_calibrated_reference(self):
        sample=fast_report()
        for row in sample['cases']:row['difficulty']='standard'
        self.assertEqual(verdict(sample)['grade'],'B')
        sample=fast_report()
        for row in sample['cases']:row['family']='logic'
        self.assertEqual(verdict(sample)['grade'],'B')

    def test_behavior_and_tools_do_not_lower_capability_grade(self):
        sample=fast_report();sample['tool_summary']['result_used']=False
        sample['cases'].append({'family':'parameter','completed':False,'observed':{}})
        sample['numeric_reference_panel']={'comparisons':[{'target_model':sample['target_model'],
            'trusted_by_operator':True,'status':'distribution_shift'}]}
        result=verdict(sample)
        self.assertEqual(result['grade'],'A')
        self.assertEqual(result['task_accuracy'],1)
        self.assertEqual(result['usability']['status'],'issues_found')
        self.assertEqual(len(result['usability']['notes']),2)
        self.assertEqual(result['identity_signal']['status'],'behavior_difference')
        self.assertIn('接口提示',result['action'])

    def test_better_task_performance_passes_reference_despite_different_identity(self):
        candidate,reference=report(),report()
        for row in reference['cases'][:10]:row['grade']['passed']=False
        candidate['model_requested']='different-backend'
        candidate['reference_comparison']=compare_reference(candidate,reference,trusted=True)
        result=verdict(candidate)
        self.assertEqual(result['grade'],'A')
        self.assertEqual(result['evidence_basis'],'official_reference')
        self.assertEqual(candidate['reference_comparison']['mean_loss'],-.25)
        self.assertEqual(result['identity_claim'],'not established')

    def test_report_keeps_basis_and_interface_advice_visible(self):
        sample=fast_report();sample['tool_summary']['result_used']=False
        sample=finalize_report(sample)
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'report.html';write_html(sample,path);text=path.read_text(encoding='utf-8')
        self.assertIn('A · 本轮能力达标',text)
        self.assertIn('依据：本轮能力筛查',text)
        self.assertIn('尚无充分的同配置官方对照',text)
        self.assertIn('工具闭环未通过',text)
        self.assertIn('身份与行为线索 · 不计入能力等级',text)
