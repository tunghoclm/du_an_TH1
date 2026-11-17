"""
train_chatbot.py
Tự động huấn luyện chatbot hỗ trợ nội bộ (support_model, TF-IDF) từ file kiến thức JSON.

Quy trình mỗi lần chạy:
  1. Khởi tạo CSDL (nếu chưa có).
  2. Đồng bộ file JSON -> bảng support_ai_knowledge (thêm mục mới / cập nhật mục thay đổi theo tiêu đề).
  3. Đánh giá chất lượng (leave-one-out): mỗi câu hỏi mẫu được che đi rồi cho mô hình đoán lại.
  4. Nếu độ chính xác >= --min-accuracy thì huấn luyện và kích hoạt mô hình mới.

Cách chạy:
  python py/train_chatbot.py                         # đồng bộ + đánh giá + train (nếu có thay đổi)
  python py/train_chatbot.py --force                 # luôn train lại
  python py/train_chatbot.py --watch                 # theo dõi file JSON, sửa là tự train lại
  python py/train_chatbot.py --watch --interval 10   # kiểm tra mỗi 10 giây
  python py/train_chatbot.py --file data.json --prune  # tắt các mục trong DB không còn trong file
  python py/train_chatbot.py --overwrite             # ghi đè mục trùng tiêu đề bằng nội dung file
  python py/train_chatbot.py --ask "Xe vào thế nào?" # hỏi thử sau khi train
  python py/train_chatbot.py --eval-only             # chỉ đánh giá, không ghi DB

Định dạng JSON: danh sách [{"title", "questions": [...], "answer", "enabled"?}]
hoặc {"documents": [...]} (giống file xuất/nhập trong trang Cài đặt AI).
"""
import argparse
import json
import os
import sys
import time
from collections import Counter

# Console Windows mặc định dùng cp1252 -> in tiếng Việt sẽ lỗi; chuyển sang UTF-8.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

PY_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PY_DIR)

import database           # noqa: E402
import support_knowledge  # noqa: E402
import support_model      # noqa: E402

DEFAULT_FILE = os.path.join(os.path.dirname(PY_DIR), 'assets', 'support_knowledge.json')


# ---------------------------------------------------------------- dữ liệu
def load_file(path):
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    items = data.get('documents') if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise support_knowledge.KnowledgeError('File JSON cần là danh sách mục kiến thức hoặc {"documents": [...]}.')
    cleaned, titles = [], set()
    for index, item in enumerate(items, 1):
        try:
            item = support_knowledge.validate(item)
        except support_knowledge.KnowledgeError as error:
            raise support_knowledge.KnowledgeError(f'Mục #{index}: {error}') from None
        key = item['title'].casefold()
        if key in titles:
            raise support_knowledge.KnowledgeError(f'Tiêu đề bị trùng trong file: {item["title"]}')
        titles.add(key)
        cleaned.append(item)
    return cleaned


def sync(items, prune=False, overwrite=False):
    """Đồng bộ file -> DB theo tiêu đề. Trả về (thêm, sửa, tắt).
    Mặc định KHÔNG ghi đè mục admin đã sửa trên web; bật overwrite để file là nguồn chuẩn."""
    existing = {doc['title'].casefold(): doc for doc in support_knowledge.list_documents()}
    added = updated = disabled = 0
    for item in items:
        current = existing.pop(item['title'].casefold(), None)
        if current is None:
            support_knowledge.save_document(dict(item), None)
            added += 1
            print(f'  + Thêm  : {item["title"]}')
        elif any(current[k] != item[k] for k in ('title', 'questions', 'answer', 'enabled')):
            if not overwrite:
                print(f'  = Giữ   : {item["title"]} (DB khác file; dùng --overwrite để ghi đè)')
                continue
            support_knowledge.save_document(dict(item, id=current['id']), None)
            updated += 1
            print(f'  ~ Sửa   : {item["title"]}')
    if prune:
        for doc in existing.values():
            if doc['enabled']:
                support_knowledge.save_document(dict(doc, enabled=False), None)
                disabled += 1
                print(f'  - Tắt   : {doc["title"]}')
    return added, updated, disabled


# ---------------------------------------------------------------- đánh giá
def evaluate(documents, threshold, verbose=True):
    """Leave-one-out: che từng câu hỏi mẫu và để mô hình đoán từ các câu còn lại."""
    model = support_model.train(documents)
    samples = model['samples']
    titles = {doc['id']: doc['title'] for doc in documents}
    result = Counter()
    confusions = Counter()
    for held in samples:
        ranked = {}
        for other in samples:
            if other is held:
                continue
            score = sum(v * other['vector'].get(t, 0) for t, v in held['vector'].items())
            key = other['document_id']
            ranked[key] = max(ranked.get(key, 0), score)
        if not ranked:
            continue
        choices = sorted(ranked.items(), key=lambda item: (-item[1], item[0]))
        best_id, score = choices[0]
        margin = score - choices[1][1] if len(choices) > 1 else score
        matched = score >= threshold and (score >= 0.999 or margin >= 0.07)
        if not matched:
            result['unmatched'] += 1
        elif best_id == held['document_id']:
            result['correct'] += 1
        else:
            result['wrong'] += 1
            confusions[(held['question'], titles[held['document_id']], titles[best_id])] += 1
    total = sum(result.values()) or 1
    accuracy = result['correct'] / total
    precision = result['correct'] / ((result['correct'] + result['wrong']) or 1)
    if verbose:
        print(f'  Mẫu: {total} | Đúng: {result["correct"]} | Sai chủ đề: {result["wrong"]} '
              f'| Không chắc: {result["unmatched"]}')
        print(f'  Độ chính xác (LOO): {accuracy:.1%} | Độ chuẩn khi đã trả lời: {precision:.1%}')
        for (question, expected, got), _ in confusions.most_common(10):
            print(f'    ! "{question}" thuộc [{expected}] nhưng bị nhận thành [{got}]')
        if result['unmatched']:
            print('  Gợi ý: thêm nhiều cách hỏi khác nhau cho mỗi mục để giảm câu "Không chắc".')
    return accuracy, precision


