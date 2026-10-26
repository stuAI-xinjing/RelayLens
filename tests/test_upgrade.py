"""Regression and independent-oracle checks for the expanded audit."""
import contextlib
import copy
import io
import itertools
import json
import random
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

from relaylens.audit import main, make_tool_case, verdict
from relaylens.challenges import suite, exact_probability, backend_transactions, frontend_state
from relaylens.comparison import compare_panel, apply_comparisons
from relaylens.evidence import compare_reference, compare_fingerprints, quality_profile, regression_upper_bound
from relaylens.grading import exact, strict_json
from relaylens.privacy import private_report
from relaylens.tasks import Task, evaluate_expression
from relaylens.transport import Client, extract
from relaylens.suite_loader import _sha256
from test_evidence import report


class UpgradeTests(unittest.TestCase):
    def test_json_types_duplicates_and_nonfinite_are_not_answers(self):
        task = Task('x','arithmetic','prompt',{'count':1},{})
        for answer in ('{"count":true}','{"count":1.0}','{"count":2,"count":1}','{"count":NaN}'):
            self.assertFalse(task.grade(answer)['passed'],answer)
        self.assertTrue(task.grade('{"count":1}')['passed'])
        wrapped = task.grade('```json\n{"count":1}\n```')
        self.assertTrue(wrapped['content_passed'])
        self.assertFalse(wrapped['passed'])

    def test_python_boolean_short_circuit_and_operand_semantics(self):
        self.assertEqual(evaluate_expression('3 or 1/0',{}),3)
        self.assertEqual(evaluate_expression('0 and 1/0',{}),0)
        self.assertEqual(evaluate_expression('1 and 7',{}),7)

    def test_challenge_pack_reproducibility_and_solutions(self):
        tasks = suite(67,1,64)
        again = suite(67,1,64)
        self.assertEqual(len(tasks),14)
        self.assertEqual([t.prompt_hash for t in tasks],[t.prompt_hash for t in again])
        for task in tasks:
            answer = task.expected if task.family=='instruction' else json.dumps({'expression':task.expected}) if task.family=='code_repair' else json.dumps(task.expected)
            self.assertTrue(task.grade(answer)['passed'],task.id)
            self.assertFalse(task.grade('{}')['passed'],task.id)

    def test_probability_against_labelled_ball_enumeration(self):
        class Three:
            def randint(self,*args): return 3
        task = exact_probability(Three(),0)
        universe = list(itertools.permutations(range(9),4))
        conditioned = [p for p in universe if sum(x//3==2 for x in p)==1 and p[0]//3!=p[-1]//3]
        good = sum(sum(x//3==0 for x in p)==2 for p in conditioned)
        fraction = Fraction(good,len(conditioned))
        self.assertEqual(task.expected,{'numerator':fraction.numerator,'denominator':fraction.denominator})

    def test_backend_conservation_and_idempotency_oracle(self):
        for seed in range(20):
            task = backend_transactions(random.Random(seed),seed)
            initial, events = task.metadata['initial'],task.metadata['events']
            balances = initial.copy(); processed = {}; version = 0; statuses = []
            for key, expected, src, dst, amount in events:
                if key not in processed:
                    code = 200 if expected==version and balances[src]>=amount else 409 if expected!=version else 422
                    processed[key] = code
                    if code==200:
                        balances = {k:v+amount*(k==dst)-amount*(k==src) for k,v in balances.items()}
                        version += 1
                statuses.append(processed[key])
            self.assertEqual(task.expected,dict(balances=balances,version=version,statuses=statuses))
            self.assertEqual(sum(initial.values()),sum(balances.values()))
            self.assertGreaterEqual(min(balances.values()),0)

    def test_frontend_stale_response_and_clear_invariants(self):
        for seed in range(20):
            task = frontend_state(random.Random(seed),seed)
            self.assertTrue(task.expected['selected'] is None or task.expected['selected'] in task.expected['items'])
            events = task.metadata['events']
            last_reset = max((i for i,e in enumerate(events) if e[0]=='clear'),default=-1)
            if last_reset>=0 and all(e[0] in ('resolve','reject','select') for e in events[last_reset+1:]):
                self.assertEqual(task.expected,dict(active=None,items=[],selected=None,loading=False,error=None))

    def test_duplicate_ids_and_truthy_grade_rejected(self):
        for bad in ('duplicate','truthy','conflict'):
            candidate = report()
            if bad=='duplicate': candidate['cases'].append(copy.deepcopy(candidate['cases'][0]))
            elif bad=='truthy': candidate['cases'][0]['grade']['passed']='false'
            else: candidate['cases'][0]['observed']['incomplete']=True
            self.assertEqual(compare_reference(candidate,report(),trusted=True)['status'],'invalid_report')

    def test_exact_upper_bound_zero_regressions(self):
        self.assertAlmostEqual(regression_upper_bound(0,40),1-.05**(1/40),places=12)
        self.assertGreater(regression_upper_bound(0,40,.001),regression_upper_bound(0,40,.05))

    def test_outage_is_not_labelled_as_weaker_reasoning(self):
        candidate = report(80)
        for row in candidate['cases'][:50]:
            row['completed']=False; row['observed']['transport_state']='upstream_error'
        result=compare_reference(candidate,report(80),trusted=True)
        self.assertEqual(result['status'],'service_degradation')
        candidate['reference_comparison']=result
        self.assertEqual(verdict(candidate)['capability_status'],'service_degradation')

    def test_panel_keeps_ambiguity_and_corrects_multiple_comparisons(self):
        candidate, a, b = report(80),report(80),report(80)
        b['target_model']='claude-opus-5-5'
        result=compare_panel(candidate,[a,b,a],trusted=True)
        self.assertEqual(result['status'],'overlapping_references')
        self.assertEqual(len(result['comparisons']),2)
        self.assertEqual(result['per_comparison_alpha'],.025)
        self.assertEqual(result['identity'],'not_established')
        self.assertEqual(compare_panel(candidate,[a,b])['status'],'insufficient_evidence')

    def test_reference_alias_or_protocol_cannot_mask_mismatch(self):
        a,b=report(),report(); b['api_style']='messages'
        self.assertEqual(compare_panel(a,[b],trusted=True)['comparisons'][0]['status'],'incompatible')

    def test_missing_fingerprint_text_is_insufficient(self):
        rows=[dict(case_id='fp',family='fingerprint',completed=True,prompt_hash='p',observed={}) for _ in range(40)]
        self.assertEqual(compare_fingerprints(rows,rows)['status'],'insufficient_samples')

    def test_public_export_drops_personal_free_text_and_is_comparable(self):
        source=report(40); source['egress']={'city':'private-city','org':'private-org'}
        source['cases'][0]['observed'].update(text='private-name',error='arbitrary-private-data')
        source['cases'][0]['grade']['expected']='private-answer'
        exported=private_report(source)
        text=json.dumps(exported)
        for value in ('private-city','private-org','private-name','arbitrary-private-data','private-answer'):
            self.assertNotIn(value,text)
        self.assertEqual(compare_reference(source,exported,trusted=True)['status'],'within_margin')
        self.assertIn('private-name',json.dumps(source))

    def test_offline_cli_never_opens_client_or_asks_for_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); candidate=root/'candidate.json'; ref=root/'ref.json'; out=root/'out.json'
            candidate.write_text(json.dumps(report(40)),encoding='utf-8'); ref.write_text(candidate.read_text(),encoding='utf-8')
            with patch('relaylens.audit.Client',side_effect=AssertionError('network forbidden in offline test')),patch('getpass.getpass',side_effect=AssertionError('no key')),contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--compare-report',str(candidate),'--reference-report',str(ref),'--trust-reference','--out',str(out)]),0)
            self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['verdict']['grade'],'A')

    def test_invalid_reference_does_not_discard_other_comparisons(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); (root/'bad.json').write_text('[]'); (root/'good.json').write_text(json.dumps(report()))
            result=apply_comparisons(report(),directory=root,trusted=True)
            self.assertEqual(len(result['reference_panel']['load_errors']),1)
            self.assertEqual(result['reference_comparison']['status'],'within_margin')

    def test_incomplete_and_malformed_shapes_preserve_failure(self):
        for api,data in (('responses',{'output_text':'ok','status':'in_progress'}),
                         ('chat',{'choices':[{'message':{'content':'ok'}}]}),
                         ('messages',{'content':[{'type':'text','text':'ok'}]}),
                         ('chat',{'choices':['broken']})):
            row,_,_=extract({'data':data,'transport_state':'ok'},api)
            self.assertFalse(row['completed'])

    def test_stream_done_without_finish_is_rejected(self):
        client=Client('https://gateway.example/v1','dummy',api='chat')
        with self.assertRaises(ValueError):
            client.read_stream(io.BytesIO(b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'),0)

    def test_tool_uses_unpredictable_typed_receipt(self):
        _,prompt,value=make_tool_case(1)
        self.assertNotIn(value['receipt'],prompt)
        self.assertNotEqual(value['receipt'],make_tool_case(2)[2]['receipt'])
        self.assertFalse(exact(dict(value,temperature_c=str(value['temperature_c'])),value))

    def test_chat_budget_fields_preserve_new_and_legacy_protocols(self):
        for field in ('max_completion_tokens','max_tokens'):
            client=Client('https://gateway.example/v1','dummy',api='chat',max_tokens=9000,chat_token_field=field)
            with patch.object(client,'request',return_value={}) as send:
                client.call('alias','hi',effort='high')
            payload=send.call_args.args[1]
            self.assertEqual(payload[field],9000)
            self.assertEqual(payload['reasoning_effort'],'high')
            self.assertEqual(sum(k in payload for k in ('max_completion_tokens','max_tokens')),1)

    def test_documented_tool_unavailability_does_not_invalidate_task_reference(self):
        a,b=report(),report()
        for obj in (a,b):
            obj['api_style']='chat'; obj['tool_summary']['result_used']=False
        a['reference_comparison']=compare_reference(a,b,trusted=True)
        self.assertEqual(a['reference_comparison']['status'],'within_margin')
        self.assertEqual(verdict(a)['grade'],'A')

    def test_self_reference_rejected_by_run_id(self):
        a,b=report(),report(); a['run_id']=b['run_id']='same-run'
        self.assertEqual(compare_reference(a,b,trusted=True)['status'],'invalid_report')

    def test_quality_repeated_reliability_excludes_best_of_bias(self):
        rows=report(1)['cases']; duplicate=copy.deepcopy(rows[0]); duplicate['grade']['passed']=False
        result=quality_profile(rows+[duplicate])
        self.assertEqual(result['all_repeats_pass_rate'],0)
        self.assertEqual(result['any_repeat_pass_rate'],1)

    def test_newlines_do_not_change_suite_commitment(self):
        with tempfile.TemporaryDirectory() as directory:
            a,b=Path(directory)/'a.py',Path(directory)/'b.py'
            a.write_bytes(b'x=1\ny=2\n'); b.write_bytes(b'x=1\r\ny=2\r\n')
            self.assertEqual(_sha256(a),_sha256(b))

    def test_public_export_is_idempotent(self):
        once=private_report(report())
        self.assertEqual(private_report(once),once)

    def test_network_failure_is_not_reported_as_truncation(self):
        row,_,_=extract({'data':{},'transport_state':'rate_or_quota_error','http_status':429},'responses')
        self.assertFalse(row['incomplete'])
        case=dict(family='logic',case_id='x',completed=False,grade={'passed':False},observed=row)
        self.assertEqual(quality_profile([case])['failures_by_cause'],{'rate_or_quota_error':1})


if __name__=='__main__': unittest.main()
