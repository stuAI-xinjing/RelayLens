import base64
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from relaylens.billing_ui import BillingWorkspace, create_server
from relaylens.audit import finalize_report
from test_rating import fast_report


class BillingUITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'report.json'
        report=finalize_report(fast_report())
        report['base_url']='https://relay.example/v1'
        report['cases'][0]['observed'].update(request_id='req-a',usage={'input_tokens':100,'output_tokens':20})
        self.path.write_text(json.dumps(report),encoding='utf-8')
        self.digest=hashlib.sha256(self.path.read_bytes()).hexdigest()

    def tearDown(self): self.temp.cleanup()

    def test_whole_csv_upload_preserves_source_and_excludes_raw_private_fields(self):
        workspace=BillingWorkspace(self.path,{'key':'private-key'})
        raw='request_id,input_tokens,output_tokens,username,api_key\nreq-a,300,60,private-user,private-key'
        result=workspace.import_file('bill.csv',base64.b64encode(raw.encode()).decode())
        self.assertEqual(result['state']['billing']['matched'],1)
        self.assertEqual(result['state']['billing']['comparison_totals']['input_tokens']['ratio'],3)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.digest)
        self.assertNotIn('private-',workspace.output.read_text(encoding='utf-8'))
        self.assertTrue(workspace.output.with_suffix('.html').exists())
        self.assertNotIn('private-key',json.dumps(workspace.state()))

    def test_ocr_requires_review_and_does_not_save_guesses(self):
        workspace=BillingWorkspace(self.path)
        with patch('relaylens.billing.import_billing_image',return_value={'state':'needs_review','ocr_text':'uncertain digits','records':[]}):
            result=workspace.import_file('bill.png',base64.b64encode(b'dummy image').decode())
        self.assertEqual(result['import']['state'],'needs_review')
        self.assertFalse(workspace.output.exists())

    def test_session_key_cannot_be_reused_for_a_different_host(self):
        workspace=BillingWorkspace(self.path,{'key':'private-key'})
        with patch('relaylens.billing.fetch_key_billing') as fetch:
            with self.assertRaises(ValueError): workspace.connect({'url':'https://different.example'})
            fetch.assert_not_called()

    def test_live_http_upload_path_secret_origin_and_report_render(self):
        server=create_server(self.path)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        url=server.workspace_url
        try:
            with urllib.request.urlopen(url) as r:
                self.assertIn('Token',r.read().decode())
            with urllib.request.urlopen(url+'state') as r:
                self.assertIn('token_audit',json.load(r))
            with urllib.request.urlopen(url+'report') as r:
                self.assertIn('Token 消耗',r.read().decode())
            req=urllib.request.Request(url+'text',data=json.dumps({'text':'request_id,input_tokens\nreq-a,300'}).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req) as r:
                self.assertEqual(json.load(r)['state']['billing']['matched'],1)
            req.add_header('Origin','https://unrelated.example')
            with self.assertRaises(urllib.error.HTTPError) as denied: urllib.request.urlopen(req)
            self.assertEqual(denied.exception.code,403)
            with self.assertRaises(urllib.error.HTTPError): urllib.request.urlopen(url.rsplit('/',2)[0]+'/state')
        finally:
            server.shutdown();server.server_close();thread.join()
