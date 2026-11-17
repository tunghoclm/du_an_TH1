"""Fixed, read-only local lookups for aggregate parking availability. No generated SQL."""
from datetime import datetime, timedelta, timezone
import re

import database
from support_model import normalize


def contains(text, phrase):
    return re.search(r'\b' + re.escape(phrase) + r'\b', text) is not None


def is_availability_question(text):
    # Do not treat instructions to change the lot or general help as live lookups.
    if any(contains(text, phrase) for phrase in (
            'xoa', 'them', 'sua', 'tao', 'cap nhat', 'bao tri', 'dat cho', 'giu cho',
            'dat truoc', 'chuyen xe', 'mo cong', 'thay doi', 'phai lam gi', 'huong dan', 'cach',
            'phi', 'gia', 'tien', 'hoa don', 'doanh thu')):
        return False
    context = any(contains(text, phrase) for phrase in ('bai', 'xe', 'do', 'khu', 'tang', 'slot', 'cho trong', 'con cho', 'co cho'))
    capacity = any(contains(text, phrase) for phrase in ('trong', 'cho', 'o do', 'slot', 'suc chua', 'day'))
    question = (any(contains(text, phrase) for phrase in ('bao nhieu', 'may cho', 'may o', 'con lai', 'so cho', 'so o', 'suc chua'))
                or any(contains(text, word) for word in ('khong', 'chua'))
                or text in ('cho trong', 'o do trong', 'con cho', 'bai con cho'))
    return context and capacity and question


def _read_snapshot():
    conn = database.get_connection()
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        # A slot with an open parking record must not be offered even if its status is stale.
        rows = conn.execute("""
            WITH slot_states AS (
                SELECT s.area,s.slot_name,
                    CASE WHEN s.status='occupied' OR EXISTS (
                        SELECT 1 FROM parking_records r WHERE r.slot_name=s.slot_name AND r.status='IN'
                    ) THEN 'occupied'
                    WHEN s.status='maintenance' THEN 'maintenance'
                    WHEN s.status='available' THEN 'available' ELSE 'unavailable' END AS state
                FROM parking_slots s
            )
            SELECT a.name,a.vehicle_type_id,COUNT(s.slot_name) AS total,
                SUM(CASE WHEN s.state='available' THEN 1 ELSE 0 END) AS available,
                SUM(CASE WHEN s.state='occupied' THEN 1 ELSE 0 END) AS occupied,
                SUM(CASE WHEN s.state='maintenance' THEN 1 ELSE 0 END) AS maintenance
            FROM parking_areas a LEFT JOIN slot_states s ON s.area=a.name
            GROUP BY a.id ORDER BY a.id
        """).fetchall()
        types = conn.execute('SELECT id,name FROM vehicle_types ORDER BY id').fetchall()
        return [dict(row) for row in rows], [dict(row) for row in types]
    finally:
        conn.close()


def _areas_in_question(text, areas):
    result = []
    for area in areas:
        name = normalize(area['name'])
        short = re.sub(r'^(?:khu|tang|bai)\s+', '', name)
        keys = {name} if len(name.split()) > 1 else set()
        keys.update(prefix + ' ' + short for prefix in ('khu', 'tang', 'bai'))
        if any(contains(text, key) for key in keys):
            result.append(area)
    return result


def _vehicle_key(text):
    return re.sub(r'\b(?:oto|xe hoi)\b', 'o to', text)


def _types_in_question(text, types):
    text = _vehicle_key(text)
    matches = []
    for item in types:
        name = _vehicle_key(normalize(item['name']))
        # Bare "máy" normalizes to "mấy", and "tải" to "tại"; these are not type names on their own.
        keys = {name} if name not in ('', 'xe', 'may', 'tai', 'dap', 'cho', 'o') else set()
        short = re.sub(r'^xe\s+', '', name)
        if len(short.split()) > 1:
            keys.add(short)
        found = [key for key in keys if contains(text, key)]
        if found:
            matches.append((item, found))
    # Prefer the full type name: "xe máy điện" should not also mean "xe máy".
    return [item for item, keys in matches if not any(
        all(any(other != key and contains(other, key) for other in other_keys) for key in keys)
        for other_item, other_keys in matches if other_item['id'] != item['id'])]


