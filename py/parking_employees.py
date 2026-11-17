"""Nghiệp vụ quản lý hồ sơ nhân viên và thiết lập lương theo giao diện KiotViet."""

import csv
import io
from datetime import datetime
from urllib.parse import urlencode

DEFAULT_DEPARTMENTS = (
    'Vận hành bãi xe',
    'Bảo vệ / Trực cổng',
    'Thu ngân',
    'Quản lý',
    'Kỹ thuật',
)

DEFAULT_POSITIONS = (
    'Nhân viên trực cổng',
    'Trưởng ca',
    'Thu ngân',
    'Kỹ thuật viên',
    'Quản trị viên',
)

SALARY_TYPES = (
    ('month', 'Lương cố định theo tháng'),
    ('shift', 'Theo ca trực'),
    ('hour', 'Theo giờ làm việc'),
    ('contract', 'Khoán'),
)

SALARY_TEMPLATES = (
    'Mặc định nhân viên trực cổng',
    'Ca đêm / Tăng ca',
    'Quản lý vận hành',
    'Tùy chỉnh',
)


def _clean_text(value, limit=255):
    return (value or '').strip()[:limit]


def _clean_int(value, default=0):
    raw = (value or '').strip().replace(',', '').replace('.', '')
    if not raw:
        return default
    try:
        num = int(raw)
        return num if num >= 0 else default
    except ValueError:
        return default


def _bool_flag(form, name):
    return 1 if form.get(name) in ('1', 'true', 'on', 'yes') else 0


def format_employee_code(user_row):
    code = (user_row['employee_code'] or '').strip() if 'employee_code' in user_row.keys() else ''
    return code or f"NV{user_row['id']:06d}"


