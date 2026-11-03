"""Provider protocols, legacy config migration and safe custom HTTPS endpoints."""
from io import BytesIO
import json
import os
import socket
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import ProxyHandler
from uuid import uuid4

import test_gate
import test_support_settings
import database
import support_ai
import support_config
from support_transport import PublicHTTPSConnection, PublicHTTPSHandler


class SupportProviderTests(unittest.TestCase):
    setUpClass = classmethod(test_gate.GateTests.setUpClass.__func__)
    tearDownClass = classmethod(test_gate.GateTests.tearDownClass.__func__)
    setUp = test_support_settings.SupportSettingsTests.setUp
    post = test_support_settings.SupportSettingsTests.post
    save = test_support_settings.SupportSettingsTests.save

    def provider_config(self, provider):
        preset = support_config.PROVIDERS[provider]
        return dict(provider=provider, model=preset['default_model'] or 'vendor/model-1:latest',
                    base_url=preset['base_url'] or 'https://api.example.com/v1', key=self.fake_key)

    def test_protocols_use_correct_paths_headers_system_and_history(self):
        history = [dict(user_text='Hỏi trước',answer='Trả lời trước')]
        for provider in support_config.PROVIDERS:
            with self.subTest(provider=provider):
                config = self.provider_config(provider)
                request = support_ai._request(config,history,'Câu mới')
                payload = json.loads(request.data)
                self.assertNotIn(self.fake_key,request.full_url)
                self.assertNotIn(self.fake_key,request.data.decode())
                if provider == 'gemini':
                    self.assertEqual(request.get_header('X-goog-api-key'),self.fake_key)
                    self.assertIn(':generateContent',request.full_url)
                    self.assertEqual([m['role'] for m in payload['contents']],['user','model','user'])
                elif provider == 'anthropic':
                    self.assertEqual(request.full_url,'https://api.anthropic.com/v1/messages')
                    self.assertEqual(request.get_header('Anthropic-version'),'2026-10-21')
                    self.assertEqual(payload['system'],support_ai.SYSTEM_INSTRUCTION)
                    self.assertEqual([m['role'] for m in payload['messages']],['user','assistant','user'])
                else:
                    self.assertTrue(request.full_url.endswith('/chat/completions'))
                    self.assertEqual([m['role'] for m in payload['messages']],['system','user','assistant','user'])
                    self.assertEqual(payload['messages'][0]['content'],support_ai.SYSTEM_INSTRUCTION)
                    self.assertIn('max_completion_tokens' if provider == 'openai' else 'max_tokens',payload)
                if provider != 'gemini':
                    self.assertEqual(request.get_header('Authorization'),'Bearer ' + self.fake_key)

    def test_parser_accepts_text_only_and_never_exposes_reasoning_or_tools(self):
        result = support_ai._answer({'content':[{'type':'thinking','thinking':'private'}, {'type':'text','text':'Hướng dẫn'}]},'anthropic')
        self.assertEqual(result,'Hướng dẫn')
        data = {'choices':[{'message':{'content':'Hướng dẫn','reasoning_content':'private'}}]}
        self.assertEqual(support_ai._answer(data,'deepseek'),'Hướng dẫn')
        self.assertEqual(support_ai._answer({'choices':[{'message':{'content':[{'type':'text','text':'Hello'},{'type':'tool_call','text':'private'}]}}]},'compatible'),'Hello')
        for provider,data in [('anthropic',{'stop_reason':'refusal'}), ('openai',{'choices':[{'message':{'refusal':'No'}}]}),
                              ('deepseek',{'choices':[{'finish_reason':'content_filter'}]})]:
            with self.assertRaises(support_ai.AIError) as error:
                support_ai._answer(data,provider)
            self.assertEqual(error.exception.status,422)

    def test_all_non_gemini_providers_work_through_authenticated_chat_endpoint(self):
        for provider in ('openai','anthropic','deepseek','compatible'):
            with self.subTest(provider=provider):
                config = self.provider_config(provider)
                self.assertEqual(self.save(provider=provider,model=config['model'],base_url=config['base_url']).status_code,200)
                output = {'content':[{'type':'text','text':'Trả lời thật từ bộ giả lập API'}]} if provider == 'anthropic' else {'choices':[{'message':{'content':'Trả lời thật từ bộ giả lập API'}}]}
                opener = MagicMock()
                opener.open.return_value.__enter__.return_value = BytesIO(json.dumps(output).encode())
                with patch.object(support_ai,'build_opener',return_value=opener) as builder:
                    response = self.post({'text':'Hướng dẫn xe vào','client_id':str(uuid4())},path='/ai/messages')
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json['messages'][-1]['text'],'Trả lời thật từ bộ giả lập API')
                self.assertEqual(response.json['ai']['provider'],provider)
                if provider == 'compatible':
                    handlers = builder.call_args.args
                    self.assertTrue(any(isinstance(h,PublicHTTPSHandler) for h in handlers))
                    self.assertTrue(any(isinstance(h,ProxyHandler) and not h.proxies for h in handlers))

    def test_provider_and_host_change_require_fresh_key_but_model_change_preserves_it(self):
        self.save()
        original = database.get_setting(support_config.SETTING_KEY)
        self.assertEqual(self.save(provider='openai',model='example-model',api_key='').status_code,400)
        self.assertEqual(database.get_setting(support_config.SETTING_KEY),original)
        self.assertEqual(self.save(provider='compatible',base_url='https://api.example.com/v1',model='model-one').status_code,200)
        self.assertEqual(self.save(provider='compatible',base_url='https://other.example.com/v1',model='model-one',api_key='').status_code,400)
        self.assertEqual(self.save(provider='compatible',base_url='https://api.example.com/v1',model='model-two',api_key='').status_code,200)
        self.assertEqual(support_ai.credentials(),self.fake_key)

    def test_legacy_gemini_config_is_read_without_losing_key_and_migrates_on_write(self):
        token = support_config._cipher(create=True).encrypt(self.fake_key.encode()).decode()
        database.set_setting(support_config.LEGACY_SETTING_KEY,json.dumps(dict(enabled=True,model='gemini-2.5-flash',api_key=token)))
        self.assertEqual(support_ai.credentials(),self.fake_key)
        self.assertEqual(support_config.public_settings()['provider'],'gemini')
        self.assertEqual(self.save(api_key='').status_code,200)
        self.assertIsNone(database.get_setting(support_config.LEGACY_SETTING_KEY))
        self.assertEqual(support_ai.credentials(),self.fake_key)
        self.post({'action':'disconnect'})
        with patch.dict(os.environ,{'GEMINI_API_KEY':'never-reenable'}):
            self.assertEqual(support_ai.credentials(),'')

    def test_custom_url_validation_rejects_private_or_credential_bearing_urls(self):
        rejected = ['http://api.example.com/v1','https://127.0.0.1/v1','https://[::1]/v1','https://10.0.0.2/v1',
                    'https://169.254.169.254/v1','https://localhost/v1','https://service.local/v1',
                    'https://user:pass@api.example.com/v1','https://api.example.com/v1?key=secret',
                    'https://api.example.com/v1#token','https://api.example.com:0/v1','https://api.example.com:65536/v1',
                    'https://api.example.com/%2e%2e/','https://api.example.com\\@127.0.0.1/v1','https://api.example.com/\nkey']
        for url in rejected:
            with self.subTest(url=url), self.assertRaises(support_config.ConfigError):
                support_config.validate_connection('compatible','vendor/model:tag',url)
        self.assertEqual(support_config.validate_connection('compatible','vendor/model:tag','https://API.EXAMPLE.COM/v1/chat/completions/'),'https://api.example.com/v1')
        with self.assertRaises(support_config.ConfigError):
            support_config.validate_connection('openai','example-model','https://other.example.com/v1')

    def test_private_or_mixed_dns_is_blocked_before_socket_connect(self):
        for addresses in ([('127.0.0.1',443)], [('1.1.1.1',443),('10.0.0.1',443)], [('169.254.169.254',443)]):
            resolved = [(socket.AF_INET,socket.SOCK_STREAM,6,'',address) for address in addresses]
            with patch('support_transport.socket.getaddrinfo',return_value=resolved), patch('support_transport.socket.socket') as sock:
                with self.assertRaises(OSError):
                    PublicHTTPSConnection('api.example.com',timeout=30).connect()
                sock.assert_not_called()

    def test_public_dns_address_is_pinned_while_tls_verifies_original_hostname(self):
        resolved = [(socket.AF_INET,socket.SOCK_STREAM,6,'',('1.1.1.1',443))]
        connection = PublicHTTPSConnection('api.example.com',timeout=30)
        context = MagicMock()
        connection._context = context
        with patch('support_transport.socket.getaddrinfo',return_value=resolved) as resolver, patch('support_transport.socket.socket') as sock:
            connection.connect()
        resolver.assert_called_once_with('api.example.com',443,type=socket.SOCK_STREAM)
        sock.return_value.connect.assert_called_once_with(('1.1.1.1',443))
        context.wrap_socket.assert_called_once_with(sock.return_value,server_hostname='api.example.com')

    def test_non_gemini_provider_errors_are_sanitized_and_no_redirect_is_followed(self):
        self.save(provider='openai',model='example-model')
        opener = MagicMock()
        opener.open.side_effect = HTTPError('https://api.openai.com/v1/chat/completions',401,'secret-provider-error',{},BytesIO(self.fake_key.encode()))
        with patch.object(support_ai,'build_opener',return_value=opener) as builder:
            response = self.post({},path='/ai/test')
        self.assertEqual(response.status_code,503)
        self.assertNotIn(self.fake_key,response.text)
        self.assertNotIn('secret-provider-error',response.text)
        self.assertTrue(any(isinstance(h,support_ai.NoRedirect) for h in builder.call_args.args))

    def test_generic_environment_supports_other_provider_and_long_keys_remain_encrypted(self):
        with patch.dict(os.environ,{'SUPPORT_AI_PROVIDER':'openai','SUPPORT_AI_MODEL':'example-model','OPENAI_API_KEY':self.fake_key}):
            self.assertEqual(support_config.load()['provider'],'openai')
            self.assertEqual(support_ai.credentials(),self.fake_key)
        long_key = 'sk-' + 'a'*600
        self.assertEqual(self.save(provider='openai',model='example-model',api_key=long_key).status_code,200)
        self.assertNotIn(long_key,database.get_setting(support_config.SETTING_KEY))
        self.assertEqual(support_ai.credentials(),long_key)


if __name__ == '__main__':
    unittest.main()
