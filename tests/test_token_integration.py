import copy
import io
import json
import os
import unittest
from unittest.mock import patch

from relaylens.transport import Client, extract
from relaylens.token_counter import official_input_count, control_prompts
from relaylens.privacy import private_report


class TokenIntegrationTests(unittest.TestCase):
    def test_wire_capture_timestamp_id_and_count_without_extra_generation(self):
        client = Client('https://relay.example/v1','dummy',counter_model='gpt-6.1-sol')
        response = {'transport_state':'ok','request_id':'request-123','data':{'status':'completed','output_text':'OK',
                    'usage':{'input_tokens':12,'output_tokens':2}}}
        with patch.object(client,'request',return_value=response) as request:
            result = client.call('relay-alias','hello',stream=True)
        self.assertEqual(request.call_count,1)
        observed,_,_ = extract(result,'responses')
        self.assertIn('+00:00',observed['started_at_utc'])
        self.assertEqual(observed['request_id'],'request-123')
        self.assertEqual(observed['token_measurement']['model'],'gpt-6.1-sol')
        self.assertNotIn('hello',json.dumps(observed['token_measurement']))

    def test_chat_requests_terminal_stream_usage(self):
        client = Client('https://relay.example','dummy',api='chat')
        with patch.object(client,'request',return_value={'data':{}}) as request:
            client.call('gpt-test','hello',stream=True)
        self.assertEqual(request.call_args.args[1]['stream_options'],{'include_usage':True})

    def test_legacy_chat_can_keep_original_wire_shape(self):
        client=Client('https://relay.example','dummy',api='chat',stream_usage=False)
        with patch.object(client,'request',return_value={'data':{}}) as request:
            client.call('gpt-test','hello',stream=True)
        self.assertNotIn('stream_options',request.call_args.args[1])

    def test_direct_counter_never_sends_official_key_to_relay(self):
        captured = []
        class Opener:
            def open(self,req,timeout):
                captured.append(req)
                return io.BytesIO(b'{"input_tokens":42}')
        fallback={'method':'character_estimate','exact':False}
        with patch.dict(os.environ,{'COUNTER_TEST_SECRET':'dummy-official'}):
            result = official_input_count({'model':'relay-alias','input':'test','stream':True},'responses',
                                          'gpt-6.1-sol','COUNTER_TEST_SECRET',Opener(),1,fallback)
        self.assertEqual(result['input_tokens'],42)
        self.assertEqual(captured[0].full_url,'https://api.openai.com/v1/responses/input_tokens')
        self.assertEqual(json.loads(captured[0].data)['model'],'gpt-6.1-sol')
        self.assertNotIn('dummy-official',json.dumps(result))
        self.assertEqual(fallback,{'method':'character_estimate','exact':False})

    def test_official_counter_error_and_chat_do_not_become_exact(self):
        class Opener:
            def open(self,*args,**kwargs): raise ValueError('echoed dummy-official')
        with patch.dict(os.environ,{'COUNTER_TEST_SECRET':'dummy-official'}):
            for api in ('responses','chat'):
                result = official_input_count({},api,'gpt-6.1-sol','COUNTER_TEST_SECRET',Opener(),1,{'exact':False})
                self.assertFalse(result['exact'])
                self.assertNotIn('dummy-official',json.dumps(result))

    def test_controls_are_reproducible_and_have_three_lengths(self):
        controls=list(control_prompts(42,6))
        self.assertEqual(controls,list(control_prompts(42,6)))
        self.assertEqual(len({len(x) for x in controls}),3)
        self.assertEqual(list(control_prompts(42,0)),[])

    def test_public_export_excludes_billing_ids_text_and_account_alias(self):
        source={'cases':[],'billing':{'state':'matched','matched':2,'coverage':1.0,
            'rows':[{'request_id':'private-id','model':'private-alias'}],
            'warnings':['Account private-name'],'ocr_text':'private text'},'billing_import':{'records':[{'user':'private-name'}]}}
        original=copy.deepcopy(source)
        exported=private_report(source)
        self.assertNotIn('private-',json.dumps(exported))
        self.assertNotIn('private text',json.dumps(exported))
        self.assertEqual(exported['billing']['matched'],2)
        self.assertEqual(source,original)