def _initials(fullname, username):
    text = (fullname or username or 'NV').strip()
    parts = [p for p in text.split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return text[:2].upper()


def enrich_employee(row):
    item = dict(row)
    item['code'] = format_employee_code(row)
    item['initials'] = _initials(item.get('fullname'), item.get('username'))
    item['work_branch'] = item.get('work_branch') or 'Bãi xe trung tâm'
    item['pay_branch'] = item.get('pay_branch') or 'Bãi xe trung tâm'
    item['salary_amount'] = int(item.get('salary_amount') or 0)
    item['allowance_amount'] = int(item.get('allowance_amount') or 0)
    item['deduction_amount'] = int(item.get('deduction_amount') or 0)
    item['deduction_note'] = item.get('deduction_note') or ''
    allowance_add = item['allowance_amount'] if item.get('allowance_enabled') else 0
    deduction_sub = item['deduction_amount'] if item.get('deduction_enabled') else 0
    item['net_salary'] = max(0, item['salary_amount'] + allowance_add - deduction_sub)
    item['missing_setup'] = not (item.get('phone') and item.get('salary_type'))
    salary_map = dict(SALARY_TYPES)
    item['salary_type_label'] = salary_map.get(item.get('salary_type') or '', 'Chưa thiết lập')
    item['attendance'] = []
    item['shift_count'] = 0
    return item


def _format_attendance_row(row):
    item = dict(row)
    ci = item.get('check_in') or ''
    co = item.get('check_out') or ''
    item['check_in_label'] = ci[11:16] if len(ci) >= 16 else (ci or '—')
    item['check_out_label'] = co[11:16] if len(co) >= 16 else ('Đang trực' if item.get('status') == 'working' else (co or '—'))
    duration = '—'
    if len(ci) >= 16 and len(co) >= 16:
        try:
            mins = max(0, int((datetime.fromisoformat(co) - datetime.fromisoformat(ci)).total_seconds() // 60))
            duration = f"{mins // 60}h {mins % 60:02d}p"
        except ValueError:
            pass
    item['duration_label'] = duration
    status_labels = {
        'working': 'Đang trong ca',
        'completed': 'Hoàn thành',
        'late': 'Đi muộn',
        'leave': 'Nghỉ phép',
    }
    item['status_label'] = status_labels.get(item.get('status') or '', 'Hoàn thành')
    return item


def attach_attendance(employees, attendance_rows):
    by_user = {}
    for r in attendance_rows:
        by_user.setdefault(r['user_id'], []).append(_format_attendance_row(r))
    for emp in employees:
        records = by_user.get(emp['id'], [])
        emp['attendance'] = records
        emp['shift_count'] = len(records)


def parse_employee_form(form):
    """Trích xuất toàn bộ trường Thông tin + Thiết lập lương từ form nhân viên."""
    fullname = _clean_text(form.get('fullname'), 160)
    role = form.get('role', 'manager')
    if role not in ('manager', 'admin'):
        role = 'manager'

    data = {
        'fullname': fullname,
        'role': role,
        'employee_code': _clean_text(form.get('employee_code'), 32),
        'attendance_code': _clean_text(form.get('attendance_code'), 32),
        'phone': _clean_text(form.get('phone'), 32),
        'email': _clean_text(form.get('email'), 254),
        'address': _clean_text(form.get('address'), 500),
        'customer_note': _clean_text(form.get('customer_note') or form.get('note'), 2000),
        'department': _clean_text(form.get('department'), 120),
        'position': _clean_text(form.get('position'), 120),
        'work_branch': _clean_text(form.get('work_branch'), 120) or 'Bãi xe trung tâm',
        'pay_branch': _clean_text(form.get('pay_branch'), 120) or 'Bãi xe trung tâm',
        'start_date': _clean_text(form.get('start_date'), 20),
        'id_card': _clean_text(form.get('id_card'), 32),
        'gender': form.get('gender') if form.get('gender') in ('Nam', 'Nữ') else '',
        'dob': _clean_text(form.get('dob'), 20),
        'bank_account': _clean_text(form.get('bank_account'), 64),
        'bank_name': _clean_text(form.get('bank_name'), 120),
        'bank_holder': _clean_text(form.get('bank_holder'), 160),
        'salary_type': form.get('salary_type') if form.get('salary_type') in dict(SALARY_TYPES) else '',
        'salary_amount': _clean_int(form.get('salary_amount'), 0),
        'salary_template': _clean_text(form.get('salary_template'), 120),
        'allowance_enabled': _bool_flag(form, 'allowance_enabled'),
        'allowance_amount': _clean_int(form.get('allowance_amount'), 0),
        'deduction_enabled': _bool_flag(form, 'deduction_enabled'),
        'deduction_amount': _clean_int(form.get('deduction_amount'), 0),
        'deduction_note': _clean_text(form.get('deduction_note'), 255),
    }
    return data


def employee_context(staff_rows, args):
    """Lọc, sắp xếp, phân trang danh sách nhân viên cho trang /accounts."""
    employees = [enrich_employee(r) for r in staff_rows]

    q = (args.get('q') or '').strip().lower()
    status = args.get('status') or ''
    department = (args.get('department') or '').strip()
    position = (args.get('position') or '').strip()
    role = args.get('role') or ''

    departments = sorted({e['department'] for e in employees if e.get('department')} | set(DEFAULT_DEPARTMENTS))
    positions = sorted({e['position'] for e in employees if e.get('position')} | set(DEFAULT_POSITIONS))

    filtered = []
    for emp in employees:
        if status in ('active', 'locked') and emp['status'] != status:
            continue
        if department and (emp.get('department') or '') != department:
            continue
        if position and (emp.get('position') or '') != position:
            continue
        if role in ('admin', 'manager') and emp['role'] != role:
            continue
        if q:
            haystack = ' '.join([
                emp['code'],
                emp.get('attendance_code') or '',
                emp.get('fullname') or '',
                emp.get('username') or '',
                emp.get('phone') or '',
                emp.get('id_card') or '',
            ]).lower()
            if q not in haystack:
                continue
        filtered.append(emp)

    sort = args.get('sort') or 'id'
    direction = args.get('direction') or 'asc'
    reverse = (direction == 'desc')
    sort_keys = {
        'code': lambda e: e['code'],
        'name': lambda e: (e.get('fullname') or '').lower(),
        'role': lambda e: e.get('role') or '',
        'id': lambda e: e['id'],
    }
    filtered.sort(key=sort_keys.get(sort, sort_keys['id']), reverse=reverse)

    try:
        per_page = int(args.get('per_page', 20))
    except ValueError:
        per_page = 20
    if per_page not in (20, 50, 100):
        per_page = 20

    total = len(filtered)
    pages = max(1, (total + per_page - 1) // per_page)
    try:
        page = int(args.get('page', 1))
    except ValueError:
        page = 1
    page = max(1, min(page, pages))
    start = (page - 1) * per_page
    paged = filtered[start:start + per_page]

    open_id = args.get('open', '')
    try:
        open_employee_id = int(open_id) if open_id else None
    except ValueError:
        open_employee_id = None

    filters = {
        'q': args.get('q') or '',
        'status': status,
        'department': department,
        'position': position,
        'role': role,
        'sort': sort,
        'direction': direction,
    }

    def query_string(**overrides):
        query = dict(filters, per_page=per_page)
        query.update(overrides)
        return urlencode({key: value for key, value in query.items() if value != ''})

    return {
        'employees': paged,
        'filtered_employees': filtered,
        'staff_count': total,
        'total_staff_count': len(employees),
        'departments': departments,
        'positions': positions,
        'salary_types': SALARY_TYPES,
        'salary_templates': SALARY_TEMPLATES,
        'filters': filters,
        'query_string': query_string,
        'page': page,
        'pages': pages,
        'per_page': per_page,
        'first_item': start + 1 if total else 0,
        'last_item': min(start + per_page, total),
        'open_employee_id': open_employee_id,
    }


def export_employees(rows):
    buf = io.StringIO()
    buf.write('\ufeff')
    writer = csv.writer(buf)
    writer.writerow([
        'Mã nhân viên', 'Mã chấm công', 'Tên nhân viên', 'Tên đăng nhập',
        'Vai trò', 'Trạng thái', 'Số điện thoại', 'Số CMND/CCCD',
        'Phòng ban', 'Chức danh', 'Loại lương', 'Mức lương (VNĐ)', 'Ghi chú'
    ])
    for e in rows:
        writer.writerow([
            e['code'],
            e.get('attendance_code') or '',
            e.get('fullname') or '',
            e.get('username') or '',
            'Quản trị viên' if e.get('role') == 'admin' else 'Nhân viên vận hành',
            'Đang làm việc' if e.get('status') == 'active' else 'Đã nghỉ',
            e.get('phone') or '',
            e.get('id_card') or '',
            e.get('department') or '',
            e.get('position') or '',
            e.get('salary_type_label') or '',
            e.get('salary_amount') or 0,
            e.get('customer_note') or '',
        ])
    return buf.getvalue().encode('utf-8')
