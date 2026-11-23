"""Nghiệp vụ quản lý hồ sơ nhân viên và thiết lập lương theo giao diện KiotViet."""

import csv
import io
import os
from datetime import datetime
from urllib.parse import urlencode
from xml.sax.saxutils import escape

from config import FONTS_DIR

try:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    OPENPYXL_ERROR = None
except ImportError as _e:  # pragma: no cover
    OPENPYXL_ERROR = _e

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    REPORTLAB_ERROR = None
except ImportError as _e:  # pragma: no cover
    REPORTLAB_ERROR = _e

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

SALARY_UNITS = {
    'month': '/tháng',
    'shift': '/ca',
    'hour': '/giờ',
    'contract': '/khoán',
}

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


def _recalculate_payroll(emp):
    """Tính lương theo công/giờ/tháng + phụ cấp - giảm trừ cho một nhân viên."""
    salary_type = emp.get('salary_type') or ''
    salary_amount = int(emp.get('salary_amount') or 0)
    worked_shifts = int(emp.get('worked_shifts') or 0)
    worked_minutes = int(emp.get('worked_minutes') or 0)

    if salary_type == 'shift':
        base_earned = salary_amount * worked_shifts
    elif salary_type == 'hour':
        base_earned = round(salary_amount * (worked_minutes / 60.0))
    else:
        base_earned = salary_amount

    allowance_add = emp['allowance_amount'] if emp.get('allowance_enabled') else 0
    deduction_sub = emp['deduction_amount'] if emp.get('deduction_enabled') else 0
    emp['allowance_add'] = allowance_add
    emp['deduction_sub'] = deduction_sub
    emp['base_earned'] = base_earned
    emp['net_salary'] = max(0, base_earned + allowance_add - deduction_sub)
    emp['has_salary_config'] = bool(salary_amount or emp.get('allowance_enabled') or emp.get('deduction_enabled'))


def enrich_employee(row):
    item = dict(row)
    item['code'] = format_employee_code(row)
    item['initials'] = _initials(item.get('fullname'), item.get('username'))
    item['work_branch'] = item.get('work_branch') or 'Cổng chính'
    item['work_branches_list'] = [b.strip() for b in item['work_branch'].split(',') if b.strip()] or ['Cổng chính']
    item['pay_branch'] = item.get('pay_branch') or 'Cổng chính'
    item['salary_amount'] = int(item.get('salary_amount') or 0)
    item['allowance_amount'] = int(item.get('allowance_amount') or 0)
    item['deduction_amount'] = int(item.get('deduction_amount') or 0)
    item['deduction_note'] = item.get('deduction_note') or ''
    item['missing_setup'] = not (item.get('phone') and item.get('salary_type'))
    salary_map = dict(SALARY_TYPES)
    item['salary_type_label'] = salary_map.get(item.get('salary_type') or '', 'Chưa thiết lập')
    item['salary_unit_label'] = SALARY_UNITS.get(item.get('salary_type') or '', '')
    item['attendance'] = []
    item['shift_count'] = 0
    item['worked_shifts'] = 0
    item['worked_minutes'] = 0
    item['worked_hours'] = 0.0
    item['worked_hours_label'] = '0h 00p'
    _recalculate_payroll(item)
    return item


