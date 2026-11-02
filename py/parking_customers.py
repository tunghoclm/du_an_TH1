"""Customer directory and statistics from currently linked parking vehicles."""
import csv
from datetime import date, datetime, timedelta
from io import StringIO
import re
from urllib.parse import urlencode

import database
from invoice_periods import PERIOD_GROUPS, PERIOD_LABELS, datetime_input, period_bounds
from plate_utils import plate_key


CUSTOMER_GROUPS = (('all', 'Tất cả các nhóm'), ('month', 'Có vé tháng còn hạn'),
                   ('expiring', 'Vé tháng sắp hết hạn'), ('expired', 'Có vé tháng hết hạn'),
                   ('turn', 'Có vé lượt'), ('no_vehicle', 'Chưa đăng ký xe'))


def parse_profile(form):
    profile = {key: form.get(key, '').strip() for key in ('fullname', 'phone', 'email', 'address', 'customer_note')}
    errors = []
    if not profile['fullname'] or len(profile['fullname']) > 160:
        errors.append('Họ tên khách hàng phải có từ 1 đến 160 ký tự.')
    phone = profile['phone']
    if phone and (not re.fullmatch(r'[+\d ().-]{7,32}', phone) or not 7 <= sum(c.isdigit() for c in phone) <= 15):
        errors.append('Số điện thoại không hợp lệ.')
    email = profile['email']
    if email and (len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email)):
        errors.append('Địa chỉ email không hợp lệ.')
    if len(profile['address']) > 500:
        errors.append('Địa chỉ tối đa 500 ký tự.')
    if len(profile['customer_note']) > 2000:
        errors.append('Ghi chú tối đa 2.000 ký tự.')
    return profile, errors


def display_time(value):
    try:
        return datetime.fromisoformat(value).strftime('%d/%m/%Y %H:%M')
    except (TypeError, ValueError):
        return 'Chưa ghi nhận'


def customer_records(today):
    conn = database.get_connection()
    try:
        users = conn.execute("SELECT id,username,fullname,status,phone,email,address,customer_note,created_at "
                             "FROM users WHERE role='user' ORDER BY id DESC").fetchall()
        vehicles = conn.execute("SELECT v.*,t.name AS vehicle_type_name FROM user_vehicles v "
                                "LEFT JOIN vehicle_types t ON t.id=v.vehicle_type_id ORDER BY v.id").fetchall()
        records = conn.execute("SELECT id,plate_number,entry_time,exit_time,fee,status,slot_name,vehicle_type_name "
                               "FROM parking_records WHERE status IN ('IN','OUT') ORDER BY entry_time DESC,id DESC").fetchall()
        payments = conn.execute("SELECT user_vehicle_id,amount FROM ticket_payments").fetchall()
    finally:
        conn.close()
    customers = {u['id']: dict(u) for u in users}
    for customer in customers.values():
        customer.update(code=f"KH{customer['id']:06d}", vehicles=[], history=[], groups=set(),
                        vehicle_count=0, monthly_count=0, parking_count=0, visit_count=0,
                        parking_fee=0, monthly_fee=0, total_fee=0, last_visit=None)
        words = (customer['fullname'] or customer['username'] or 'Khách hàng').split()
        customer['initials'] = ''.join(w[0] for w in (words[0], words[-1])).upper() if len(words) > 1 else words[0][:2].upper()
        customer['created_label'] = display_time(customer['created_at'])
    plate_owners, vehicle_owners = {}, {}
    for row in vehicles:
        if row['user_id'] not in customers:
            continue
        vehicle = dict(row)
        customer = customers[row['user_id']]
        expiry = vehicle['expires_on'] or ''
        if vehicle['ticket_type'] == 'month':
            if expiry >= today.isoformat():
                customer['groups'].add('month')
                customer['monthly_count'] += 1
                vehicle['ticket_label'] = 'Vé tháng còn hạn'
                if expiry <= (today + timedelta(days=7)).isoformat():
                    customer['groups'].add('expiring')
                    vehicle['ticket_label'] = 'Sắp hết hạn'
            else:
                customer['groups'].add('expired')
                vehicle['ticket_label'] = 'Vé tháng hết hạn'
        else:
            customer['groups'].add('turn')
            vehicle['ticket_label'] = 'Vé lượt'
        vehicle['in_parking'] = False
        customer['vehicles'].append(vehicle)
        customer['vehicle_count'] += 1
        plate_owners[vehicle['plate_key']] = (customer, vehicle)
        vehicle_owners[vehicle['id']] = customer
    for row in records:
        owner = plate_owners.get(plate_key(row['plate_number']))
        if owner is None:
            continue
        customer, vehicle = owner
        record = dict(row)
        record['entry_label'] = display_time(record['entry_time'])
        record['exit_label'] = display_time(record['exit_time']) if record['exit_time'] else 'Đang trong bãi'
        customer['history'].append(record)
        customer['visit_count'] += 1
        if customer['last_visit'] is None or record['entry_time'] > customer['last_visit']:
            customer['last_visit'] = record['entry_time']
        if record['status'] == 'IN':
            customer['parking_count'] += 1
            vehicle['in_parking'] = True
        elif record['fee'] is not None:
            customer['parking_fee'] += record['fee']
    for payment in payments:
        customer = vehicle_owners.get(payment['user_vehicle_id'])
        if customer is not None:
            customer['monthly_fee'] += payment['amount']
    for customer in customers.values():
        customer['total_fee'] = customer['parking_fee'] + customer['monthly_fee']
        customer['last_visit_label'] = display_time(customer['last_visit'])
        if not customer['vehicles']:
            customer['groups'].add('no_vehicle')
        customer['group_label'] = ('Có vé tháng' if 'month' in customer['groups'] else
                                   'Vé tháng hết hạn' if 'expired' in customer['groups'] else
                                   'Vé lượt' if customer['vehicles'] else 'Chưa đăng ký xe')
    return list(customers.values())


