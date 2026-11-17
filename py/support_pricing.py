"""Local parking fee estimates using the same calculator as checkout; no account lookups."""
from datetime import datetime, timedelta, timezone
import re
import unicodedata

import database
from parking_fees import calculate_turn_fee, DEFAULT_HOURLY_FALLBACK
from support_live import contains, _types_in_question, is_availability_question
from support_model import normalize


ASK_TYPE = 'Để ước tính phí, bạn gửi loại xe nào?'
ASK_TIME = 'Bạn gửi từ mấy giờ đến mấy giờ?'
QUOTE_PREFIX = 'Ước tính phí gửi '
TIME = r'\d{1,2}\s*(?:(?:h|gio|:)\s*(?:\d{1,2}\s*(?:phut|p)?)?)?\s*(?:sang|trua|chieu|toi|dem|am|pm)?'
RANGE = re.compile(r'(?<![\d/:])(?:tu\s+)?(?P<start>' + TIME + r')\s*(?:den|toi|–|—|->|-)\s*(?P<end>' + TIME + r')(?![\w/:])')


def fold(text):
    text = unicodedata.normalize('NFKD', text.lower().replace('đ', 'd'))
    return ' '.join(''.join(c for c in text if not unicodedata.combining(c)).split())


def _clock(value):
    match = re.fullmatch(r'(\d{1,2})\s*(?:(h|gio|:)\s*(?:(\d{1,2})\s*(?:phut|p)?)?)?\s*(sang|trua|chieu|toi|dem|am|pm)?', value.strip())
    if not match:
        raise ValueError
    hour, unit, minute, period = match.groups()
    hour, minute = int(hour), int(minute or 0)
    if hour > 23 or minute > 59 or (unit == ':' and not re.search(r':\s*\d', value)):
        raise ValueError
    if period in ('am', 'pm'):
        if not 1 <= hour <= 12:
            raise ValueError
        hour = hour % 12 + (12 if period == 'pm' else 0)
    elif period == 'sang':
        if hour > 11:
            raise ValueError
    elif period == 'trua':
        if hour in (1, 2):
            hour += 12
        elif hour not in (11, 12, 13, 14):
            raise ValueError
    elif period == 'chieu':
        if 1 <= hour <= 6:
            hour += 12
        elif not 12 <= hour <= 18:
            raise ValueError
    elif period in ('toi', 'dem'):
        if hour == 12:
            hour = 0
        elif 6 <= hour <= 11:
            hour += 12
        elif not (18 <= hour <= 23 or (period == 'dem' and 0 <= hour <= 5)):
            raise ValueError
    if not unit and not period:
        raise ValueError
    return hour * 60 + minute


def parse_interval(text):
    match = RANGE.search(fold(text))
    if not match:
        return None
    start, end = _clock(match['start']), _clock(match['end'])
    if end < start or any(contains(normalize(text), phrase) for phrase in ('hom sau', 'ngay sau')):
        end += 1440
    return start, end


def _fee_question(text):
    has_interval = RANGE.search(fold(text)) is not None
    text = normalize(text)
    explicit_price = any(contains(text, word) for word in ('phi', 'tien', 'gia', 'het bao nhieu', 'ton bao nhieu'))
    if is_availability_question(text) and not explicit_price:
        return False
    parking = any(contains(text, word) for word in ('gui xe', 'giu xe', 'do xe', 'phi gui', 'tinh phi', 'xe may', 'o to', 'oto'))
    return parking and (explicit_price or contains(text, 'bao nhieu') or has_interval)


def _read_pricing():
    conn = database.get_connection()
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        types = [dict(row) for row in conn.execute('SELECT id,name,grace_minutes,daily_cap,free_minutes,first_block_hours,first_block_amount,next_hour_amount FROM vehicle_types ORDER BY id')]
        rates = {}
        for row in conn.execute("SELECT p.vehicle_type_id,t.id AS period_id,p.amount,t.name AS period_name,t.start_value AS start,t.end_value AS end "
                                "FROM prices p JOIN price_periods t ON t.id=p.period_id WHERE p.ticket_type='turn' AND t.kind='time' ORDER BY t.id"):
            rates.setdefault(row['vehicle_type_id'], []).append(dict(row))
        return types, rates
    finally:
        conn.close()


