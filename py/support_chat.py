"""Authenticated support inbox and private AI conversations."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import hmac
import secrets
import sqlite3
from uuid import UUID

from flask import Blueprint, g, jsonify, request, session

import database
import support_config
import support_ai
import support_knowledge


STAFF_ROLES = ('admin', 'manager')
ROLE_LABELS = {'admin': 'Quản trị viên', 'manager': 'Nhân viên', 'user': 'Khách hàng'}


class SupportError(Exception):
    def __init__(self, message, status=400, code=None):
        super().__init__(message)
        self.status = status
        self.code = code


@contextmanager
def connection(write=False):
    conn = database.get_connection()
    try:
        if write:
            conn.execute('BEGIN IMMEDIATE')
        yield conn
        if write:
            conn.commit()
    except Exception:
        if write:
            conn.rollback()
        raise
    finally:
        conn.close()


def csrf_token():
    if not session.get('support_csrf'):
        session['support_csrf'] = secrets.token_urlsafe(32)
    return session['support_csrf']


def json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise SupportError('Dữ liệu gửi chưa hợp lệ.')
    return body


def positive_id(value):
    if isinstance(value, bool):
        raise SupportError('Mã không hợp lệ.')
    try:
        parsed = int(str(value))
        if parsed < 1 or parsed > 9223372036854775807:
            raise ValueError
        return parsed
    except (ValueError, TypeError):
        raise SupportError('Mã không hợp lệ.') from None


def message_body(data):
    text = data.get('text')
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise SupportError('Tin nhắn phải có từ 1 đến 2.000 ký tự.')
    try:
        client_id = str(UUID(data.get('client_id', '')))
    except (ValueError, TypeError, AttributeError):
        raise SupportError('Mã gửi tin không hợp lệ. Vui lòng tải lại trang.') from None
    return text.strip(), client_id


def get_thread(conn, thread_id, actor):
    thread_id = positive_id(thread_id)
    thread = conn.execute(
        "SELECT t.*,o.fullname AS owner_name,o.status AS owner_status,o.role AS owner_role,"
        "a.fullname AS agent_name,a.status AS agent_status,a.role AS agent_role "
        "FROM support_threads t LEFT JOIN users o ON o.id=t.owner_id "
        "LEFT JOIN users a ON a.id=t.agent_id WHERE t.id=?", (thread_id,)).fetchone()
    if thread is None or not (thread['owner_id'] == actor['id'] or
                              (thread['agent_id'] == actor['id'] and actor['role'] in STAFF_ROLES)):
        raise SupportError('Không tìm thấy cuộc trò chuyện.', 404)
    return thread


def thread_data(thread, actor):
    mine = thread['owner_id'] == actor['id']
    side = 'agent' if mine else 'owner'
    role = thread[side + '_role'] or 'user'
    can_send = (thread['owner_status'] == thread['agent_status'] == 'active'
                and thread['agent_role'] in STAFF_ROLES)
    return dict(id=thread['id'], name=thread[side + '_name'] or 'Tài khoản đã xóa',
                role=ROLE_LABELS.get(role, 'Khách hàng'), incoming=not mine,
                can_send=can_send, updated_at=thread['updated_at'])


def message_data(row, actor):
    return dict(id=row['id'], text=row['body'], mine=row['sender_id'] == actor['id'],
                sender=row['sender_name'] or 'Tài khoản đã xóa', created_at=row['created_at'],
                client_id=row['client_id'] if row['sender_id'] == actor['id'] else None)


def thread_list(conn, actor):
    rows = conn.execute(
        "SELECT t.*,o.fullname AS owner_name,o.status AS owner_status,o.role AS owner_role,"
        "a.fullname AS agent_name,a.status AS agent_status,a.role AS agent_role,"
        "(SELECT body FROM support_messages WHERE thread_id=t.id ORDER BY id DESC LIMIT 1) AS snippet,"
        "(SELECT COUNT(*) FROM support_messages m WHERE m.thread_id=t.id AND m.sender_id<>? "
        "AND m.id>CASE WHEN t.owner_id=? THEN t.owner_read_id ELSE t.agent_read_id END) AS unread "
        "FROM support_threads t LEFT JOIN users o ON o.id=t.owner_id LEFT JOIN users a ON a.id=t.agent_id "
        "WHERE t.owner_id=? OR (t.agent_id=? AND ?) ORDER BY t.updated_at DESC,t.id DESC",
        (actor['id'], actor['id'], actor['id'], actor['id'], actor['role'] in STAFF_ROLES)).fetchall()
    return [dict(thread_data(row, actor), snippet=(row['snippet'] or '')[:120], unread=row['unread']) for row in rows]


def expire_ai(conn):
    cutoff = (datetime.now() - timedelta(seconds=150)).isoformat()
    conn.execute("UPDATE support_ai_turns SET state='error',finished_at=? WHERE state='pending' AND created_at<?",
                 (datetime.now().isoformat(), cutoff))


def ai_history(conn, user_id):
    turns = conn.execute("SELECT id,client_id,user_text,answer,created_at,finished_at FROM support_ai_turns "
                         "WHERE user_id=? AND state='done' ORDER BY id DESC LIMIT 20", (user_id,)).fetchall()
    messages = []
    for turn in reversed(turns):
        messages.extend([dict(id=f"{turn['id']}-user", text=turn['user_text'], mine=True, client_id=turn['client_id'], created_at=turn['created_at']),
                         dict(id=f"{turn['id']}-ai", text=turn['answer'], mine=False, created_at=turn['finished_at'])])
    pending = conn.execute("SELECT 1 FROM support_ai_turns WHERE user_id=? AND state='pending'", (user_id,)).fetchone()
    return dict(messages=messages, pending=bool(pending), configured=support_ai.available(), ai=support_config.identity())


def register_support(app):
    bp = Blueprint('support', __name__, url_prefix='/api/support')

    @app.context_processor
    def support_context():
        return dict(support_csrf=csrf_token() if session.get('user_id') else '')

    @bp.before_request
    def authorize():
        actor_id = session.get('user_id')
        if not isinstance(actor_id, int) or isinstance(actor_id, bool) or not 0 < actor_id <= 9223372036854775807:
            raise SupportError('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.', 401)
        with connection() as conn:
            g.support_user = conn.execute('SELECT id,fullname,role,status FROM users WHERE id=?',
                                          (actor_id,)).fetchone()
        if g.support_user is None or g.support_user['status'] != 'active':
            raise SupportError('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.', 401)
        if request.method == 'POST':
            limit = 8 * 1024 * 1024 if request.path.endswith('/ai/knowledge/import') else 65536 if request.path.endswith('/ai/knowledge') else 16384
            if request.content_length is None or request.content_length > limit:
                raise SupportError('Dữ liệu gửi quá lớn.', 413)
            expected = session.get('support_csrf', '')
            supplied = request.headers.get('X-Support-CSRF', '')
            if not isinstance(expected, str) or not expected or not hmac.compare_digest(expected.encode('utf-8'), supplied.encode('utf-8')):
                raise SupportError('Phiên gửi tin đã thay đổi. Vui lòng tải lại trang.', 403)
            origin = request.headers.get('Origin')
            if origin and origin != request.host_url.rstrip('/'):
                raise SupportError('Yêu cầu gửi tin không hợp lệ.', 403)

    @bp.after_request
    def no_cache(response):
        response.headers['Cache-Control'] = 'no-store'
        return response

    @bp.errorhandler(SupportError)
    def support_error(error):
        result = dict(error=str(error))
        if error.code:
            result['code'] = error.code
        return jsonify(result), error.status

    @bp.errorhandler(sqlite3.OperationalError)
    def busy_database(error):
        return jsonify(error='Hộp thư đang bận. Vui lòng thử lại sau.'), 503

    @bp.errorhandler(support_knowledge.KnowledgeError)
    def knowledge_error(error):
        return jsonify(error=str(error)), 400

    @bp.get('/bootstrap')
    def bootstrap():
        actor = g.support_user
        with connection() as conn:
            staff = conn.execute("SELECT id,fullname,role FROM users WHERE status='active' "
                                  "AND role IN ('admin','manager') AND id<>? ORDER BY role,fullname,id", (actor['id'],)).fetchall()
            threads = thread_list(conn, actor)
        return jsonify(me=dict(id=actor['id'], name=actor['fullname'], role=actor['role']),
                       staff=[dict(id=p['id'], name=p['fullname'], role=ROLE_LABELS[p['role']]) for p in staff],
                       threads=threads, unread_total=sum(t['unread'] for t in threads),
                       ai_configured=support_ai.available(), ai=support_config.identity(), csrf_token=csrf_token())

    def require_admin():
        if g.support_user['role'] != 'admin':
            raise SupportError('Chỉ quản trị viên được cấu hình trợ lý AI.', 403)

    @bp.get('/ai/settings')
    def ai_settings():
        require_admin()
        return jsonify(support_config.public_settings())

    @bp.post('/ai/settings')
    def save_ai_settings():
        require_admin()
        data = json_body()
        try:
            if data.get('action') == 'save':
                result = support_config.save(data)
            else:
                raise SupportError('Thao tác cấu hình chưa hợp lệ.')
        except support_config.ConfigError as error:
            raise SupportError(str(error)) from None
        return jsonify(result)

    @bp.post('/ai/test')
    def test_ai_settings():
        require_admin()
        text = support_knowledge.clean_text(json_body().get('text'), 'Câu hỏi thử', 2000)
        return jsonify(support_knowledge.answer(text))

    @bp.get('/ai/knowledge')
    def ai_knowledge():
        require_admin()
        return jsonify(documents=support_knowledge.list_documents())

    @bp.post('/ai/knowledge')
    def save_ai_knowledge():
        require_admin()
        item_id = support_knowledge.save_document(json_body(), g.support_user['id'])
        return jsonify(id=item_id, settings=support_config.public_settings())

    @bp.post('/ai/knowledge/<int:item_id>/delete')
    def delete_ai_knowledge(item_id):
        require_admin()
        support_knowledge.delete_document(positive_id(item_id))
        return jsonify(settings=support_config.public_settings())

    @bp.post('/ai/train')
    def train_ai():
        require_admin()
        json_body()
        return jsonify(support_knowledge.train(g.support_user['id']))

    @bp.get('/ai/knowledge/export')
    def export_ai_knowledge():
        require_admin()
        documents = [{key: item[key] for key in ('title', 'questions', 'answer', 'enabled')}
                     for item in support_knowledge.list_documents()]
        response = jsonify(format='smart-parking-knowledge-v1', documents=documents)
        response.headers['Content-Disposition'] = 'attachment; filename="smart-parking-knowledge.json"'
        return response

    @bp.post('/ai/knowledge/import')
    def import_ai_knowledge():
        require_admin()
        count = support_knowledge.import_documents(json_body(), g.support_user['id'])
        return jsonify(imported=count, settings=support_config.public_settings())

    @bp.post('/threads')
    def start_thread():
        actor = g.support_user
        agent_id = positive_id(json_body().get('agent_id'))
        if agent_id == actor['id']:
            raise SupportError('Vui lòng chọn một người hỗ trợ khác.')
        with connection(write=True) as conn:
            agent = conn.execute("SELECT id FROM users WHERE id=? AND status='active' AND role IN ('admin','manager')", (agent_id,)).fetchone()
            if agent is None:
                raise SupportError('Người hỗ trợ hiện không sẵn sàng.', 409)
            now = datetime.now().isoformat()
            conn.execute('INSERT OR IGNORE INTO support_threads(owner_id,agent_id,created_at,updated_at) VALUES (?,?,?,?)',
                         (actor['id'], agent_id, now, now))
            thread_id = conn.execute('SELECT id FROM support_threads WHERE owner_id=? AND agent_id=?', (actor['id'], agent_id)).fetchone()['id']
            thread = thread_data(get_thread(conn, thread_id, actor), actor)
        return jsonify(thread=thread)

    @bp.get('/threads/<int:thread_id>/messages')
    def messages(thread_id):
        actor = g.support_user
        after, before = request.args.get('after'), request.args.get('before')
        if after and before:
            raise SupportError('Chỉ chọn một hướng tải tin nhắn.')
        with connection() as conn:
            thread = get_thread(conn, thread_id, actor)
            params, condition = [thread_id], ''
            if after:
                condition = ' AND m.id>?'
                params.append(positive_id(after))
            elif before:
                condition = ' AND m.id<?'
                params.append(positive_id(before))
            order = 'ASC' if after else 'DESC'
            rows = conn.execute('SELECT m.*,u.fullname AS sender_name FROM support_messages m LEFT JOIN users u ON u.id=m.sender_id '
                                'WHERE m.thread_id=?' + condition + ' ORDER BY m.id ' + order + ' LIMIT 51', params).fetchall()
            more = len(rows) > 50
            rows = rows[:50]
            if not after:
                rows.reverse()
        return jsonify(thread=thread_data(thread, actor), messages=[message_data(row, actor) for row in rows],
                       has_older=more if not after else False, has_more=more if after else False)

    @bp.post('/threads/<int:thread_id>/messages')
    def send_message(thread_id):
        actor = g.support_user
        text, client_id = message_body(json_body())
        with connection(write=True) as conn:
            thread = get_thread(conn, thread_id, actor)
            existing = conn.execute('SELECT m.*,u.fullname AS sender_name FROM support_messages m LEFT JOIN users u ON u.id=m.sender_id '
                                    'WHERE m.thread_id=? AND m.sender_id=? AND m.client_id=?', (thread_id, actor['id'], client_id)).fetchone()
            if existing:
                if existing['body'] != text:
                    raise SupportError('Mã gửi đã được sử dụng cho tin nhắn khác.', 409)
                return jsonify(message=message_data(existing, actor))
            if not thread_data(thread, actor)['can_send']:
                raise SupportError('Người nhận hiện không sẵn sàng. Lịch sử trò chuyện vẫn được giữ.', 409)
            now = datetime.now()
            count = conn.execute('SELECT COUNT(*) FROM support_messages WHERE sender_id=? AND created_at>?',
                                 (actor['id'], (now-timedelta(minutes=1)).isoformat())).fetchone()[0]
            if count >= 30:
                raise SupportError('Bạn gửi tin quá nhanh. Vui lòng chờ một chút.', 429)
            cursor = conn.execute('INSERT INTO support_messages(thread_id,sender_id,body,client_id,created_at) VALUES (?,?,?,?,?)',
                                  (thread_id, actor['id'], text, client_id, now.isoformat()))
            conn.execute('UPDATE support_threads SET updated_at=? WHERE id=?', (now.isoformat(), thread_id))
            row = conn.execute('SELECT m.*,u.fullname AS sender_name FROM support_messages m LEFT JOIN users u ON u.id=m.sender_id WHERE m.id=?', (cursor.lastrowid,)).fetchone()
            result = message_data(row, actor)
        return jsonify(message=result), 201

    @bp.post('/threads/<int:thread_id>/read')
    def read_thread(thread_id):
        actor = g.support_user
        message_id = positive_id(json_body().get('last_id'))
        with connection(write=True) as conn:
            thread = get_thread(conn, thread_id, actor)
            if conn.execute('SELECT 1 FROM support_messages WHERE id=? AND thread_id=?', (message_id, thread_id)).fetchone() is None:
                raise SupportError('Không tìm thấy tin nhắn.', 404)
            field = 'owner_read_id' if thread['owner_id'] == actor['id'] else 'agent_read_id'
            conn.execute(f'UPDATE support_threads SET {field}=MAX({field},?) WHERE id=?', (message_id, thread_id))
        return jsonify(ok=True)

    @bp.get('/ai/history')
    def history():
        with connection(write=True) as conn:
            expire_ai(conn)
            result = ai_history(conn, g.support_user['id'])
        return jsonify(result)

    @bp.post('/ai/messages')
    def ai_message():
        actor = g.support_user
        text, client_id = message_body(json_body())
        if not support_ai.available():
            raise SupportError('Trợ lý AI nội bộ đang tắt hoặc chưa được huấn luyện. Bạn có thể chat với đội ngũ hỗ trợ.', 503)
        with connection(write=True) as conn:
            expire_ai(conn)
            existing = conn.execute('SELECT * FROM support_ai_turns WHERE user_id=? AND client_id=?', (actor['id'], client_id)).fetchone()
            if existing:
                if existing['user_text'] != text:
                    raise SupportError('Mã gửi đã được sử dụng cho nội dung khác.', 409)
                if existing['state'] == 'done':
                    return jsonify(ai_history(conn, actor['id']))
                raise SupportError('Lần gửi này đang xử lý hoặc đã kết thúc. Vui lòng chờ rồi gửi lại.', 409)
            pending = conn.execute("SELECT COUNT(*),SUM(user_id=?) FROM support_ai_turns WHERE state='pending'", (actor['id'],)).fetchone()
            if pending[1]:
                raise SupportError('AI đang trả lời tin nhắn trước. Vui lòng chờ một chút.', 409)
            if pending[0] >= 4:
                raise SupportError('AI đang bận. Vui lòng thử lại sau.', 503)
            now = datetime.now()
            count = conn.execute('SELECT COUNT(*) FROM support_ai_turns WHERE user_id=? AND created_at>?',
                                 (actor['id'], (now-timedelta(minutes=1)).isoformat())).fetchone()[0]
            if count >= 5:
                raise SupportError('Bạn đã gửi nhiều câu hỏi liên tiếp. Vui lòng chờ một phút.', 429)
            cursor = conn.execute("INSERT INTO support_ai_turns(user_id,client_id,user_text,state,created_at) VALUES (?,?,?,'pending',?)",
                                  (actor['id'], client_id, text, now.isoformat()))
            turn_id = cursor.lastrowid
            previous = conn.execute("SELECT user_text,answer FROM support_ai_turns WHERE user_id=? AND state='done' ORDER BY id DESC LIMIT 8", (actor['id'],)).fetchall()
            context, size = [], 0
            for turn in previous:
                size += len(turn['user_text']) + len(turn['answer'])
                if size > 16000:
                    break
                context.append(dict(turn))
            context.reverse()
        try:
            answer = support_ai.generate_reply(context, text)
        except Exception as error:
            with connection(write=True) as conn:
                conn.execute("UPDATE support_ai_turns SET state='error',finished_at=? WHERE id=?", (datetime.now().isoformat(), turn_id))
            if isinstance(error, support_ai.AIError):
                raise SupportError(str(error), error.status, error.code) from None
            raise SupportError('AI chưa hoàn tất câu trả lời. Vui lòng thử lại sau.', 503) from None
        with connection(write=True) as conn:
            conn.execute("UPDATE support_ai_turns SET state='done',answer=?,finished_at=? WHERE id=?", (answer, datetime.now().isoformat(), turn_id))
            result = ai_history(conn, actor['id'])
        return jsonify(result)

    app.register_blueprint(bp)