def _format_attendance_row(row):
    item = dict(row)
    ci = item.get('check_in') or ''
    co = item.get('check_out') or ''
    item['check_in_label'] = ci[11:16] if len(ci) >= 16 else (ci or '—')
    item['check_out_label'] = co[11:16] if len(co) >= 16 else ('Đang trực' if item.get('status') == 'working' else (co or '—'))
    duration = '—'
    mins = 0
    if len(ci) >= 16 and len(co) >= 16:
        try:
            mins = max(0, int((datetime.fromisoformat(co) - datetime.fromisoformat(ci)).total_seconds() // 60))
            duration = f"{mins // 60}h {mins % 60:02d}p"
        except ValueError:
            mins = 0
    item['duration_minutes'] = mins
    item['duration_label'] = duration
    status_labels = {
        'working': 'Đang trong ca',
        'completed': 'Hoàn thành',
        'late': 'Đi muộn',
        'leave': 'Nghỉ phép',
    }
    item['status_label'] = status_labels.get(item.get('status') or '', 'Hoàn thành')
    return item


def attach_attendance(employees, attendance_rows, month=''):
    month = (month or '').strip()
    by_user = {}
    for r in attendance_rows:
        if month and not (r['work_date'] or '').startswith(month):
            continue
        by_user.setdefault(r['user_id'], []).append(_format_attendance_row(r))
    for emp in employees:
        records = by_user.get(emp['id'], [])
        worked = [r for r in records if r.get('status') != 'leave']
        worked_minutes = sum(r.get('duration_minutes', 0) for r in worked)
        emp['attendance'] = records
        emp['shift_count'] = len(records)
        emp['worked_shifts'] = len(worked)
        emp['worked_minutes'] = worked_minutes
        emp['worked_hours'] = round(worked_minutes / 60.0, 2)
        emp['worked_hours_label'] = f"{worked_minutes // 60}h {worked_minutes % 60:02d}p"
        _recalculate_payroll(emp)


def parse_employee_form(form):
    """Trích xuất toàn bộ trường Thông tin + Thiết lập lương từ form nhân viên."""
    fullname = _clean_text(form.get('fullname'), 160)
    role = form.get('role', 'manager')
    if role not in ('manager', 'admin'):
        role = 'manager'

    raw_branches = [p.strip() for item in form.getlist('work_branch') for p in (item or '').split(',') if p.strip()]
    seen_wb = []
    for b in raw_branches:
        if b not in seen_wb:
            seen_wb.append(b)
    work_branch_val = ', '.join(seen_wb)[:240] if seen_wb else 'Cổng chính'

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
        'work_branch': work_branch_val,
        'pay_branch': _clean_text(form.get('pay_branch'), 120) or 'Cổng chính',
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


def employee_context(staff_rows, args, active_gates=None):
    """Lọc, sắp xếp, phân trang danh sách nhân viên cho trang /accounts."""
    employees = [enrich_employee(r) for r in staff_rows]

    q = (args.get('q') or '').strip().lower()
    status = args.get('status') or ''
    department = (args.get('department') or '').strip()
    position = (args.get('position') or '').strip()
    raw_wb_filters = args.getlist('work_branch') if hasattr(args, 'getlist') else ([args.get('work_branch')] if args.get('work_branch') else [])
    selected_work_branches = []
    for item in raw_wb_filters:
        for part in (item or '').split(','):
            p = part.strip()
            if p and p.lower() not in ('tất cả các cổng', 'tat ca cac cong') and p not in selected_work_branches:
                selected_work_branches.append(p)
    work_branch = ','.join(selected_work_branches)
    role = args.get('role') or ''

    departments = sorted({e['department'] for e in employees if e.get('department')} | set(DEFAULT_DEPARTMENTS))
    positions = sorted({e['position'] for e in employees if e.get('position')} | set(DEFAULT_POSITIONS))
    gate_choices = ['Cổng chính']
    for g in (active_gates or []):
        gname = (dict(g).get('name') or '').strip() if not isinstance(g, str) else g.strip()
        if gname and gname.lower() not in ('cổng chính', 'cong chinh') and gname not in gate_choices:
            gate_choices.append(gname)
    work_branches = list(dict.fromkeys(gate_choices + [b for e in employees for b in e.get('work_branches_list', [])]))

    def _matches_gate_filter(emp_branches, filter_gates):
        if not filter_gates:
            return True
        central_aliases = {'cổng chính', 'cong chinh', 'trung tâm', 'trung tam', 'bãi xe trung tâm'}
        emp_norm = {b.strip().lower() for b in emp_branches if b.strip()}
        for fg in filter_gates:
            fg_l = fg.strip().lower()
            if fg_l in central_aliases:
                if emp_norm & central_aliases:
                    return True
            elif fg_l in emp_norm:
                return True
        return False

    filtered = []
    for emp in employees:
        if status in ('active', 'locked') and emp['status'] != status:
            continue
        if department and (emp.get('department') or '') != department:
            continue
        if position and (emp.get('position') or '') != position:
            continue
        if selected_work_branches and not _matches_gate_filter(emp.get('work_branches_list', []), selected_work_branches):
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
        'salary': lambda e: e.get('salary_amount') or 0,
        'net_salary': lambda e: e.get('net_salary') or 0,
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

    month = (args.get('month') or '').strip()
    if month and (len(month) != 7 or month[4] != '-'):
        month = ''

    filters = {
        'q': args.get('q') or '',
        'status': status,
        'department': department,
        'position': position,
        'work_branch': work_branch,
        'role': role,
        'month': month,
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
        'work_branches': work_branches,
        'gate_choices': gate_choices,
        'selected_work_branches': selected_work_branches,
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


def payroll_totals(employees):
    return {
        'count': len(employees),
        'base_earned': sum(int(e.get('base_earned') or 0) for e in employees),
        'allowance': sum(int(e.get('allowance_add') or 0) for e in employees),
        'deduction': sum(int(e.get('deduction_sub') or 0) for e in employees),
        'net_salary': sum(int(e.get('net_salary') or 0) for e in employees),
        'worked_shifts': sum(int(e.get('worked_shifts') or 0) for e in employees),
        'worked_minutes': sum(int(e.get('worked_minutes') or 0) for e in employees),
    }


def export_employees(rows):
    buf = io.StringIO()
    buf.write('\ufeff')
    writer = csv.writer(buf)
    writer.writerow([
        'Mã nhân viên', 'Mã chấm công', 'Tên nhân viên', 'Tên đăng nhập',
        'Vai trò', 'Trạng thái', 'Số điện thoại', 'Số CMND/CCCD',
        'Loại lương', 'Mức lương (VNĐ)',
        'Phụ cấp (VNĐ)', 'Giảm trừ (VNĐ)', 'Thực nhận (VNĐ)', 'Ghi chú'
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
            e.get('salary_type_label') or '',
            e.get('salary_amount') or 0,
            e.get('allowance_add') or 0,
            e.get('deduction_sub') or 0,
            e.get('net_salary') or 0,
            e.get('customer_note') or '',
        ])
    return buf.getvalue().encode('utf-8')


def export_employees_file(rows, fmt='csv', generated_by='Admin'):
    """Xuất danh sách nhân viên ra CSV (.csv), Excel (.xlsx) hoặc PDF (.pdf)."""
    fmt = (fmt or 'csv').lower()
    if fmt == 'xlsx':
        return (
            _export_employees_xlsx(rows, generated_by),
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'xlsx',
        )
    if fmt == 'pdf':
        return _export_employees_pdf(rows, generated_by), 'application/pdf', 'pdf'
    return export_employees(rows), 'text/csv; charset=utf-8', 'csv'


def _export_employees_xlsx(rows, generated_by='Admin'):
    if OPENPYXL_ERROR is not None:
        raise RuntimeError(f'Thiếu thư viện openpyxl: {OPENPYXL_ERROR}')
    wb = Workbook()
    ws = wb.active
    ws.title = 'Nhan vien'
    ws.views.sheetView[0].showGridLines = True

    navy_fill = PatternFill('solid', fgColor='FF14306B')
    alt_fill = PatternFill('solid', fgColor='FFF5F7FC')
    thin = Side(style='thin', color='FFD9DCE1')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    money_fmt = '#,##0" đ"'

    ws.merge_cells('A1:N1')
    ws['A1'] = 'DANH SÁCH NHÂN VIÊN'
    ws['A1'].font = Font(name='Calibri', size=15, bold=True, color='FF14306B')
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 28

    ws.merge_cells('A2:N2')
    ws['A2'] = (
        f"Thời điểm xuất: {datetime.now().strftime('%d/%m/%Y %H:%M')}  |  "
        f"Người xuất: {generated_by}  |  Tổng nhân viên: {len(rows)}"
    )
    ws['A2'].font = Font(name='Calibri', size=10, italic=True, color='FF525E70')
    ws['A2'].alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[2].height = 20

    headers = [
        'Mã nhân viên', 'Mã chấm công', 'Tên nhân viên', 'Tên đăng nhập',
        'Vai trò', 'Trạng thái', 'Số điện thoại', 'Số CMND/CCCD',
        'Loại lương', 'Mức lương',
        'Phụ cấp', 'Giảm trừ', 'Thực nhận', 'Ghi chú'
    ]
    header_row = 4
    ws.row_dimensions[header_row].height = 26
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=h)
        cell.font = Font(name='Calibri', size=10, bold=True, color='FFFFFFFF')
        cell.fill = navy_fill
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = border

    money_cols = {10, 11, 12, 13}
    center_cols = {1, 2, 6, 7, 8}
    for idx, e in enumerate(rows, 1):
        r = header_row + idx
        ws.row_dimensions[r].height = 21
        values = [
            e['code'],
            e.get('attendance_code') or '',
            e.get('fullname') or '',
            e.get('username') or '',
            'Quản trị viên' if e.get('role') == 'admin' else 'Nhân viên vận hành',
            'Đang làm việc' if e.get('status') == 'active' else 'Đã nghỉ',
            e.get('phone') or '',
            e.get('id_card') or '',
            e.get('salary_type_label') or '',
            e.get('salary_amount') or 0,
            e.get('allowance_add') or 0,
            e.get('deduction_sub') or 0,
            e.get('net_salary') or 0,
            e.get('customer_note') or '',
        ]
        for col_idx, val in enumerate(values, 1):
            cell = ws.cell(row=r, column=col_idx, value=val)
            cell.border = border
            cell.font = Font(
                name='Calibri',
                size=10,
                bold=(col_idx == 13),
                color='FF188246' if col_idx == 13 else 'FF1D2433',
            )
            if idx % 2 == 0:
                cell.fill = alt_fill
            if col_idx in money_cols:
                cell.number_format = money_fmt
                cell.alignment = Alignment(horizontal='right', vertical='center')
            elif col_idx in center_cols:
                cell.alignment = Alignment(horizontal='center', vertical='center')
            else:
                cell.alignment = Alignment(horizontal='left', vertical='center')

    widths = [13, 14, 24, 16, 20, 15, 14, 15, 22, 16, 15, 15, 17, 24]
    for idx, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(idx)].width = w

    ws.freeze_panes = 'A5'
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _export_employees_pdf(rows, generated_by='Admin'):
    if REPORTLAB_ERROR is not None:
        raise RuntimeError(f'Thiếu thư viện reportlab: {REPORTLAB_ERROR}')
    reg_font, bold_font = _register_pdf_fonts()

    navy = colors.HexColor('#14306B')
    line = colors.HexColor('#D9DCE1')
    alt = colors.HexColor('#F5F7FC')
    text_c = colors.HexColor('#1D2433')
    muted_c = colors.HexColor('#525E70')
    green_c = colors.HexColor('#188246')

    st_title = ParagraphStyle('e_title', fontName=bold_font, fontSize=14, leading=18, textColor=navy, alignment=TA_CENTER)
    st_sub = ParagraphStyle('e_sub', fontName=reg_font, fontSize=8.5, leading=12, textColor=muted_c, alignment=TA_CENTER)
    st_th = ParagraphStyle('e_th', fontName=bold_font, fontSize=8, leading=10, textColor=colors.white, alignment=TA_CENTER)
    st_c = ParagraphStyle('e_c', fontName=reg_font, fontSize=7.8, leading=10, textColor=text_c)
    st_cc = ParagraphStyle('e_cc', parent=st_c, alignment=TA_CENTER)
    st_cr = ParagraphStyle('e_cr', parent=st_c, alignment=TA_RIGHT)
    st_net = ParagraphStyle('e_net', parent=st_cr, fontName=bold_font, textColor=green_c)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm, title='Danh sách nhân viên', author=generated_by,
    )

    story = [
        Paragraph('DANH SÁCH NHÂN VIÊN', st_title),
        Paragraph(
            f"Ngày xuất: {datetime.now().strftime('%d/%m/%Y %H:%M')} · "
            f"Người xuất: {escape(generated_by)} · Số nhân viên: {len(rows)}",
            st_sub,
        ),
        Spacer(1, 8),
    ]

    headers = [
        'Mã NV', 'Mã CC', 'Họ và tên', 'SĐT',
        'Vai trò', 'Trạng thái', 'Hình thức lương', 'Mức lương', 'Thực nhận'
    ]
    data = [[Paragraph(h, st_th) for h in headers]]
    for e in rows:
        role_lbl = 'Quản trị viên' if e.get('role') == 'admin' else 'Nhân viên'
        status_lbl = 'Đang làm' if e.get('status') == 'active' else 'Đã nghỉ'
        rate_str = (_fmt_vnd(e.get('salary_amount') or 0) + (e.get('salary_unit_label') or '')) if e.get('salary_amount') else '—'
        net_str = _fmt_vnd(e.get('net_salary') or 0) if e.get('has_salary_config') else '—'
        data.append([
            Paragraph(escape(e['code']), st_cc),
            Paragraph(escape(e.get('attendance_code') or '—'), st_cc),
            Paragraph(escape(e.get('fullname') or ''), st_c),
            Paragraph(escape(e.get('phone') or '—'), st_cc),
            Paragraph(escape(role_lbl), st_cc),
            Paragraph(escape(status_lbl), st_cc),
            Paragraph(escape(e.get('salary_type_label') or '—'), st_c),
            Paragraph(escape(rate_str), st_cr),
            Paragraph(escape(net_str), st_net),
        ])

    col_widths = [22*mm, 20*mm, 54*mm, 28*mm, 28*mm, 24*mm, 42*mm, 29*mm, 30*mm]
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), navy),
        ('GRID', (0, 0), (-1, -1), 0.4, line),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]
    for r_i in range(1, len(data)):
        if r_i % 2 == 0:
            style_cmds.append(('BACKGROUND', (0, r_i), (-1, r_i), alt))
    tbl.setStyle(TableStyle(style_cmds))
    story.append(tbl)

    doc.build(story)
    return buf.getvalue()


