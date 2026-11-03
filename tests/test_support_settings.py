"""Admin-only Gemini configuration, encryption and immediate provider integration."""
from pathlib import Path
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_gate
import database
import support_config
import support_ai


class SupportSettingsTests(unittest.TestCase):
    setUpClass = classmethod(test_gate.GateTests.setUpClass.__func__)
    tearDownClass = classmethod(test_gate.GateTests.tearDownClass.__func__)

    def setUp(self):
        test_gate.GateTests.setUp(self)
        self.env = patch.dict(os.environ, {'GEMINI_API_KEY':'', 'GOOGLE_API_KEY':'', 'GEMINI_MODEL':'',
            'SUPPORT_AI_PROVIDER':'', 'SUPPORT_AI_API_KEY':'', 'SUPPORT_AI_MODEL':'', 'SUPPORT_AI_BASE_URL':'',
            'OPENAI_API_KEY':'', 'ANTHROPIC_API_KEY':'', 'DEEPSEEK_API_KEY':''})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.fake_key = 'test-only-gemini-key-' + 'a'*24
        self.token = self.client.get('/api/support/bootstrap').json['csrf_token']

    def post(self, data, client=None, path='/ai/settings'):
        client = client or self.client
        token = client.get('/api/support/bootstrap').json['csrf_token']
        return client.post('/api/support' + path, json=data, headers={'X-Support-CSRF':token})

    def actor(self, user_id, role):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=user_id, role=role, fullname='Người kiểm thử')
        return client

    def save(self, **changes):
        data = dict(action='save', api_key=self.fake_key, model=support_config.DEFAULT_MODEL)
        data.update(changes)
        return self.post(data)

    def test_only_active_database_admin_can_see_and_change_configuration(self):
        user_id = database.add_user('settings-user', 'Khách kiểm thử', 'fixture-pass', 'user')
        for actor in (self.actor(2,'manager'), self.actor(user_id,'admin')):
            self.assertEqual(actor.get('/api/support/ai/settings').status_code, 403)
            self.assertEqual(self.post(dict(action='save',api_key=self.fake_key,model=support_config.DEFAULT_MODEL), actor).status_code, 403)
            self.assertEqual(self.post({},actor,path='/ai/test').status_code, 403)
            self.assertNotIn('id="ai-settings"', actor.get('/settings').text)
            self.assertEqual(actor.get('/settings?section=ai').status_code,403)
        self.assertNotIn('id="ai-settings"', self.client.get('/settings').text)
        ai_page = self.client.get('/settings?section=ai')
        self.assertIn('id="ai-settings"', ai_page.text)
        self.assertNotIn('name="entry_mode"', ai_page.text)
        self.assertIn('name="entry_mode"', self.client.get('/settings').text)
        guest = self.app.test_client()
        self.assertEqual(guest.get('/api/support/ai/settings').status_code, 401)
        database.toggle_user_status(1)
        self.assertEqual(self.client.get('/api/support/ai/settings').status_code, 401)

    def test_csrf_and_origin_are_required_and_never_echo_key(self):
        data = dict(action='save',api_key=self.fake_key,model=support_config.DEFAULT_MODEL)
        self.assertEqual(self.client.post('/api/support/ai/settings',json=data).status_code, 403)
        response = self.client.post('/api/support/ai/settings',json=data,
                                    headers={'X-Support-CSRF':self.token,'Origin':'https://another.test'})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn(self.fake_key,response.text)
        self.assertIsNone(database.get_setting(support_config.SETTING_KEY))

    def test_key_is_encrypted_persisted_and_never_returned_to_browser(self):
        response = self.save()
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json['configured'])
        self.assertEqual(response.json['source'],'settings')
        saved = database.get_setting(support_config.SETTING_KEY)
        self.assertNotIn(self.fake_key,saved)
        self.assertIn('gAAAA',saved)
        self.assertEqual(support_ai.credentials(),self.fake_key)
        # A new client/process read uses persisted data, with no in-memory key cache.
        for url in ('/settings','/api/support/ai/settings','/api/support/bootstrap','/api/support/ai/history'):
            response = self.client.get(url)
            self.assertNotIn(self.fake_key,response.text)
            self.assertNotIn('gAAAA',response.text)
        key_file = Path(database.DB_PATH).parent / 'secrets' / 'gemini.key'
        self.assertTrue(key_file.exists())
        self.assertNotIn(self.fake_key,key_file.read_text())
        self.assertEqual(self.client.get('/api/support/ai/settings').headers['Cache-Control'],'no-store')

    def test_empty_key_preserves_current_key_and_replacement_applies_immediately(self):
        self.save()
        self.assertEqual(self.save(api_key='',model='gemini-2.5-flash').status_code,200)
        self.assertEqual(support_config.load()['model'],'gemini-2.5-flash')
        self.assertEqual(support_ai.credentials(),self.fake_key)
        next_key = 'test-only-replacement-' + 'b'*24
        self.assertEqual(self.save(api_key=next_key).status_code,200)
        self.assertEqual(support_ai.credentials(),next_key)
        self.assertTrue(self.client.get('/api/support/bootstrap').json['ai_configured'])

    def test_environment_fallback_and_disconnect_do_not_silently_reenable_ai(self):
        with patch.dict(os.environ,{'GEMINI_API_KEY':self.fake_key,'GEMINI_MODEL':'gemini-2.5-flash'}):
            self.assertEqual(support_config.public_settings()['source'],'environment')
            self.assertEqual(self.save(api_key='',model='gemini-2.5-flash').status_code,200)
            self.assertEqual(support_config.public_settings()['source'],'settings')
            self.assertEqual(self.post({'action':'disconnect'}).status_code,200)
            self.assertEqual(support_config.public_settings()['source'],'disabled')
            self.assertEqual(support_ai.credentials(),'')
            self.assertFalse(self.client.get('/api/support/ai/history').json['configured'])
            self.assertEqual(self.save(api_key='').status_code,400)
            self.assertEqual(self.save().status_code,200)
            self.assertEqual(support_ai.credentials(),self.fake_key)

    def test_invalid_input_never_overwrites_working_configuration(self):
        self.assertEqual(self.save(api_key='').status_code,400)
        self.save()
        saved = database.get_setting(support_config.SETTING_KEY)
        for changes in ({'model':''},{'model':'https://evil.test/key'}, {'model':'gemini-a'*30},
                        {'api_key':'short'}, {'api_key':'a'*4097}, {'api_key':'test key\n'*8},
                        {'model':None}, {'api_key':42}):
            response = self.save(**changes)
            self.assertEqual(response.status_code,400)
            self.assertNotIn(self.fake_key,response.text)
            self.assertEqual(database.get_setting(support_config.SETTING_KEY),saved)
        self.assertEqual(self.post({'action':'unknown'}).status_code,400)

    def test_corrupted_configuration_fails_closed_and_can_be_disconnected_or_replaced(self):
        for raw in ('not-json','[]','{}','{"enabled":true,"model":"gemini-2.5-flash","api_key":"bad"}'):
            database.set_setting(support_config.SETTING_KEY,raw)
            with patch.dict(os.environ,{'GEMINI_API_KEY':self.fake_key}):
                settings = self.client.get('/api/support/ai/settings').json
                self.assertFalse(settings['configured'])
                self.assertTrue(settings['error'])
                self.assertEqual(support_ai.credentials(),'')
            self.assertEqual(self.post({'action':'disconnect'}).status_code,200)
            self.assertEqual(self.save().status_code,200)

    def test_encryption_failure_preserves_existing_record(self):
        self.save()
        saved = database.get_setting(support_config.SETTING_KEY)
        with patch.object(support_config,'_cipher',side_effect=support_config.ConfigError('Máy chủ chưa đọc được khóa mã hóa.')):
            self.assertEqual(self.save().status_code,400)
        self.assertEqual(database.get_setting(support_config.SETTING_KEY),saved)

    def test_connection_test_uses_saved_config_and_writes_no_chat_history(self):
        self.assertEqual(self.post({},path='/ai/test').status_code,400)
        self.save()
        with patch.object(support_ai,'generate_reply',return_value=self.fake_key) as provider:
            response = self.post({},path='/ai/test')
        self.assertEqual(response.status_code,200)
        self.assertNotIn(self.fake_key,response.text)
        provider.assert_called_once()
        self.assertEqual(self.client.get('/api/support/ai/history').json['messages'],[])
        with patch.object(support_ai,'generate_reply',side_effect=support_ai.AIError('Hết hạn mức',429)):
            self.assertEqual(self.post({},path='/ai/test').status_code,429)
        with patch.object(support_ai,'generate_reply',side_effect=RuntimeError(self.fake_key)):
            response = self.post({},path='/ai/test')
            self.assertEqual(response.status_code,503)
            self.assertNotIn(self.fake_key,response.text)

    def test_saved_key_and_model_are_used_for_real_gemini_request_builder(self):
        self.save(model='gemini-2.5-flash')
        from io import BytesIO
        from unittest.mock import MagicMock
        import json
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = BytesIO(json.dumps(
            {'candidates':[{'content':{'parts':[{'text':'OK'}]}}]}).encode())
        with patch.object(support_ai,'build_opener',return_value=opener), patch.dict(os.environ,{'GEMINI_API_KEY':'unused-env-key'}):
            response = self.post({'text':'Hướng dẫn xe vào','client_id':str(uuid4())},path='/ai/messages')
        self.assertEqual(response.status_code,200)
        request = opener.open.call_args.args[0]
        self.assertIn('/models/gemini-2.5-flash:generateContent',request.full_url)
        self.assertEqual(request.get_header('X-goog-api-key'),self.fake_key)


if __name__ == '__main__':
    unittest.main()
