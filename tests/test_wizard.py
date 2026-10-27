import argparse
import contextlib
import io
import unittest
from unittest.mock import patch

from relaylens.wizard import configure
from relaylens.reporting import clean_local


class WizardTests(unittest.TestCase):
    def test_wizard_selects_target_and_hides_key(self):
        inputs = ['https://gateway.example/v1','1','']
        args = argparse.Namespace(base_url=None,target_model=None,model=None)
        captured = io.StringIO()
        with patch('builtins.input',side_effect=inputs) as prompts,patch('relaylens.wizard.getpass.getpass',return_value='dummy-hidden-key'),contextlib.redirect_stdout(captured):
            configured = configure(args)
        self.assertEqual(prompts.call_count,3)  # Plus one hidden Key entry.
        self.assertEqual(configured.target_model,'gpt-6-astra')
        self.assertEqual(configured.model,'gpt-6-astra')
        self.assertEqual(configured.mode,'fast')
        self.assertEqual(configured.api,'responses')
        self.assertTrue(configured.open_report)
        self.assertNotIn('dummy-hidden-key',captured.getvalue())

    def test_advanced_retains_full_controls(self):
        inputs=['https://gateway.example/v1','1','A','2','gateway-alias','2','2','2','2','1024',
                '5','3','high','20','30','123','','','300','32768','y','n','reports/test.json']
        args=argparse.Namespace(base_url=None,target_model=None,model=None)
        with patch('builtins.input',side_effect=inputs),patch('relaylens.wizard.getpass.getpass',return_value='dummy'),contextlib.redirect_stdout(io.StringIO()):
            configured=configure(args)
        self.assertEqual(configured.mode,'full')
        self.assertEqual(configured.model,'gateway-alias')
        self.assertEqual(configured.api,'chat')
        self.assertEqual(configured.chat_token_field,'max_tokens')
        self.assertEqual(configured.route,'direct')
        self.assertEqual(configured.repeats,3)
        self.assertEqual(configured.fingerprint_samples,20)
        self.assertEqual(configured.numeric_samples,30)
        self.assertEqual(configured.max_output_tokens,32768)

    def test_echoed_key_is_removed_from_local_error_and_answer(self):
        record = {'observed':{'error':'server echoed dummy-secret','text':'dummy-secret'},'api_key':'dummy-secret'}
        result = clean_local(record,('dummy-secret',))
        self.assertNotIn('dummy-secret',str(result))
        self.assertNotIn('api_key',result)
