"""Admin-curated local corpus and atomic, versioned training stored in SQLite."""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path

import database
import support_model
import support_live
import support_pricing

DEFAULT_FALLBACK = ('Tôi chưa có đủ kiến thức để trả lời câu hỏi này. Bạn hãy nêu rõ chức năng cần hỗ trợ '
                    '(xe vào/ra, vé tháng, hóa đơn, bảng giá) hoặc chọn Chat với đội ngũ. '
                    'Tôi có thể kiểm tra số chỗ trống hiện tại và hướng dẫn sử dụng; không thay đổi dữ liệu vận hành.')
MAX_DOCUMENTS = 300


class KnowledgeError(ValueError):
    pass


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


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def clean_text(value, label, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or '\x00' in value:
        raise KnowledgeError(f'{label} phải có từ 1 đến {maximum:,} ký tự.')
    return value.strip()


def validate(data):
    if not isinstance(data, dict):
        raise KnowledgeError('Mục kiến thức chưa hợp lệ.')
    title = clean_text(data.get('title'), 'Tiêu đề', 120)
    answer = clean_text(data.get('answer'), 'Câu trả lời', 6000)
    questions = data.get('questions')
    if not isinstance(questions, list) or not 1 <= len(questions) <= 12:
        raise KnowledgeError('Mỗi mục cần từ 1 đến 12 cách hỏi.')
    questions = [clean_text(item, 'Cách hỏi', 200) for item in questions]
    if not isinstance(data.get('enabled', True), bool):
        raise KnowledgeError('Trạng thái mục kiến thức chưa hợp lệ.')
    return dict(title=title, questions=questions, answer=answer, enabled=data.get('enabled', True))


def document(row):
    return dict(id=row['id'], title=row['title'], questions=json.loads(row['questions']),
                answer=row['answer'], enabled=bool(row['enabled']), updated_at=row['updated_at'])


def _train(conn, actor_id):
    state = conn.execute('SELECT * FROM support_ai_state WHERE id=1').fetchone()
    documents = [document(row) for row in conn.execute('SELECT * FROM support_ai_knowledge WHERE enabled=1 ORDER BY id')]
    try:
        model = support_model.train(documents)
    except ValueError as error:
        raise KnowledgeError(str(error)) from None
    payload = encoded(model)
    cursor = conn.execute('INSERT INTO support_ai_models(trained_at,trained_by,revision,document_count,sample_count,fingerprint,payload) '
                          'VALUES (?,?,?,?,?,?,?)', (datetime.now().isoformat(), actor_id, state['revision'], len(documents),
                          len(model['samples']), hashlib.sha256(payload.encode('utf-8')).hexdigest(), payload))
    conn.execute('UPDATE support_ai_state SET active_model=? WHERE id=1', (cursor.lastrowid,))
    # Retain the latest five snapshots without unbounded database growth.
    conn.execute('DELETE FROM support_ai_models WHERE id NOT IN (SELECT id FROM support_ai_models ORDER BY id DESC LIMIT 5)')


def initialize():
    with connection(write=True) as conn:
        # Retire old credentials without decrypting them or reading provider environment variables.
        conn.execute("DELETE FROM settings WHERE key IN ('support:ai','support:gemini')")
        if conn.execute('SELECT 1 FROM support_ai_state WHERE id=1').fetchone():
            return
        conn.execute('INSERT INTO support_ai_state(id,name,enabled,threshold,fallback) VALUES (1,?,1,0.55,?)',
                     ('Smart Parking AI nội bộ', DEFAULT_FALLBACK))
        path = Path(__file__).resolve().parents[1] / 'assets' / 'support_knowledge.json'
        for item in json.loads(path.read_text(encoding='utf-8')):
            _insert(conn, validate(item), None)
        _train(conn, None)


def _insert(conn, item, actor_id):
    return conn.execute('INSERT INTO support_ai_knowledge(title,questions,answer,enabled,updated_at,updated_by) VALUES (?,?,?,?,?,?)',
                        (item['title'], encoded(item['questions']), item['answer'], int(item['enabled']),
                         datetime.now().isoformat(), actor_id)).lastrowid


def status():
    with connection() as conn:
        state = dict(conn.execute('SELECT * FROM support_ai_state WHERE id=1').fetchone())
        model = conn.execute('SELECT id,trained_at,revision,document_count,sample_count,fingerprint FROM support_ai_models WHERE id=?',
                              (state['active_model'],)).fetchone()
        count = conn.execute('SELECT COUNT(*),COALESCE(SUM(enabled),0) FROM support_ai_knowledge').fetchone()
    return dict(name=state['name'], enabled=bool(state['enabled']), configured=bool(state['enabled'] and model),
                threshold=state['threshold'], fallback=state['fallback'], provider='local', source='local',
                algorithm=support_model.ALGORITHM, knowledge_count=count[0], enabled_count=count[1],
                needs_training=not model or model['revision'] != state['revision'], model=dict(model) if model else None)


def settings(data):
    name = clean_text(data.get('name'), 'Tên trợ lý', 80)
    fallback = clean_text(data.get('fallback'), 'Câu trả lời khi chưa biết', 1200)
    enabled, threshold = data.get('enabled'), data.get('threshold')
    if not isinstance(enabled, bool) or isinstance(threshold, bool) or not isinstance(threshold, (float, int)) or not math.isfinite(threshold) or not 0.35 <= threshold <= 0.95:
        raise KnowledgeError('Chọn trạng thái hợp lệ và ngưỡng tin cậy từ 0.35 đến 0.95.')
    with connection(write=True) as conn:
        conn.execute('UPDATE support_ai_state SET name=?,enabled=?,threshold=?,fallback=? WHERE id=1',
                     (name, int(enabled), threshold, fallback))
    return status()


def list_documents():
    with connection() as conn:
        return [document(row) for row in conn.execute('SELECT * FROM support_ai_knowledge ORDER BY id DESC')]


def save_document(data, actor_id):
    item = validate(data)
    item_id = data.get('id')
    if item_id is not None and (type(item_id) is not int or item_id < 1 or item_id > 9223372036854775807):
        raise KnowledgeError('Mã mục kiến thức chưa hợp lệ.')
    with connection(write=True) as conn:
        if item_id is None:
            if conn.execute('SELECT COUNT(*) FROM support_ai_knowledge').fetchone()[0] >= MAX_DOCUMENTS:
                raise KnowledgeError('Kho kiến thức có tối đa 300 mục.')
            item_id = _insert(conn, item, actor_id)
        else:
            result = conn.execute('UPDATE support_ai_knowledge SET title=?,questions=?,answer=?,enabled=?,updated_at=?,updated_by=? WHERE id=?',
                                  (item['title'], encoded(item['questions']), item['answer'], int(item['enabled']),
                                   datetime.now().isoformat(), actor_id, item_id))
            if result.rowcount != 1:
                raise KnowledgeError('Không tìm thấy mục kiến thức.')
        conn.execute('UPDATE support_ai_state SET revision=revision+1 WHERE id=1')
    return item_id


def delete_document(item_id):
    if type(item_id) is not int or not 1 <= item_id <= 9223372036854775807:
        raise KnowledgeError('Mã mục kiến thức chưa hợp lệ.')
    with connection(write=True) as conn:
        if conn.execute('DELETE FROM support_ai_knowledge WHERE id=?', (item_id,)).rowcount != 1:
            raise KnowledgeError('Không tìm thấy mục kiến thức.')
        conn.execute('UPDATE support_ai_state SET revision=revision+1 WHERE id=1')


def train(actor_id):
    with connection(write=True) as conn:
        _train(conn, actor_id)
    return status()


def import_documents(data, actor_id):
    items = data.get('documents')
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_DOCUMENTS:
        raise KnowledgeError('Tệp JSON cần có danh sách documents từ 1 đến 300 mục.')
    items = [validate(item) for item in items]
    with connection(write=True) as conn:
        titles = [row[0].casefold() for row in conn.execute('SELECT title FROM support_ai_knowledge')]
        existing = set(titles)
        if len(titles) + len(items) > MAX_DOCUMENTS:
            raise KnowledgeError('Kho kiến thức có tối đa 300 mục.')
        for item in items:
            if item['title'].casefold() in existing:
                raise KnowledgeError('Tiêu đề đã tồn tại: ' + item['title'])
            existing.add(item['title'].casefold())
            _insert(conn, item, actor_id)
        conn.execute('UPDATE support_ai_state SET revision=revision+1 WHERE id=1')
    return len(items)


def answer(text, history=()):
    with connection() as conn:
        state = conn.execute('SELECT * FROM support_ai_state WHERE id=1').fetchone()
        if not state['enabled']:
            raise KnowledgeError('Trợ lý AI nội bộ đang tắt. Bạn có thể chọn Chat với đội ngũ.')
        row = conn.execute('SELECT id,payload FROM support_ai_models WHERE id=?', (state['active_model'],)).fetchone()
    if row is None:
        raise KnowledgeError('Chưa có mô hình nội bộ. Quản trị viên cần huấn luyện kho kiến thức.')
    # Only explicit requests to repeat an explanation use the user's own previous question.
    if support_model.normalize(text) in ('noi ro hon', 'chi tiet hon', 'huong dan lai') and history:
        text = history[-1]['user_text']
    live_result = support_pricing.answer(text, history)
    if live_result is None:
        live_result = support_live.answer(text)
    if live_result is not None:
        return dict(live_result, model_version=row['id'])
    result = support_model.predict(json.loads(row['payload']), text, state['threshold'])
    result.update(answer=result['answer'] or state['fallback'], model_version=row['id'], source='knowledge')
    return result
