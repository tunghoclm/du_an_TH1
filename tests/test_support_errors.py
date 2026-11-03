"""Useful AI diagnostics, short connection probes, and credential redaction."""
from io import BytesIO
import json
import socket
import ssl
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import test_gate
import test_support_settings
import support_ai
import support_config


class SupportErrorTests(unittest.TestCase):
    setUpClass = classmethod(test_gate.GateTests.setUpClass.__func__)
    tearDownClass = classmethod(test_gate.GateTests.tearDownClass.__func__)
    setUp = test_support_settings.SupportSettingsTests.setUp
    post = test_support_settings.SupportSettingsTests.post
    save = test_support_settings.SupportSettingsTests.save

    def test_connection_probe_is_small_and_does_not_include_parking_system_context(self):
        self.save()
        request = support_ai._request(support_config.load(),[],'Reply OK.',connection_test=True)
        payload = json.loads(request.data)
        self.assertEqual(payload['generationConfig']['maxOutputTokens'],256)
        self.assertEqual(payload['systemInstruction']['parts'][0]['text'],'Reply only OK.')
        self.assertNotIn('Smart Parking',request.data.decode())
        self.assertEqual(request.get_header('X-goog-api-key'),self.fake_key)

    def test_connection_endpoint_explicitly_requests_probe_mode(self):
        self.save()
        with patch.object(support_ai,'generate_reply',return_value='OK') as call:
            response = self.post({},path='/ai/test')
        self.assertEqual(response.status_code,200)
        call.assert_called_once_with([],'Reply OK.',connection_test=True)

    def test_timeout_is_reported_as_timeout_with_no_claim_that_the_key_is_wrong(self):
        self.save()
        for error in (TimeoutError(self.fake_key),URLError(TimeoutError(self.fake_key))):
            opener = MagicMock()
            opener.open.side_effect = error
            with patch.object(support_ai,'build_opener',return_value=opener):
                response = self.post({},path='/ai/test')
            self.assertEqual(response.status_code,504)
            self.assertEqual(response.json['code'],'provider_timeout')
            self.assertIn('60',response.json['error'])
            self.assertNotIn(self.fake_key,response.text)
            self.assertEqual(opener.open.call_args.kwargs['timeout'],60)

    def test_dns_tls_and_other_network_errors_have_distinct_safe_categories(self):
        for error,code in ((URLError(socket.gaierror(-2,self.fake_key)),'provider_dns'),
                           (URLError(ssl.SSLCertVerificationError(self.fake_key)),'provider_tls'),
                           (ConnectionResetError(self.fake_key),'provider_network')):
            result = support_ai._network_error(error)
            self.assertEqual(result.code,code)
            self.assertNotIn(self.fake_key,str(result))

    def test_provider_http_errors_are_specific_without_returning_untrusted_body(self):
        cases = [(400,{'details':[{'reason':'API_KEY_INVALID'}]},'key_invalid'),
                 (401,{},'key_invalid'),(403,{},'provider_permission'),(404,{},'model_not_found'),
                 (402,{},'provider_billing'),(429,{},'provider_quota'),(504,{},'provider_timeout'),
                 (400,{},'provider_request'),(503,{},'provider_unavailable')]
        for http,detail,code in cases:
            with self.subTest(http=http,code=code):
                detail['message'] = self.fake_key
                error = HTTPError('https://example.test',http,self.fake_key,{},BytesIO(json.dumps({'error':detail}).encode()))
                result = support_ai._http_error(error,'Google Gemini')
                self.assertEqual(result.code,code)
                self.assertNotIn(self.fake_key,str(result))

    def test_google_blocked_key_message_is_classified_without_echoing_key(self):
        detail = {'error':{'message':'Your API key was reported as leaked: ' + self.fake_key}}
        error = HTTPError('https://example.test',403,'denied',{},BytesIO(json.dumps(detail).encode()))
        result = support_ai._http_error(error,'Google Gemini')
        self.assertEqual(result.code,'key_blocked')
        self.assertNotIn(self.fake_key,str(result))

    def test_google_authorization_key_format_is_accepted_and_kept_server_side(self):
        auth_key = 'AQ.' + 'a'*50
        self.assertEqual(self.save(api_key=auth_key).status_code,200)
        self.assertEqual(support_ai.credentials(),auth_key)
        self.assertNotIn(auth_key,self.client.get('/api/support/ai/settings').text)


if __name__ == '__main__':
    unittest.main()
