"""Read-only receipts from completed parking sessions, using their recorded fees."""
import csv
from datetime import date, datetime
from io import StringIO
from urllib.parse import urlencode

import database
from plate_utils import plate_key
from invoice_periods import PERIOD_GROUPS, PERIOD_LABELS, datetime_input, period_bounds


def get_invoices(role, user_id):
    conn = database.get_connection()
    try:
        rows = conn.execute(
            """SELECT r.*, u.fullname AS customer_name, s.area AS area_name
               FROM parking_records r
               LEFT JOIN parking_slots s ON s.slot_name = r.slot_name
               LEFT JOIN user_vehicles v ON v.plate_key =
                   REPLACE(REPLACE(REPLACE(UPPER(r.plate_number), '-', ''), '.', ''), ' ', '')
               LEFT JOIN users u ON u.id = v.user_id
               WHERE r.status = 'OUT' AND r.exit_time IS NOT NULL AND r.fee IS NOT NULL"""
            + (" AND v.user_id = ?" if role not in ('admin', 'manager') else "")
            + " ORDER BY r.exit_time DESC, r.id DESC",
            (user_id,) if role not in ('admin', 'manager') else (),
        ).fetchall()
    finally:
        conn.close()
    result = []
    for row in rows:
        item = dict(row)
        item['code'] = f"HD{item['id']:06d}"
        item['customer_name'] = item['customer_name'] or 'Khách vãng lai'
        item['vehicle_type_name'] = item['vehicle_type_name'] or 'Chưa phân loại'
        item['area_name'] = item['area_name'] or ''
        item['fee'] = int(item['fee'])
        item['payment_method_label'] = ('Không thu phí' if item['fee'] == 0 else
                                        database.PAYMENT_METHODS.get(item['payment_method'], 'Chưa ghi nhận'))
        for field in ('entry_time', 'exit_time'):
            try:
                item[field + '_label'] = datetime.fromisoformat(item[field]).strftime('%d/%m/%Y %H:%M')
            except (ValueError, TypeError):
                item[field + '_label'] = item[field] or '—'
        try:
            minutes = max(0, int((datetime.fromisoformat(item['exit_time'])
                                 - datetime.fromisoformat(item['entry_time'])).total_seconds() // 60))
            days, minutes = divmod(minutes, 1440)
            hours, minutes = divmod(minutes, 60)
            item['duration'] = ' '.join(label for count, label in (
                (days, f'{days} ngày'), (hours, f'{hours} giờ'), (minutes, f'{minutes} phút')) if count) or 'Dưới 1 phút'
        except (ValueError, TypeError):
            item['duration'] = '—'
        result.append(item)
    return result


def invoice_context(args, role, user_id, today=None):
    today = today or date.today()
    records = get_invoices(role, user_id)
    filters = {key: args.get(key, '').strip() for key in
               ('q', 'range', 'from', 'to', 'area', 'vehicle_type', 'fee', 'payment_method', 'sort', 'direction')}
    if args.get('payment_choice') in database.PAYMENT_METHODS:
        filters['payment_method'] = args['payment_choice']
    if filters['payment_method'] not in database.PAYMENT_METHODS:
        filters['payment_method'] = ''
    errors = []
    if args.get('range_choice') in PERIOD_LABELS:
        filters['range'] = args['range_choice']
    elif args.get('time_mode') == 'custom':
        filters['range'] = 'custom'
    if filters['range'] not in (*PERIOD_LABELS, 'custom'):
        filters['range'] = 'today'
    if filters['fee'] not in ('paid', 'free'):
        filters['fee'] = ''
    if filters['sort'] not in ('code', 'time', 'fee'):
        filters['sort'] = 'time'
    if filters['direction'] not in ('asc', 'desc'):
        filters['direction'] = 'desc'
    start = end = None
    try:
        start, end = period_bounds(filters['range'], today, filters['from'], filters['to'])
    except ValueError as error:
        errors.append(str(error))
    areas = sorted({r['area_name'] for r in records if r['area_name']})
    types = sorted({r['vehicle_type_name'] for r in records})
    keyword = filters['q'].casefold()
    key = plate_key(filters['q'])

    def matches(record):
        if errors:
            return False
        if keyword and not (any(keyword in str(record[field]).casefold()
                                for field in ('code', 'plate_number', 'customer_name'))
                            or (key and key in plate_key(record['plate_number']))):
            return False
        if start:
            try:
                stamp = datetime.fromisoformat(record['exit_time'])
                if not start <= stamp < end:
                    return False
            except (ValueError, TypeError):
                return False
        if filters['area'] and record['area_name'] != filters['area']:
            return False
        if filters['vehicle_type'] and record['vehicle_type_name'] != filters['vehicle_type']:
            return False
        if filters['payment_method'] and record['payment_method'] != filters['payment_method']:
            return False
        return not ((filters['fee'] == 'paid' and record['fee'] <= 0)
                    or (filters['fee'] == 'free' and record['fee'] != 0))

    filtered = [record for record in records if matches(record)]
    sort_field = {'code': 'id', 'time': 'exit_time', 'fee': 'fee'}[filters['sort']]
    filtered.sort(key=lambda r: (r[sort_field], r['id']), reverse=filters['direction'] == 'desc')
    try:
        per_page = int(args.get('per_page', 20))
    except (ValueError, TypeError):
        per_page = 20
    per_page = per_page if per_page in (20, 50, 100) else 20
    pages = max(1, (len(filtered) + per_page - 1) // per_page)
    try:
        page = min(pages, max(1, int(args.get('page', 1))))
    except (ValueError, TypeError):
        page = 1

    def query_string(**overrides):
        query = dict(filters, per_page=per_page)
        query.update(overrides)
        return urlencode({key: value for key, value in query.items() if value != ''})

    return dict(items=filtered[(page - 1) * per_page:page * per_page], filtered=filtered,
                total_count=len(filtered), total_fee=sum(r['fee'] for r in filtered),
                page=page, pages=pages, per_page=per_page, filters=filters, errors=errors,
                areas=areas, vehicle_types=types, query_string=query_string,
                payment_methods=database.PAYMENT_METHODS,
                period_groups=PERIOD_GROUPS, period_label=PERIOD_LABELS.get(filters['range'], 'Hôm nay'),
                custom_from=datetime_input(filters['from']), custom_to=datetime_input(filters['to'], end=True),
                first_item=(page - 1) * per_page + 1 if filtered else 0,
                last_item=min(page * per_page, len(filtered)))


def export_csv(records):
    output = StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['Mã hóa đơn', 'Biển số', 'Khách hàng', 'Loại xe', 'Khu vực', 'Ô đỗ',
                     'Thời gian vào', 'Thời gian ra', 'Thời gian gửi', 'Phí thu (VND)', 'Phương thức', 'Ghi chú'])
    for record in records:
        values = [record[key] if record[key] is not None else '' for key in ('code', 'plate_number', 'customer_name',
                  'vehicle_type_name', 'area_name', 'slot_name', 'entry_time_label',
                  'exit_time_label', 'duration', 'fee', 'payment_method_label', 'note')]
        writer.writerow(["'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@'))
                         else value for value in values])
    return output.getvalue().encode('utf-8-sig')