def answer(text):
    text = normalize(text)
    if not is_availability_question(text):
        return None
    base = dict(source='parking_data', intent='parking_availability', matched=False,
                confidence=None, title='Tra cứu chỗ trống hiện tại')
    if re.search(r'\b(hom qua|ngay mai|ngay kia|sang mai|toi mai|toi nay|chieu nay|dem nay|tuan truoc|tuan sau|thang truoc|thang sau|luc \d+|ngay \d+|\d{1,2}h)\b', text):
        return dict(base, answer='Tôi tra cứu được số ô đỗ trống tại thời điểm hiện tại, chưa tra cứu lịch sử hoặc dự báo chỗ trống. Bạn có muốn kiểm tra số chỗ trống bây giờ không?')
    areas, types = _read_snapshot()
    selected_areas = _areas_in_question(text, areas)
    if len(selected_areas) > 1:
        return dict(base, answer='Bạn muốn kiểm tra khu nào? Hãy hỏi một khu cụ thể: ' + ', '.join(area['name'] for area in selected_areas[:12]) + '.')
    if not selected_areas and re.search(r'\b(?:khu|tang)\s+\S+', text):
        return dict(base, answer='Tôi chưa xác định được khu bạn hỏi. Các khu hiện có: ' + (', '.join(area['name'] for area in areas[:12]) or 'chưa có khu nào') + '. Hãy ghi đúng tên khu.')
    selected_types = _types_in_question(text, types)
    if len(selected_types) > 1:
        return dict(base, answer='Bạn muốn kiểm tra chỗ cho loại xe nào? Hãy chọn một loại: ' + ', '.join(item['name'] for item in selected_types) + '.')
    if not selected_types and any(contains(_vehicle_key(text), name) for name in ('xe may', 'o to', 'xe dap', 'xe tai', 'xe khach', 'xe buyt')):
        return dict(base, answer='Tôi chưa xác định được loại xe trong cấu hình bãi. Hãy dùng tên loại xe trong Bảng giá hoặc liên hệ đội ngũ hỗ trợ.')
    rows = selected_areas or areas
    vehicle_type = selected_types[0] if selected_types else None
    if vehicle_type:
        rows = [area for area in rows if area['vehicle_type_id'] in (None, vehicle_type['id'])]
    counts = {key: sum(area[key] for area in rows) for key in ('total', 'available', 'occupied', 'maintenance')}
    scope = 'khu ' + selected_areas[0]['name'] if selected_areas else 'bãi xe'
    if vehicle_type:
        scope += ' dành cho ' + vehicle_type['name']
    if not counts['total']:
        message = f'Hiện {scope} chưa có ô đỗ được cấu hình phù hợp.'
    elif counts['available'] == 0:
        message = f'Hiện {scope} không còn ô đỗ trống (0/{counts["total"]} ô).'
    else:
        message = f'Hiện {scope} còn {counts["available"]}/{counts["total"]} ô đỗ trống.'
    if counts['total']:
        message += f' Có {counts["occupied"]} ô đang có xe và {counts["maintenance"]} ô bảo trì.'
    if len(rows) > 1:
        message += '\nTheo khu: ' + '; '.join(f'{area["name"]}: {area["available"]} ô trống' for area in rows[:12]) + '.'
        if len(rows) > 12:
            message += ' Xem Bãi đỗ (/parking) để biết các khu còn lại.'
    checked_at = datetime.now(timezone(timedelta(hours=7)))
    message += '\nTheo dữ liệu quản lý vừa kiểm tra lúc ' + checked_at.strftime('%H:%M:%S %d/%m/%Y') + ' (UTC+7). Ô bảo trì không được tính là chỗ trống.'
    return dict(base, matched=True, answer=message, checked_at=checked_at.isoformat(),
                data=dict(counts, areas=[dict(name=area['name'], **{key: area[key] for key in counts}) for area in rows],
                          vehicle_type=vehicle_type['name'] if vehicle_type else None))