def _fmt_vnd(value):
    return f"{int(value or 0):,}".replace(',', '.') + ' đ'


def _period_label(month):
    if month and len(month) == 7 and '-' in month:
        y, m = month.split('-', 1)
        return f"Tháng {m}/{y}"
    return "Tất cả kỳ chấm công"


def export_payroll(rows, fmt='xlsx', month='', generated_by='Admin'):
    """Xuất bảng lương nhân viên ra Excel (.xlsx), PDF (.pdf) hoặc CSV (.csv)."""
    fmt = (fmt or 'xlsx').lower()
    if fmt == 'csv':
        return _export_payroll_csv(rows, month), 'text/csv; charset=utf-8', 'csv'
    if fmt == 'pdf':
        return _export_payroll_pdf(rows, month, generated_by), 'application/pdf', 'pdf'
    return (
        _export_payroll_xlsx(rows, month, generated_by),
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'xlsx',
    )


def _export_payroll_csv(rows, month=''):
    totals = payroll_totals(rows)
    buf = io.StringIO()
    buf.write('\ufeff')
    writer = csv.writer(buf)
    writer.writerow([f'BẢNG LƯƠNG NHÂN VIÊN - {_period_label(month)}'])
    writer.writerow([
        'STT', 'Mã NV', 'Mã chấm công', 'Họ và tên',
        'Hình thức lương', 'Mức lương (VNĐ)', 'Số ca', 'Giờ làm',
        'Lương theo công (VNĐ)', 'Phụ cấp (VNĐ)', 'Giảm trừ (VNĐ)',
        'Lý do giảm trừ', 'Thực nhận (VNĐ)', 'Số tài khoản', 'Ngân hàng', 'Chủ tài khoản'
    ])
    for idx, e in enumerate(rows, 1):
        writer.writerow([
            idx,
            e['code'],
            e.get('attendance_code') or '',
            e.get('fullname') or '',
            e.get('salary_type_label') or '',
            e.get('salary_amount') or 0,
            e.get('worked_shifts') or 0,
            e.get('worked_hours_label') or '0h 00p',
            e.get('base_earned') or 0,
            e.get('allowance_add') or 0,
            e.get('deduction_sub') or 0,
            e.get('deduction_note') or '',
            e.get('net_salary') or 0,
            e.get('bank_account') or '',
            e.get('bank_name') or '',
            e.get('bank_holder') or '',
        ])
    writer.writerow([
        '', '', '', 'TỔNG CỘNG', '', '',
        totals['worked_shifts'], '', totals['base_earned'],
        totals['allowance'], totals['deduction'], '', totals['net_salary'],
        '', '', ''
    ])
    return buf.getvalue().encode('utf-8')


