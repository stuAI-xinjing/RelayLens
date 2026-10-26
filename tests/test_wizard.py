import argparse
import contextlib
import io
import unittest
from unittest.mock import patch

from relaylens.wizard import configure
from relaylens.reporting import clean_local


class WizardTests(unittest.TestCase):
    def test_wizard_selects_target_and_hides_key(self):
        inputs = ['https://gateway.example/v1','1','','1','2','1','1','3','high','0','0','123','','','120','4096','y','n','reports/test.json']
        args = argparse.Namespace(base_url=None,target_model=None,model=None)
        captured = io.StringIO()
        with patch('builtins.input',side_effect=inputs),patch('relaylens.wizard.getpass.getpass',return_value='dummy-hidden-key'),contextlib.redirect_stdout(captured):
            configured = configure(args)
        self.assertEqual(configured.target_model,'gpt-6-astra')
        self.assertEqual(configured.model,'gpt-6-astra')
        self.assertEqual(configured.repeats,3)
        self.assertEqual(configured.seed,123)
        self.assertEqual(configured.route,'direct')
        self.assertNotIn('dummy-hidden-key',captured.getvalue())

    def test_echoed_key_is_removed_from_local_error_and_answer(self):
        record = {'observed':{'error':'server echoed dummy-secret','text':'dummy-secret'},'api_key':'dummy-secret'}
        result = clean_local(record,('dummy-secret',))
        self.assertNotIn('dummy-secret',str(result))
        self.assertNotIn('api_key',result)