def customer_context(args, today=None):
    today = today or date.today()
    all_customers = customer_records(today)
    keys = ('q', 'group', 'status', 'vehicle_type', 'min_fee', 'max_fee', 'sort', 'direction',
            'created_range', 'created_from', 'created_to', 'visit_range', 'visit_from', 'visit_to')
    filters = {key: args.get(key, '').strip() for key in keys}
    errors, bounds, time_controls = [], {}, []
    if filters['group'] not in dict(CUSTOMER_GROUPS):
        filters['group'] = 'all'
    if filters['status'] not in ('active', 'locked'):
        filters['status'] = ''
    if filters['sort'] not in ('code', 'name', 'fee', 'vehicles', 'monthly'):
        filters['sort'] = 'code'
    if filters['direction'] not in ('asc', 'desc'):
        filters['direction'] = 'desc'
    for prefix, label, field in (('created', 'Ngày tạo', 'created_at'), ('visit', 'Lần vào bãi cuối', 'last_visit')):
        key = filters[prefix + '_range']
        if args.get(prefix + '_choice') in PERIOD_LABELS:
            key = args[prefix + '_choice']
        elif args.get(prefix + '_mode') == 'custom':
            key = 'custom'
        if key not in (*PERIOD_LABELS, 'custom'):
            key = 'all'
        filters[prefix + '_range'] = key
        start_value, end_value = filters[prefix + '_from'], filters[prefix + '_to']
        try:
            bounds[field] = period_bounds(key, today, start_value, end_value)
        except ValueError as error:
            errors.append(f'{label}: {error}')
        time_controls.append(dict(prefix=prefix, title=label, key=key, label=PERIOD_LABELS.get(key, 'Toàn thời gian'),
                                  start=datetime_input(start_value), end=datetime_input(end_value, end=True)))
    amounts = {}
    for key in ('min_fee', 'max_fee'):
        if filters[key]:
            try:
                amount = int(filters[key])
                if amount < 0:
                    raise ValueError
                amounts[key] = amount
            except ValueError:
                errors.append('Giá trị tổng phí phải là số nguyên không âm.')
    if amounts.get('min_fee', 0) > amounts.get('max_fee', float('inf')):
        errors.append('Tổng phí tối thiểu không được lớn hơn tổng phí tối đa.')
    keyword = filters['q'].casefold()
    normalized = plate_key(filters['q'])
    phone_query = re.sub(r'\D', '', filters['q']) if re.fullmatch(r'[+\d ().-]+', filters['q']) else ''

    def matches(customer):
        if errors:
            return False
        if keyword and not (any(keyword in str(customer[k] or '').casefold() for k in ('code', 'fullname', 'username', 'phone', 'email'))
                            or (phone_query and phone_query in re.sub(r'\D', '', customer['phone'] or ''))
                            or any(normalized and normalized in v['plate_key'] for v in customer['vehicles'])):
            return False
        if filters['group'] != 'all' and filters['group'] not in customer['groups']:
            return False
        if filters['status'] and customer['status'] != filters['status']:
            return False
        if filters['vehicle_type'] and not any(str(v['vehicle_type_id']) == filters['vehicle_type'] for v in customer['vehicles']):
            return False
        if not amounts.get('min_fee', 0) <= customer['total_fee'] <= amounts.get('max_fee', float('inf')):
            return False
        for field, (start, end) in bounds.items():
            if start:
                try:
                    if not start <= datetime.fromisoformat(customer[field]) < end:
                        return False
                except (TypeError, ValueError):
                    return False
        return True

    filtered = [c for c in all_customers if matches(c)]
    sort_field = {'code': 'id', 'name': 'fullname', 'fee': 'total_fee', 'vehicles': 'vehicle_count', 'monthly': 'monthly_count'}[filters['sort']]
    filtered.sort(key=lambda c: (str(c[sort_field]).casefold(), c['id']) if sort_field == 'fullname' else (c[sort_field], c['id']),
                  reverse=filters['direction'] == 'desc')
    try:
        per_page = int(args.get('per_page', 20))
    except (ValueError, TypeError):
        per_page = 20
    per_page = per_page if per_page in (20, 50, 100) else 20
    pages = max(1, (len(filtered) + per_page - 1) // per_page)
    try:
        page = int(args.get('page', 1))
        open_id = int(args.get('open', 0))
    except (ValueError, TypeError):
        page, open_id = 1, 0
    if open_id and not args.get('page'):
        page = next((i // per_page + 1 for i, c in enumerate(filtered) if c['id'] == open_id), page)
    page = min(pages, max(1, page))

    def query_string(**overrides):
        query = dict(filters, per_page=per_page)
        query.update(overrides)
        return urlencode({key: value for key, value in query.items() if value != ''})

    return dict(customers=filtered[(page - 1) * per_page:page * per_page], filtered_customers=filtered,
                customer_count=len(filtered), total_vehicle_count=sum(c['vehicle_count'] for c in filtered),
                total_monthly_count=sum(c['monthly_count'] for c in filtered), total_customer_fee=sum(c['total_fee'] for c in filtered),
                filters=filters, filter_errors=errors, groups=CUSTOMER_GROUPS, customer_time_controls=time_controls,
                period_groups=PERIOD_GROUPS, page=page, pages=pages, per_page=per_page, query_string=query_string,
                first_item=(page - 1) * per_page + 1 if filtered else 0, last_item=min(page * per_page, len(filtered)), open_customer_id=open_id)


def export_customers(customers):
    output = StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['Mã khách hàng', 'Họ tên', 'Tài khoản', 'Điện thoại', 'Email', 'Địa chỉ', 'Biển số',
                     'Số xe', 'Vé tháng còn hạn', 'Lượt gửi xe', 'Phí gửi xe', 'Tiền vé tháng', 'Tổng phí', 'Trạng thái'])
    for customer in customers:
        values = [customer['code'], customer['fullname'], customer['username'], customer['phone'] or '',
                  customer['email'] or '', customer['address'] or '', ', '.join(v['plate_number'] for v in customer['vehicles']),
                  customer['vehicle_count'], customer['monthly_count'], customer['visit_count'], customer['parking_fee'],
                  customer['monthly_fee'], customer['total_fee'], 'Hoạt động' if customer['status'] == 'active' else 'Đã khóa']
        writer.writerow(["'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value
                         for value in values])
    return output.getvalue().encode('utf-8-sig')