def _export_payroll_xlsx(rows, month='', generated_by='Admin'):
    if OPENPYXL_ERROR is not None:
        raise RuntimeError(f'Thiếu thư viện openpyxl: {OPENPYXL_ERROR}')
    totals = payroll_totals(rows)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Bang luong'
    ws.views.sheetView[0].showGridLines = True

    navy_fill = PatternFill('solid', fgColor='FF14306B')
    alt_fill = PatternFill('solid', fgColor='FFF5F7FC')
    total_fill = PatternFill('solid', fgColor='FFE8F0FE')
    thin = Side(style='thin', color='FFD9DCE1')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    money_fmt = '#,##0" đ"'

    ws.merge_cells('A1:P1')
    ws['A1'] = 'BẢNG LƯƠNG NHÂN VIÊN'
    ws['A1'].font = Font(name='Calibri', size=15, bold=True, color='FF14306B')
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[1].height = 28

    ws.merge_cells('A2:P2')
    ws['A2'] = (
        f"Kỳ lương: {_period_label(month)}  |  "
        f"Thời điểm xuất: {datetime.now().strftime('%d/%m/%Y %H:%M')}  |  "
        f"Người xuất: {generated_by}  |  Tổng nhân viên: {totals['count']}"
    )
    ws['A2'].font = Font(name='Calibri', size=10, italic=True, color='FF525E70')
    ws['A2'].alignment = Alignment(horizontal='center', vertical='center')
    ws.row_dimensions[2].height = 20

    headers = [
        'STT', 'Mã NV', 'Mã chấm công', 'Họ và tên',
        'Hình thức lương', 'Mức lương', 'Số ca', 'Tổng giờ làm',
        'Lương theo công', 'Phụ cấp', 'Giảm trừ', 'Lý do giảm trừ',
        'Thực nhận', 'Số tài khoản', 'Ngân hàng', 'Chủ tài khoản'
    ]
    header_row = 4
    ws.row_dimensions[header_row].height = 26
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=h)
        cell.font = Font(name='Calibri', size=10, bold=True, color='FFFFFFFF')
        cell.fill = navy_fill
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = border

    money_cols = {6, 9, 10, 11, 13}
    center_cols = {1, 2, 3, 7, 8}

    for idx, e in enumerate(rows, 1):
        r = header_row + idx
        ws.row_dimensions[r].height = 21
        values = [
            idx,
            e['code'],
            e.get('attendance_code') or '',
            e.get('fullname') or '',
            e.get('salary_type_label') or '',
            e.get('salary_amount') or 0,
            e.get('worked_shifts') or 0,
            e.get('worked_hours_label') or '0h 00p',
            e.get('base_earned') or 0,
            e.get('allowance_add') or 0,
            e.get('deduction_sub') or 0,
            e.get('deduction_note') or '',
            e.get('net_salary') or 0,
            e.get('bank_account') or '',
            e.get('bank_name') or '',
            e.get('bank_holder') or '',
        ]
        for col_idx, val in enumerate(values, 1):
            cell = ws.cell(row=r, column=col_idx, value=val)
            cell.border = border
            cell.font = Font(
                name='Calibri',
                size=10,
                bold=(col_idx == 13),
                color='FF188246' if col_idx == 13 else 'FF1D2433',
            )
            if idx % 2 == 0:
                cell.fill = alt_fill
            if col_idx in money_cols:
                cell.number_format = money_fmt
                cell.alignment = Alignment(horizontal='right', vertical='center')
            elif col_idx in center_cols:
                cell.alignment = Alignment(horizontal='center', vertical='center')
            else:
                cell.alignment = Alignment(horizontal='left', vertical='center')

    total_row = header_row + len(rows) + 1
    ws.row_dimensions[total_row].height = 24
    total_values = {
        4: 'TỔNG CỘNG',
        7: totals['worked_shifts'],
        9: totals['base_earned'],
        10: totals['allowance'],
        11: totals['deduction'],
        13: totals['net_salary'],
    }
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=total_row, column=col_idx, value=total_values.get(col_idx, ''))
        cell.fill = total_fill
        cell.border = border
        cell.font = Font(name='Calibri', size=10.5, bold=True, color='FF14306B')
        if col_idx in money_cols and col_idx in total_values:
            cell.number_format = money_fmt
            cell.alignment = Alignment(horizontal='right', vertical='center')
        elif col_idx in center_cols:
            cell.alignment = Alignment(horizontal='center', vertical='center')
        else:
            cell.alignment = Alignment(horizontal='left', vertical='center')

    widths = [6, 12, 14, 24, 20, 18, 22, 16, 8, 12, 17, 15, 15, 22, 18, 18, 15, 22]
    for idx, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(idx)].width = w

    ws.freeze_panes = 'A5'
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _register_pdf_fonts():
    reg_path = os.path.join(FONTS_DIR, 'DejaVuSans.ttf')
    bold_path = os.path.join(FONTS_DIR, 'DejaVuSans-Bold.ttf')
    if 'VietFont' not in pdfmetrics.getRegisteredFontNames() and os.path.isfile(reg_path):
        pdfmetrics.registerFont(TTFont('VietFont', reg_path))
    if 'VietFont-Bold' not in pdfmetrics.getRegisteredFontNames() and os.path.isfile(bold_path):
        pdfmetrics.registerFont(TTFont('VietFont-Bold', bold_path))
    if 'VietFont' in pdfmetrics.getRegisteredFontNames() and 'VietFont-Bold' in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFontFamily(
            'VietFont',
            normal='VietFont',
            bold='VietFont-Bold',
            italic='VietFont',
            boldItalic='VietFont-Bold',
        )
    reg = 'VietFont' if 'VietFont' in pdfmetrics.getRegisteredFontNames() else 'Helvetica'
    bold = 'VietFont-Bold' if 'VietFont-Bold' in pdfmetrics.getRegisteredFontNames() else 'Helvetica-Bold'
    return reg, bold