def answer(text, history=()):
    original = text
    pricing = None
    previous = history[-1] if history else None
    if not _fee_question(original) and previous and previous['answer'].startswith((ASK_TYPE, ASK_TIME, QUOTE_PREFIX)):
        # Only a short vehicle/time reply can continue the immediately preceding fee question.
        pricing = _read_pricing()
        reply_types = _types_in_question(normalize(original), pricing[0])
        remaining = normalize(original)
        for item in reply_types:
            remaining = remaining.replace(normalize(item['name']), '').replace('oto', '').replace('xe hoi', '')
        short_reply = reply_types and set(remaining.split()) <= {'toi', 'minh', 'gui', 'di', 'loai', 'xe', 'nhe', 'nha', 'a', 'thi', 'sao', 'con', 'va', 'o', 'to'}
        time_reply = RANGE.search(fold(text))
        if len(normalize(text).split()) <= 12 and short_reply:
            context = []
            for turn in reversed(history[-8:]):
                context.insert(0, turn['user_text'])
                if _fee_question(turn['user_text']):
                    if RANGE.search(fold(' '.join(context))):
                        text = ' '.join(context + [original])
                    break
        elif previous['answer'].startswith(ASK_TIME) and time_reply:
            remainder = normalize(fold(original)[:time_reply.start()] + ' ' + fold(original)[time_reply.end():])
            if set(remainder.split()) <= {'tu', 'toi', 'gui', 'xe', 'nhe', 'a', 'cung', 'ngay', 'hom', 'sau'}:
                text = previous['user_text'] + ' ' + original
    if not _fee_question(text):
        return None
    base = dict(source='parking_data', intent='parking_fee', matched=False, confidence=None, title='Ước tính phí gửi xe')
    if contains(normalize(text), 've thang'):
        return dict(base, answer='Vé tháng còn hạn tại thời điểm xe ra được miễn phí lượt. Tôi không kiểm tra vé riêng của bạn; hãy đối chiếu thời hạn vé trong Cài đặt hoặc nhờ đội ngũ hỗ trợ.')
    # A duration alone does not establish which pricing windows the stay crosses.
    try:
        interval = parse_interval(text)
    except ValueError:
        return dict(base, answer='Tôi chưa xác định được giờ hợp lệ. Hãy ghi theo dạng 24 giờ, ví dụ: gửi xe máy từ 01:00 đến 22:00 hết bao nhiêu?')
    if interval is None:
        if re.search(r'\d|\b(tinh phi|phi gui|tien gui|gui xe)\b', normalize(text)):
            return dict(base, answer=ASK_TIME + ' Ví dụ: gửi xe máy từ 01:00 đến 22:00 hết bao nhiêu?')
        return None
    if re.search(r'\d{1,2}/\d{1,2}|\d{4}-\d{1,2}-\d{1,2}|\b\d+\s*(?:ngay|tuan|thang|nam)\b', fold(text)):
        return dict(base, answer='Ước tính này hỗ trợ khoảng giờ trong cùng ngày hoặc qua một đêm. Với ngày cụ thể hoặc nhiều ngày, hãy đối chiếu tại Xe ra hoặc liên hệ đội ngũ hỗ trợ.')
    types, rates = pricing or _read_pricing()
    # Prefer the current reply's explicit type over a type in an earlier question.
    selected = _types_in_question(normalize(original), types) or _types_in_question(normalize(text), types)
    start, end = interval
    interval_label = f'{start // 60:02d}:{start % 60:02d}–{end % 1440 // 60:02d}:{end % 60:02d}'
    interval_label += ' ngày hôm sau' if end >= 1440 else ' cùng ngày'
    minutes = end - start
    duration = f'{minutes // 60} giờ' + (f' {minutes % 60} phút' if minutes % 60 else '')
    if len(selected) != 1:
        choices = ', '.join(item['name'] for item in selected or types)
        return dict(base, answer=ASK_TYPE + f' Tôi hiểu khoảng gửi là {interval_label} ({duration}). '
                    + ('Các loại xe: ' + choices + '.' if choices else 'Hiện chưa có loại xe được cấu hình.'))
    vehicle = selected[0]
    now = datetime.now(timezone(timedelta(hours=7)))
    day = datetime.combine(now.date(), datetime.min.time())
    fee, explanation = calculate_turn_fee(rates.get(vehicle['id'], []), day + timedelta(minutes=start),
        day + timedelta(minutes=end), DEFAULT_HOURLY_FALLBACK, vehicle['grace_minutes'], vehicle['daily_cap'],
        free_minutes=vehicle['free_minutes'], first_block_hours=vehicle['first_block_hours'],
        first_block_amount=vehicle['first_block_amount'], next_hour_amount=vehicle['next_hour_amount'])
    amount = f'{fee:,}'.replace(',', '.') + 'đ'
    message = QUOTE_PREFIX + vehicle['name'] + f' từ {interval_label} ({duration}): {amount}.\n' + explanation
    message += '\nTheo bảng giá hiện hành, dùng cùng cách tính với Xe ra. Đây là ước tính vé lượt, chưa áp dụng vé tháng của từng xe.'
    return dict(base, matched=True, answer=message, checked_at=now.isoformat(),
                data=dict(amount=fee, vehicle_type_id=vehicle['id'], vehicle_type=vehicle['name'],
                          start_minutes=start, end_minutes=end, duration_minutes=minutes, explanation=explanation))
