"""Support uses isolated SQLite fixtures and mocked Gemini; never contacts Google."""
from datetime import datetime
from io import BytesIO
import json
import os
import threading
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from uuid import uuid4

import test_gate
import database
import support_chat
import support_ai


class SupportTests(unittest.TestCase):
    setUpClass = classmethod(test_gate.GateTests.setUpClass.__func__)
    tearDownClass = classmethod(test_gate.GateTests.tearDownClass.__func__)

    def setUp(self):
        test_gate.GateTests.setUp(self)
        self.customer_id = database.add_user('support-customer', 'Khách Kiểm Thử', 'test-only-password', 'user')
        self.other_id = database.add_user('support-other', 'Khách Khác', 'other-test-password', 'user')
        self.customer = self.actor(self.customer_id)
        self.other = self.actor(self.other_id)
        self.agent = self.actor(2)
        self.tokens = {}

    def actor(self, user_id):
        client = self.app.test_client()
        person = database.get_user_by_id(user_id)
        with client.session_transaction() as session:
            session.update(user_id=user_id, role=person['role'], username=person['username'])
        return client

    def post(self, client, path, data, **headers):
        if id(client) not in self.tokens:
            self.tokens[id(client)] = client.get('/api/support/bootstrap').json['csrf_token']
        return client.post('/api/support' + path, json=data,
                           headers={'X-Support-CSRF':self.tokens[id(client)], **headers})

    def thread(self, client=None, agent=2):
        response = self.post(client or self.customer, '/threads', {'agent_id':agent})
        self.assertEqual(response.status_code, 200)
        return response.json['thread']['id']

    def send(self, client, thread_id, text='Xin hỗ trợ vé tháng', client_id=None):
        return self.post(client, f'/threads/{thread_id}/messages', {'text':text,'client_id':client_id or str(uuid4())})

    def test_widget_in_layout_and_fresh_database_tables_are_idempotent(self):
        database.init_db()
        for client in (self.client, self.agent, self.customer):
            response = client.get('/')
            self.assertEqual(response.status_code, 200)
            self.assertIn('id="support-launcher"', response.text)
            self.assertIn('/static/js/support.js', response.text)
        self.assertEqual(self.thread(), self.thread())

    def test_authentication_csrf_origin_and_current_database_role(self):
        guest = self.app.test_client()
        self.assertEqual(guest.get('/api/support/bootstrap').status_code, 401)
        self.assertEqual(guest.post('/api/support/threads', json={}).status_code, 401)
        self.assertEqual(self.customer.post('/api/support/threads', json={'agent_id':2}).status_code, 403)
        self.assertEqual(self.post(self.customer, '/threads', {'agent_id':2}, Origin='https://another.test').status_code, 403)
        self.assertEqual(self.post(self.customer, '/threads', {'agent_id':2}, **{'X-Support-CSRF':'không hợp lệ'}).status_code, 403)
        with self.customer.session_transaction() as session:
            session['role'] = 'admin'
        self.assertEqual(self.customer.get('/api/support/bootstrap').json['me']['role'], 'user')
        database.toggle_user_status(self.customer_id)
        self.assertEqual(self.customer.get('/api/support/bootstrap').status_code, 401)

    def test_staff_directory_is_active_only_and_never_exposes_passwords_or_keys(self):
        response = self.customer.get('/api/support/bootstrap')
        self.assertEqual({person['id'] for person in response.json['staff']}, {1,2})
        self.assertNotIn('test-only-password', response.text)
        self.assertNotIn('123456', response.text)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertNotIn(2, [p['id'] for p in self.agent.get('/api/support/bootstrap').json['staff']])
        database.toggle_user_status(2)
        self.assertEqual([p['id'] for p in self.customer.get('/api/support/bootstrap').json['staff']], [1])
        for agent in (2, self.other_id, self.customer_id, True, '1.5', None):
            with self.subTest(agent=agent):
                self.assertIn(self.post(self.customer, '/threads', {'agent_id':agent}).status_code, (400,409))

    def test_messages_reply_unread_and_read_receipts_follow_each_participant(self):
        thread = self.thread()
        sent = self.send(self.customer, thread)
        self.assertEqual(sent.status_code, 201)
        self.assertEqual(self.agent.get('/api/support/bootstrap').json['unread_total'], 1)
        self.assertEqual(self.other.get('/api/support/bootstrap').json['threads'], [])
        messages = self.agent.get(f'/api/support/threads/{thread}/messages').json
        self.assertEqual(messages['messages'][0]['text'], 'Xin hỗ trợ vé tháng')
        self.assertFalse(messages['messages'][0]['mine'])
        self.post(self.agent, f'/threads/{thread}/read', {'last_id':sent.json['message']['id']})
        self.assertEqual(self.agent.get('/api/support/bootstrap').json['unread_total'], 0)
        reply = self.send(self.agent, thread, 'Bạn mở Khách hàng > Phương tiện & vé.')
        self.assertEqual(reply.status_code, 201)
        self.assertEqual(self.customer.get('/api/support/bootstrap').json['unread_total'], 1)
        self.post(self.customer, f'/threads/{thread}/read', {'last_id':reply.json['message']['id']})
        self.post(self.customer, f'/threads/{thread}/read', {'last_id':sent.json['message']['id']})
        self.assertEqual(self.customer.get('/api/support/bootstrap').json['unread_total'], 0)

    def test_other_users_and_unassigned_admin_cannot_access_or_modify_thread(self):
        thread = self.thread()
        self.send(self.customer, thread)
        for actor in (self.other, self.client):
            self.assertEqual(actor.get(f'/api/support/threads/{thread}/messages').status_code, 404)
            self.assertEqual(self.send(actor, thread, 'forbidden').status_code, 404)
            self.assertEqual(self.post(actor, f'/threads/{thread}/read', {'last_id':1}).status_code, 404)
        database.update_user(2, 'Nhân viên đã đổi vai trò', 'user')
        self.assertEqual(self.agent.get(f'/api/support/threads/{thread}/messages').status_code, 404)
        self.assertEqual(self.send(self.customer, thread).status_code, 409)

    def test_sending_twice_with_same_nonce_does_not_duplicate_and_validates_text(self):
        thread, nonce = self.thread(), str(uuid4())
        self.assertEqual(self.send(self.customer, thread, client_id=nonce).status_code, 201)
        self.assertEqual(self.send(self.customer, thread, client_id=nonce).status_code, 200)
        self.assertEqual(self.send(self.customer, thread, 'different', nonce).status_code, 409)
        self.assertEqual(len(self.customer.get(f'/api/support/threads/{thread}/messages').json['messages']), 1)
        for text in ('', ' ', 'x'*2001, 42, None):
            self.assertEqual(self.post(self.customer, f'/threads/{thread}/messages', {'text':text,'client_id':str(uuid4())}).status_code, 400)
        self.assertEqual(self.send(self.customer, thread, client_id='invalid').status_code, 400)

    def test_message_pagination_and_read_id_are_scoped_to_thread(self):
        thread = self.thread()
        with support_chat.connection(write=True) as conn:
            for i in range(60):
                conn.execute('INSERT INTO support_messages(thread_id,sender_id,body,client_id,created_at) VALUES (?,?,?,?,?)',
                             (thread,self.customer_id,str(i),str(uuid4()),datetime.now().isoformat()))
        recent = self.customer.get(f'/api/support/threads/{thread}/messages').json
        self.assertEqual([m['text'] for m in recent['messages']], [str(i) for i in range(10,60)])
        self.assertTrue(recent['has_older'])
        first_id = recent['messages'][0]['id']
        older = self.customer.get(f'/api/support/threads/{thread}/messages?before={first_id}').json
        self.assertEqual([m['text'] for m in older['messages']], [str(i) for i in range(10)])
        newer = self.customer.get(f'/api/support/threads/{thread}/messages?after={first_id}').json
        self.assertEqual(len(newer['messages']), 49)
        other_thread = self.thread(self.other)
        foreign = self.send(self.other, other_thread).json['message']['id']
        self.assertEqual(self.post(self.customer, f'/threads/{thread}/read', {'last_id':foreign}).status_code, 404)
        self.assertEqual(self.customer.get(f'/api/support/threads/{thread}/messages?after=0').status_code, 400)

    def test_missing_gemini_key_is_explicit_and_never_uses_a_fake_ai_reply(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY':'','GOOGLE_API_KEY':''}), patch.object(support_ai,'generate_reply') as call:
            self.assertFalse(self.customer.get('/api/support/ai/history').json['configured'])
            response = self.post(self.customer, '/ai/messages', {'text':'Xin chào','client_id':str(uuid4())})
        self.assertEqual(response.status_code, 503)
        call.assert_not_called()
        with support_chat.connection() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM support_ai_turns').fetchone()[0], 0)

    def test_gemini_history_is_private_and_idempotent_and_excludes_human_messages(self):
        thread = self.thread()
        self.send(self.customer, thread, 'Nội dung riêng chỉ gửi nhân viên')
        with patch.dict(os.environ, {'GEMINI_API_KEY':'test-key'}), patch.object(support_ai,'generate_reply',return_value='Mở Cabin > Xe vào.') as call:
            nonce = str(uuid4())
            data = {'text':'Hướng dẫn xe vào','client_id':nonce}
            self.assertEqual(self.post(self.customer, '/ai/messages', data).status_code, 200)
            self.assertEqual(self.post(self.customer, '/ai/messages', data).status_code, 200)
            call.assert_called_once_with([], 'Hướng dẫn xe vào')
            second = self.post(self.customer, '/ai/messages', {'text':'Còn xe ra?','client_id':str(uuid4())})
            self.assertEqual(second.status_code, 200)
            self.assertEqual(len(call.call_args.args[0]), 1)
            self.assertNotIn('Nội dung riêng', str(call.call_args))
            self.assertEqual(self.other.get('/api/support/ai/history').json['messages'], [])
            self.assertEqual(len(self.customer.get('/api/support/ai/history').json['messages']), 4)

    def test_gemini_errors_release_pending_and_requests_are_rate_limited(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY':'test-key'}), patch.object(support_ai,'generate_reply',side_effect=support_ai.AIError('Đang bận',429)):
            for _ in range(5):
                self.assertEqual(self.post(self.customer, '/ai/messages', {'text':'Xin chào','client_id':str(uuid4())}).status_code, 429)
            self.assertFalse(self.customer.get('/api/support/ai/history').json['pending'])
            response = self.post(self.customer, '/ai/messages', {'text':'Xin chào','client_id':str(uuid4())})
            self.assertEqual(response.status_code, 429)
            self.assertIn('một phút', response.json['error'])

    def test_only_one_pending_gemini_request_per_user_and_no_double_charge(self):
        actor = self.actor(self.customer_id)
        token = actor.get('/api/support/bootstrap').json['csrf_token']
        entered, release = threading.Event(), threading.Event()
        responses = []
        def reply(history, text):
            entered.set()
            release.wait(5)
            return 'Câu trả lời thử nghiệm'
        def first():
            responses.append(actor.post('/api/support/ai/messages', json={'text':'Câu đầu','client_id':str(uuid4())}, headers={'X-Support-CSRF':token}))
        with patch.dict(os.environ, {'GEMINI_API_KEY':'test-key'}), patch.object(support_ai,'generate_reply',side_effect=reply) as call:
            worker = threading.Thread(target=first)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                blocked = self.post(self.customer, '/ai/messages', {'text':'Câu thứ hai','client_id':str(uuid4())})
                self.assertEqual(blocked.status_code, 409)
            finally:
                release.set(); worker.join(5)
            self.assertEqual(responses[0].status_code, 200)
            self.assertEqual(call.call_count, 1)

    def test_provider_payload_uses_fixed_host_header_key_and_filters_thoughts(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({'candidates':[{'content':{'parts':[{'text':'hidden','thought':True},{'text':'Câu trả lời'}]}}]}).encode()
        opener = MagicMock(); opener.open.return_value = response
        with patch.dict(os.environ, {'GEMINI_API_KEY':'private-api-key','GEMINI_MODEL':'gemini-3.8-flash'}), patch.object(support_ai,'build_opener',return_value=opener):
            answer = support_ai.generate_reply([{'user_text':'Câu trước','answer':'Trả lời trước'}], 'Câu hiện tại')
        self.assertEqual(answer, 'Câu trả lời')
        request = opener.open.call_args.args[0]
        self.assertTrue(request.full_url.startswith('https://generativelanguage.googleapis.com/v1beta/models/'))
        self.assertNotIn('private-api-key', request.full_url)
        self.assertEqual(dict((k.lower(),v) for k,v in request.header_items())['x-goog-api-key'], 'private-api-key')
        payload = json.loads(request.data)
        self.assertEqual([m['role'] for m in payload['contents']], ['user','model','user'])
        self.assertIn('systemInstruction', payload)
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 60)

    def test_provider_failure_messages_never_return_secret_or_untrusted_error_body(self):
        for error in (HTTPError('https://example.test',403,'private-api-key',{},BytesIO(b'private-api-key')), URLError('private-api-key'), TimeoutError('private-api-key')):
            with self.subTest(error=type(error).__name__), patch.dict(os.environ, {'GEMINI_API_KEY':'private-api-key'}), patch.object(support_ai,'build_opener') as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaises(support_ai.AIError) as raised:
                    support_ai.generate_reply([], 'Xin chào')
                self.assertNotIn('private-api-key', str(raised.exception))

    def test_message_rate_limit_does_not_block_retrieving_a_previously_sent_nonce(self):
        thread = self.thread()
        nonce = str(uuid4())
        first = self.send(self.customer, thread, client_id=nonce)
        with support_chat.connection(write=True) as conn:
            for _ in range(29):
                conn.execute('INSERT INTO support_messages(thread_id,sender_id,body,client_id,created_at) VALUES (?,?,?,?,?)',
                             (thread,self.customer_id,'test',str(uuid4()),datetime.now().isoformat()))
        self.assertEqual(self.send(self.customer, thread, 'Thêm tin').status_code, 429)
        retry = self.send(self.customer, thread, client_id=nonce)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json['message']['id'], first.json['message']['id'])

    def test_expired_ai_reservations_and_unexpected_failures_do_not_lock_future_questions(self):
        with support_chat.connection(write=True) as conn:
            conn.execute("INSERT INTO support_ai_turns(user_id,client_id,user_text,state,created_at) VALUES (?,?,?,'pending',?)",
                         (self.customer_id,str(uuid4()),'Câu cũ','2020-01-01T00:00:00'))
        with patch.dict(os.environ, {'GEMINI_API_KEY':'test-key'}), patch.object(support_ai,'generate_reply',side_effect=RuntimeError('private-api-key')):
            response = self.post(self.customer, '/ai/messages', {'text':'Câu mới','client_id':str(uuid4())})
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('private-api-key', response.text)
            self.assertFalse(self.customer.get('/api/support/ai/history').json['pending'])
        with patch.dict(os.environ, {'GEMINI_API_KEY':'test-key'}), patch.object(support_ai,'generate_reply',return_value='Đã hoạt động'):
            response = self.post(self.customer, '/ai/messages', {'text':'Thử lại','client_id':str(uuid4())})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['messages'][-1]['text'], 'Đã hoạt động')

    def test_invalid_or_oversized_api_bodies_and_large_ids_return_json_errors(self):
        token = self.customer.get('/api/support/bootstrap').json['csrf_token']
        headers = {'X-Support-CSRF':token}
        response = self.customer.post('/api/support/threads', data='invalid', content_type='application/json', headers=headers)
        self.assertEqual(response.status_code, 400)
        response = self.customer.post('/api/support/threads', data='x'*17000, content_type='application/json', headers=headers)
        self.assertEqual(response.status_code, 413)
        self.assertIn('error', response.json)
        self.assertEqual(self.customer.get('/api/support/threads/' + '9'*30 + '/messages').status_code, 400)
        with self.customer.session_transaction() as session:
            session['user_id'] = {'invalid':'identity'}
        self.assertEqual(self.customer.get('/api/support/bootstrap').status_code, 401)

    def test_blocked_or_empty_gemini_answers_are_not_saved_as_successful_replies(self):
        for data, status in (({'promptFeedback':{'blockReason':'SAFETY'}},422), ({'candidates':[]},503), ([],503)):
            response = MagicMock(); response.__enter__.return_value = response
            response.read.return_value = json.dumps(data).encode()
            opener = MagicMock(); opener.open.return_value = response
            with self.subTest(data=data), patch.dict(os.environ, {'GEMINI_API_KEY':'test-key'}), patch.object(support_ai,'build_opener',return_value=opener):
                with self.assertRaises(support_ai.AIError) as raised:
                    support_ai.generate_reply([], 'Xin chào')
                self.assertEqual(raised.exception.status, status)


if __name__ == '__main__':
    unittest.main()