def _export_payroll_pdf(rows, month='', generated_by='Admin'):
    if REPORTLAB_ERROR is not None:
        raise RuntimeError(f'Thiếu thư viện reportlab: {REPORTLAB_ERROR}')
    reg_font, bold_font = _register_pdf_fonts()
    totals = payroll_totals(rows)

    navy = colors.HexColor('#14306B')
    line = colors.HexColor('#D9DCE1')
    alt = colors.HexColor('#F5F7FC')
    total_bg = colors.HexColor('#E8F0FE')
    text_c = colors.HexColor('#1D2433')
    muted_c = colors.HexColor('#525E70')
    green_c = colors.HexColor('#188246')

    st_title = ParagraphStyle('p_title', fontName=bold_font, fontSize=14, leading=18, textColor=navy, alignment=TA_CENTER)
    st_sub = ParagraphStyle('p_sub', fontName=reg_font, fontSize=8.5, leading=12, textColor=muted_c, alignment=TA_CENTER)
    st_th = ParagraphStyle('p_th', fontName=bold_font, fontSize=8, leading=10, textColor=colors.white, alignment=TA_CENTER)
    st_c = ParagraphStyle('p_c', fontName=reg_font, fontSize=7.8, leading=10, textColor=text_c)
    st_cc = ParagraphStyle('p_cc', parent=st_c, alignment=TA_CENTER)
    st_cr = ParagraphStyle('p_cr', parent=st_c, alignment=TA_RIGHT)
    st_net = ParagraphStyle('p_net', parent=st_cr, fontName=bold_font, textColor=green_c)
    st_tot = ParagraphStyle('p_tot', fontName=bold_font, fontSize=8.2, leading=10.5, textColor=navy, alignment=TA_RIGHT)
    st_tot_l = ParagraphStyle('p_tot_l', parent=st_tot, alignment=TA_CENTER)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm, title='Bảng lương nhân viên', author=generated_by,
    )

    story = [
        Paragraph('BẢNG LƯƠNG NHÂN VIÊN', st_title),
        Paragraph(
            f"Kỳ lương: {escape(_period_label(month))} · Ngày xuất: {datetime.now().strftime('%d/%m/%Y %H:%M')} · "
            f"Người xuất: {escape(generated_by)} · Số nhân viên: {totals['count']}",
            st_sub,
        ),
        Spacer(1, 8),
    ]

    headers = [
        'STT', 'Mã NV', 'Họ và tên',
        'Hình thức', 'Mức lương', 'Công', 'Lương công',
        'Phụ cấp', 'Giảm trừ', 'Thực nhận', 'Tài khoản NH'
    ]
    data = [[Paragraph(h, st_th) for h in headers]]
    for idx, e in enumerate(rows, 1):
        bank_info = ' '.join(p for p in [e.get('bank_name') or '', e.get('bank_account') or ''] if p) or '—'
        rate_str = _fmt_vnd(e.get('salary_amount') or 0) + (e.get('salary_unit_label') or '')
        work_str = f"{e.get('worked_shifts') or 0} ca\n{e.get('worked_hours_label') or '0h 00p'}"
        data.append([
            Paragraph(str(idx), st_cc),
            Paragraph(escape(e['code']), st_cc),
            Paragraph(escape(e.get('fullname') or ''), st_c),
            Paragraph(escape(e.get('salary_type_label') or ''), st_c),
            Paragraph(escape(rate_str), st_cr),
            Paragraph(escape(work_str), st_cc),
            Paragraph(escape(_fmt_vnd(e.get('base_earned') or 0)), st_cr),
            Paragraph(escape(_fmt_vnd(e.get('allowance_add') or 0)), st_cr),
            Paragraph(escape(_fmt_vnd(e.get('deduction_sub') or 0)), st_cr),
            Paragraph(escape(_fmt_vnd(e.get('net_salary') or 0)), st_net),
            Paragraph(escape(bank_info), st_c),
        ])

    data.append([
        Paragraph('', st_tot_l),
        Paragraph('', st_tot_l),
        Paragraph('TỔNG CỘNG', st_tot_l),
        Paragraph('', st_tot_l),
        Paragraph('', st_tot),
        Paragraph(f"{totals['worked_shifts']} ca", st_tot_l),
        Paragraph(escape(_fmt_vnd(totals['base_earned'])), st_tot),
        Paragraph(escape(_fmt_vnd(totals['allowance'])), st_tot),
        Paragraph(escape(_fmt_vnd(totals['deduction'])), st_tot),
        Paragraph(escape(_fmt_vnd(totals['net_salary'])), st_tot),
        Paragraph('', st_tot_l),
    ])

    col_widths = [11*mm, 21*mm, 48*mm, 30*mm, 26*mm, 20*mm, 26*mm, 22*mm, 22*mm, 26*mm, 25*mm]
    tbl = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), navy),
        ('GRID', (0, 0), (-1, -1), 0.4, line),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('BACKGROUND', (0, -1), (-1, -1), total_bg),
        ('LINEABOVE', (0, -1), (-1, -1), 1, navy),
    ]
    for r_i in range(1, len(data) - 1):
        if r_i % 2 == 0:
            style_cmds.append(('BACKGROUND', (0, r_i), (-1, r_i), alt))
    tbl.setStyle(TableStyle(style_cmds))
    story.append(tbl)
    story.append(Spacer(1, 14))

    sig_data = [[
        Paragraph('<b>Người lập biểu</b><br/><i>(Ký, ghi rõ họ tên)</i>', st_cc),
        Paragraph('<b>Kế toán / Quản lý</b><br/><i>(Ký, ghi rõ họ tên)</i>', st_cc),
        Paragraph('<b>Giám đốc phê duyệt</b><br/><i>(Ký, đóng dấu)</i>', st_cc),
    ]]
    sig_tbl = Table(sig_data, colWidths=[92*mm, 92*mm, 93*mm])
    sig_tbl.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
    story.append(sig_tbl)

    doc.build(story)
    return buf.getvalue()