# ---------------------------------------------------------------- huấn luyện
def run_once(args):
    print(f'[{time.strftime("%H:%M:%S")}] Đọc kiến thức: {args.file}')
    items = load_file(args.file)
    status = support_knowledge.status()
    threshold = status['threshold']

    if args.eval_only:
        docs = [dict(item, id=i) for i, item in enumerate(items, 1) if item['enabled']]
        print('Đánh giá (không ghi DB):')
        evaluate(docs, threshold)
        return True

    print('Đồng bộ vào CSDL:')
    added, updated, disabled = sync(items, prune=args.prune, overwrite=args.overwrite)
    if not (added or updated or disabled):
        print('  (không có thay đổi)')

    status = support_knowledge.status()
    if not status['needs_training'] and not args.force:
        print(f'Mô hình #{status["model"]["id"]} đã mới nhất — bỏ qua huấn luyện (dùng --force để train lại).')
        return True

    documents = [doc for doc in support_knowledge.list_documents() if doc['enabled']]
    print(f'Đánh giá trên {len(documents)} mục đang bật (ngưỡng tin cậy {threshold}):')
    try:
        accuracy, _ = evaluate(documents, threshold)
    except ValueError as error:
        print(f'  LỖI dữ liệu: {error}')
        return False
    if accuracy < args.min_accuracy:
        print(f'  Độ chính xác {accuracy:.1%} < yêu cầu {args.min_accuracy:.0%} — KHÔNG kích hoạt mô hình mới.')
        return False

    status = support_knowledge.train(None)
    model = status['model']
    print(f'✔ Đã huấn luyện mô hình #{model["id"]} ({status["algorithm"]}): '
          f'{model["document_count"]} mục, {model["sample_count"]} câu mẫu, lúc {model["trained_at"][:19]}')
    return True


def ask(question):
    result = support_knowledge.answer(question)
    print(f'\nHỏi : {question}')
    if result.get('source') == 'knowledge':
        print(f'Khớp: {result.get("title") or "(không khớp)"} | độ tin cậy {result.get("confidence")}')
    print(f'Đáp : {result["answer"]}')


def watch(args):
    print(f'Đang theo dõi {args.file} (mỗi {args.interval}s). Nhấn Ctrl+C để dừng.')
    last = None
    while True:
        try:
            mtime = os.path.getmtime(args.file)
            if mtime != last:
                last = mtime
                try:
                    run_once(args)
                except (support_knowledge.KnowledgeError, json.JSONDecodeError) as error:
                    print(f'  LỖI: {error} — chờ lần sửa file tiếp theo.')
                print('-' * 60)
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print('\nĐã dừng theo dõi.')
            return
        except FileNotFoundError:
            time.sleep(args.interval)


def main():
    parser = argparse.ArgumentParser(description='Tự động huấn luyện chatbot hỗ trợ Smart Parking.')
    parser.add_argument('--file', default=DEFAULT_FILE, help='File JSON kiến thức (mặc định assets/support_knowledge.json)')
    parser.add_argument('--force', action='store_true', help='Luôn huấn luyện lại dù không có thay đổi')
    parser.add_argument('--prune', action='store_true', help='Tắt các mục trong DB không có trong file')
    parser.add_argument('--overwrite', action='store_true', help='Ghi đè mục trùng tiêu đề bằng nội dung trong file')
    parser.add_argument('--min-accuracy', type=float, default=0.0,
                        help='Độ chính xác LOO tối thiểu (0-1) để kích hoạt mô hình mới, vd 0.7')
    parser.add_argument('--eval-only', action='store_true', help='Chỉ đánh giá file, không ghi CSDL')
    parser.add_argument('--watch', action='store_true', help='Theo dõi file và tự train lại khi thay đổi')
    parser.add_argument('--interval', type=float, default=5, help='Chu kỳ kiểm tra file khi --watch (giây)')
    parser.add_argument('--ask', action='append', default=[], help='Câu hỏi thử sau khi train (lặp lại được)')
    args = parser.parse_args()

    database.init_db()  # tạo bảng + mô hình mặc định nếu chưa có
    if args.watch:
        watch(args)
        return 0
    try:
        ok = run_once(args)
        for question in args.ask:
            ask(question)
    except (support_knowledge.KnowledgeError, json.JSONDecodeError, FileNotFoundError) as error:
        print(f'LỖI: {error}')
        return 1
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
