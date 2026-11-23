"""
app.py
Ứng dụng web Flask cho hệ thống Bãi đỗ xe thông minh (bản ghép đầy đủ chức năng).

Chức năng:
  /login, /logout   - Đăng nhập / đăng xuất
  /                  - Menu chính (trang chủ)
  /parking           - Sơ đồ bãi đỗ theo khu A/B/C (dữ liệu thật từ DB)
  /gate              - Cabin riêng: sơ đồ ô đỗ, chọn phương tiện và điều hướng xe vào / ra
  /monitoring/parking - Giám sát ô đỗ, chờ tích hợp camera nhận diện tình trạng bãi
  /entry, /exit      - Nhận diện từ ảnh / camera -> kiểm tra -> xác nhận đúng chiều vào / ra
  /history           - Lịch sử toàn bộ lượt gửi xe (có bộ lọc)
  /invoices          - Hóa đơn thu phí của các lượt xe đã ra, xuất CSV và in phiếu thu
  /statistics        - Thống kê tổng quan
  /pricing           - Bảng giá xe: khung thời gian, loại xe, giá (ai cũng xem, admin/nhân viên chỉnh sửa)
  /settings          - Cài đặt cá nhân (mỗi người tự chọn, không cần admin/nhân viên)
  /customers         - Quản lý khách hàng & phương tiện (admin và nhân viên)
  /accounts          - Quản lý tài khoản nhân viên & quản trị (chỉ admin)
  /users             - Điều hướng tương thích ngược
"""

import os
import sys
import calendar
import uuid
import re
import functools
import threading
import time
from datetime import datetime, timedelta, date
from urllib.parse import urlencode

# Thư mục py/ chứa các module (config, database, plate_recognition, ...)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'py'))

# --- Kiểm tra thư viện cần thiết đã được cài đủ chưa ---
try:
    from flask import (
        Flask, render_template, request, redirect, url_for, flash, session,
        send_from_directory, jsonify, send_file, abort, Response, stream_with_context
    )
    import cv2          # noqa: F401  (chỉ để kiểm tra đã cài opencv-python chưa)
    import easyocr       # noqa: F401  (chỉ để kiểm tra đã cài easyocr chưa)
except ImportError as e:
    print("=" * 60)
    print("LỖI: Thiếu thư viện cần thiết ->", e)
    print("Hãy chạy lệnh cài đặt trước khi chạy app.py:")
    print()
    print("   macOS/Linux:  ./setup.sh")
    print("   Windows    :  setup.bat")
    print()
    print("(hoặc thủ công: pip install -r requirements.txt)")
    print("=" * 60)
    sys.exit(1)

from markupsafe import Markup
from config import TMP_DIR, IN_DIR, OUT_DIR, TEMPLATES_HTML_DIR, TEMPLATES_CSS_DIR
import database
import export_stats
from parking_fees import calculate_turn_fee, DEFAULT_HOURLY_FALLBACK
from plate_recognition import recognize_plate_annotated, recognize_plate, recognize_plate_live
from plate_utils import normalize_plate, plate_key, is_valid_plate_format
import parking_invoices
import parking_customers
import parking_employees
import support_chat
import ip_camera

TMP_FOLDER = TMP_DIR   # ảnh tạm (cache/tmp) giữa bước "Nhận diện" và bước "Xác nhận"
UPLOAD_DIRS = {'in': IN_DIR, 'out': OUT_DIR}   # static/in: xe vào, static/out: xe ra

VIETNAM_BANKS = [
    {'bin': '970407', 'short_name': 'Techcombank', 'name': 'Techcombank - Ngân hàng Kỹ Thương'},
    {'bin': '970436', 'short_name': 'Vietcombank', 'name': 'Vietcombank - Ngân hàng Ngoại Thương'},
    {'bin': '970422', 'short_name': 'MBBank', 'name': 'MBBank - Ngân hàng Quân Đội'},
    {'bin': '970415', 'short_name': 'VietinBank', 'name': 'VietinBank - Ngân hàng Công Thương'},
    {'bin': '970418', 'short_name': 'BIDV', 'name': 'BIDV - Ngân hàng Đầu tư & Phát triển'},
    {'bin': '970432', 'short_name': 'VPBank', 'name': 'VPBank - Ngân hàng Việt Nam Thịnh Vượng'},
    {'bin': '970423', 'short_name': 'TPBank', 'name': 'TPBank - Ngân hàng Tiên Phong'},
    {'bin': '970416', 'short_name': 'ACB', 'name': 'ACB - Ngân hàng Á Châu'},
    {'bin': '970403', 'short_name': 'Sacombank', 'name': 'Sacombank - Ngân hàng Sài Gòn Thương Tín'},
    {'bin': '970405', 'short_name': 'Agribank', 'name': 'Agribank - Ngân hàng Nông nghiệp & PTNT'},
    {'bin': '970441', 'short_name': 'VIB', 'name': 'VIB - Ngân hàng Quốc Tế'},
    {'bin': '970437', 'short_name': 'HDBank', 'name': 'HDBank - Ngân hàng Phát triển TP.HCM'},
    {'bin': '970443', 'short_name': 'SHB', 'name': 'SHB - Ngân hàng Sài Gòn - Hà Nội'},
    {'bin': '970426', 'short_name': 'MSB', 'name': 'MSB - Ngân hàng Hàng Hải'},
    {'bin': '970448', 'short_name': 'OCB', 'name': 'OCB - Ngân hàng Phương Đông'},
    {'bin': '970440', 'short_name': 'SeABank', 'name': 'SeABank - Ngân hàng Đông Nam Á'},
]

FEE_PER_HOUR = DEFAULT_HOURLY_FALLBACK  # dùng chung với ước tính phí của chatbot
MIN_PASSWORD_LEN = 4

app = Flask(__name__, template_folder=TEMPLATES_HTML_DIR)
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or 'demo-smart-parking-secret-key'


@app.route('/css/<path:filename>')
@app.route('/static/css/<path:filename>')
def css_files(filename):
    """Phục vụ file CSS đặt trong templates/css/."""
    return send_from_directory(TEMPLATES_CSS_DIR, filename)


@app.route('/images/<path:filename>')
def image_files(filename):
    """Phục vụ ảnh giao diện đặt trong static/images/."""
    return send_from_directory(os.path.join(app.root_path, 'static', 'images'), filename)


@app.route('/tmp-preview/<path:filename>')
def tmp_preview(filename):
    """Phục vụ ảnh đánh dấu tạm trong cache/tmp/ (chỉ cho người đã đăng nhập)."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return send_from_directory(TMP_FOLDER, filename)

with app.app_context():
    database.init_db()

support_chat.register_support(app)


# ============================================================
# TIỆN ÍCH
# ============================================================

def save_upload(file_storage, prefix: str):
    ext = os.path.splitext(file_storage.filename)[1].lower() or '.jpg'
    filename = f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"
    path = os.path.join(UPLOAD_DIRS.get(prefix, IN_DIR), filename)
    file_storage.save(path)
    return filename, path


def month_ticket_valid(reg, on_date) -> bool:
    """Xe đăng ký VÉ THÁNG và ngày hết hạn chưa qua (tính đến hết ngày hết hạn)."""
    return bool(reg and reg['ticket_type'] == 'month' and reg['expires_on']
                and reg['expires_on'] >= on_date.isoformat())


def find_similar_registered(plate):
    """Biển số đọc được KHÔNG khớp xe nào nhưng chỉ lệch đúng 1 ký tự so với đúng 1 xe đã đăng ký
    -> trả về xe đó để GỢI Ý (không tự đổi). Ngược lại trả None."""
    key = plate_key(plate)
    if len(key) < 5:
        return None
    candidates = [r for r in database.get_registered_plates()
                  if len(r['plate_key']) == len(key)
                  and sum(a != b for a, b in zip(r['plate_key'], key)) == 1]
    return candidates[0] if len(candidates) == 1 else None


def calc_fee(record, exit_time: datetime):
    """Tính phí khi xe ra.
    - Cộng giá LƯỢT của từng khung giờ xe đi qua, mỗi lần xuất hiện của khung tính một lần.
    - Khoảng chưa có giá (hoặc xe cũ chưa có loại xe) dùng đơn giá dự phòng theo giờ.
    Trả về (phí, thời gian gửi, mô tả cách tính)."""
    entry_time = datetime.fromisoformat(record['entry_time'])
    duration = timedelta(seconds=int((exit_time - entry_time).total_seconds()))

    # Xe đã đăng ký VÉ THÁNG còn hạn -> miễn phí lượt này
    reg = database.get_registered_vehicle(plate_key(record['plate_number']))
    if month_ticket_valid(reg, exit_time.date()):
        return 0, duration, (f"Vé tháng của tài khoản {reg['username']} "
                             f"(còn hạn đến {reg['expires_on']}) · miễn phí")

    prices = database.get_turn_prices(record['vehicle_type_id'])
    policy = next((dict(v) for v in database.get_vehicle_types() if v['id'] == record['vehicle_type_id']), {})
    fee, note = calculate_turn_fee(prices, entry_time, exit_time, FEE_PER_HOUR,
                                   policy.get('grace_minutes', 0), policy.get('daily_cap', 0),
                                   free_minutes=policy.get('free_minutes', 0),
                                   first_block_hours=policy.get('first_block_hours', 0),
                                   first_block_amount=policy.get('first_block_amount', 0),
                                   next_hour_amount=policy.get('next_hour_amount', 0))
    if prices:
        note = f"{record['vehicle_type_name'] or 'Loại xe'} · {note}"
    return fee, duration, note


def login_required(view_func):
    @functools.wraps(view_func)
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:
            flash('Vui lòng đăng nhập để tiếp tục.', 'error')
            return redirect(url_for('login'))
        return view_func(*args, **kwargs)
    return wrapped


def admin_required(view_func):
    @functools.wraps(view_func)
    def wrapped(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Chỉ quản trị viên mới có quyền truy cập trang này.', 'error')
            return redirect(url_for('index'))
        return view_func(*args, **kwargs)
    return wrapped


def staff_required(view_func):
    """Cho phép admin và nhân viên (manager); chặn tài khoản 'user' thường."""
    @functools.wraps(view_func)
    def wrapped(*args, **kwargs):
        if session.get('role') not in ('admin', 'manager'):
            flash('Chỉ nhân viên hoặc quản trị viên mới có quyền thực hiện thao tác này.', 'error')
            return redirect(url_for('parking'))
        return view_func(*args, **kwargs)
    return wrapped


def user_required(view_func):
    """Chỉ dành cho tài khoản người dùng thường (role = 'user') — các chức năng tự phục vụ ở /me/..."""
    @functools.wraps(view_func)
    def wrapped(*args, **kwargs):
        if session.get('role') != 'user':
            flash('Chức năng này chỉ dành cho tài khoản người dùng.', 'error')
            return redirect(url_for('index'))
        return view_func(*args, **kwargs)
    return wrapped


ROLE_LABELS = {'admin': 'Quản trị viên', 'manager': 'Nhân viên', 'user': 'Người dùng'}


def _get_main_gate_dict():
    """Trả về cấu hình Cổng chính mặc định (id = -1)."""
    zone_type = database.get_setting('central_gate_zone_type', 'gate_inout')
    if zone_type not in ZONE_TYPE_LABELS:
        zone_type = 'gate_inout'
    vt_id = _to_int(database.get_setting('central_gate_vehicle_type_id', ''))
    vt_ids = database.get_setting('central_gate_vehicle_type_ids', '')
    return {
        'id': -1,
        'name': 'Cổng chính',
        'zone_type': zone_type,
        'location': database.get_setting('central_gate_location') or '',
        'vehicle_type_id': vt_id,
        'vehicle_type_ids': vt_ids,
        'operating_hours': database.get_setting('central_gate_hours', '24/7') or '24/7',
        'area_names': database.get_setting('central_gate_area_names', '') or '',
        'status': 'active',
        'note': database.get_setting('central_gate_note') or '',
    }


def _current_gate():
    uid = session.get('user_id')
    role = session.get('role')
    if not (uid and role in ('admin', 'manager')):
        return None
    sel_id = session.get('selected_gate_id')
    if not sel_id:
        return None
    if sel_id == -1:
        return _get_main_gate_dict()
    try:
        for z in database.get_parking_zones(status='active'):
            if z['id'] == sel_id:
                return dict(z)
    except Exception:
        return None
    return None


def _current_gate_name():
    gate = _current_gate()
    return gate['name'] if gate else None


def build_eod_report_data(report_date_iso=None, gate_name=None, receiver_filter='', creator_filter=''):
    """Tổng hợp dữ liệu Báo cáo cuối ngày (kiểu KiotViet POS) cho Modal Cabin & trang Báo cáo."""
    today_dt = date.today()
    if report_date_iso:
        try:
            target_date = date.fromisoformat(report_date_iso[:10])
        except ValueError:
            target_date = today_dt
    else:
        target_date = today_dt
    d_iso = target_date.isoformat()
    d_vdate = target_date.strftime('%d/%m/%Y')
    now_dt = datetime.now()

    all_records = [dict(r) for r in database.get_all_records()]
    if gate_name:
        all_records = [r for r in all_records if r.get('entry_gate') == gate_name or r.get('exit_gate') == gate_name]

    # Các lượt đã ra (thanh toán) trong ngày được chọn
    out_records = [
        r for r in all_records
        if r.get('status') == 'OUT' and (r.get('exit_time') or '').startswith(d_iso)
    ]
    # Các lượt đang gửi trong bãi (Xe đang gửi / Đơn đang phục vụ)
    in_records = [
        r for r in all_records
        if r.get('status') == 'IN' and (r.get('entry_time') or '').startswith(d_iso)
    ]
    # Các lượt đã hủy / xóa trong ngày
    deleted_records = [
        r for r in all_records
        if r.get('status') == 'DELETED' and ((r.get('exit_time') or r.get('entry_time') or '').startswith(d_iso))
    ]

    cash_total = 0
    transfer_total = 0
    card_total = 0
    total_revenue = 0
    invoices = []

    for r in sorted(out_records, key=lambda x: x.get('exit_time') or '', reverse=True):
        fee = int(r.get('fee') or 0)
        pm = r.get('payment_method') or 'cash'
        if pm == 'transfer':
            transfer_total += fee
        elif pm == 'card':
            card_total += fee
        else:
            cash_total += fee
        total_revenue += fee
        exit_ts = r.get('exit_time') or ''
        entry_ts = r.get('entry_time') or ''
        time_hm = exit_ts[11:16] if len(exit_ts) >= 16 else '00:00'
        entry_hm = entry_ts[11:16] if len(entry_ts) >= 16 else '00:00'
        invoices.append({
            'id': r['id'],
            'code': f"HD{r['id']:06d}",
            'plate_number': r.get('plate_number') or '—',
            'slot_name': r.get('slot_name') or '—',
            'vehicle_type_name': r.get('vehicle_type_name') or 'Xe gửi',
            'entry_time': entry_ts,
            'exit_time': exit_ts,
            'date_only_str': d_vdate,
            'time_hm': time_hm,
            'entry_hm': entry_hm,
            'date_time_str': f"{d_vdate} {time_hm}",
            'qty': 1,
            'revenue': fee,
            'other_fee': 0,
            'tax': 0,
            'return_fee': 0,
            'paid': fee,
            'payment_method': pm,
            'payment_label': database.PAYMENT_METHODS.get(pm, 'Tiền mặt'),
            'gate': r.get('exit_gate') or r.get('entry_gate') or (gate_name or 'Trung tâm'),
        })

    serving_est_total = 0
    serving_items = []
    for r in sorted(in_records, key=lambda x: x.get('entry_time') or '', reverse=True):
        try:
            fee_est, _, _ = calc_fee(r, now_dt)
        except Exception:
            fee_est = 0
        fee_est = int(fee_est or 0)
        serving_est_total += fee_est
        entry_ts = r.get('entry_time') or ''
        entry_hm = entry_ts[11:16] if len(entry_ts) >= 16 else '00:00'
        serving_items.append({
            'id': r['id'],
            'code': f"PG{r['id']:06d}",
            'plate_number': r.get('plate_number') or '—',
            'slot_name': r.get('slot_name') or '—',
            'vehicle_type_name': r.get('vehicle_type_name') or 'Xe gửi',
            'entry_time': entry_ts,
            'date_only_str': d_vdate,
            'time_hm': entry_hm,
            'date_time_str': f"{d_vdate} {entry_hm}",
            'qty': 1,
            'revenue': fee_est,
            'other_fee': 0,
            'tax': 0,
            'return_fee': 0,
            'paid': 0,
            'gate': r.get('entry_gate') or (gate_name or 'Trung tâm'),
        })

    # Thu vé tháng trong ngày (nếu ở Trung tâm)
    month_rev = 0
    if not gate_name:
        try:
            st = database.get_statistics(d_iso, d_iso, gate_name=None)
            month_rev = int(st.get('period_month_revenue') or 0)
        except Exception:
            month_rev = 0

    inv_count = len(invoices)
    serving_count = len(in_records)
    cancel_count = len(deleted_records)
    avg_per_inv = round(total_revenue / inv_count) if inv_count > 0 else 0
    distinct_types_out = len({r.get('vehicle_type_name') or 'Xe' for r in out_records}) if out_records else 0
    distinct_types_in = len({r.get('vehicle_type_name') or 'Xe' for r in in_records}) if in_records else 0

    creator_name = session.get('fullname') or session.get('username') or 'Quản trị viên'
    branch_name = gate_name if gate_name else 'Trung tâm (Tất cả cổng)'

    return {
        'date_iso': d_iso,
        'date_vdate': d_vdate,
        'generated_at': now_dt.strftime('%d/%m/%Y %H:%M'),
        'creator_name': creator_name,
        'branch_name': branch_name,
        'receiver_filter': receiver_filter,
        'creator_filter': creator_filter,
        'invoice_count': inv_count,
        'distinct_types_out': distinct_types_out,
        'total_revenue': total_revenue,
        'month_revenue': month_rev,
        'other_revenue': month_rev,
        'net_revenue_with_other': total_revenue + month_rev,
        'net_revenue_no_other': total_revenue,
        'cash_total': cash_total,
        'transfer_total': transfer_total,
        'card_total': card_total,
        'avg_per_invoice': avg_per_inv,
        'serving_count': serving_count,
        'distinct_types_in': distinct_types_in,
        'serving_est_total': serving_est_total,
        'serving_items': serving_items,
        'cancel_count': cancel_count,
        'cancel_value': 0,
        'invoices': invoices,
    }


@app.route('/api/cabin/eod-report')
@login_required
@staff_required
def api_cabin_eod_report():
    """API trả dữ liệu JSON Báo cáo cuối ngày cho Modal trên giao diện Cabin POS."""
    report_date = (request.args.get('date') or '').strip()
    receiver = (request.args.get('receiver') or '').strip()
    creator = (request.args.get('creator') or '').strip()
    data = build_eod_report_data(
        report_date_iso=report_date or date.today().isoformat(),
        gate_name=_current_gate_name(),
        receiver_filter=receiver,
        creator_filter=creator,
    )
    return jsonify(ok=True, report=data)


@app.context_processor
def inject_user():
    uid = session.get('user_id')
    role = session.get('role')
    open_shift = None
    active_gates = []
    selected_gate = None
    staff_members = []
    eod_initial = None
    if uid and role in ('admin', 'manager'):
        try:
            open_shift = database.get_open_attendance(uid)
        except Exception:
            open_shift = None
        try:
            active_gates = [dict(z) for z in database.get_parking_zones(status='active')]
            sel_id = session.get('selected_gate_id')
            if sel_id == -1:
                selected_gate = _get_main_gate_dict()
            elif sel_id:
                selected_gate = next((g for g in active_gates if g['id'] == sel_id), None)
        except Exception:
            active_gates = []
            selected_gate = None
        try:
            staff_members = [
                {'id': u['id'], 'username': u['username'], 'fullname': u['fullname'] or u['username']}
                for u in database.get_staff_users()
            ]
        except Exception:
            staff_members = []
        try:
            eod_initial = build_eod_report_data(gate_name=selected_gate['name'] if selected_gate else None)
        except Exception:
            eod_initial = None
    return {
        'current_user_fullname': session.get('fullname'),
        'current_user_role': role,
        'role_label': ROLE_LABELS.get(role, 'Người dùng'),
        'open_shift': open_shift,
        'active_gates': active_gates,
        'selected_gate': selected_gate,
        'staff_members': staff_members,
        'eod_initial': eod_initial,
        'today_iso': date.today().isoformat(),
        'today_vdate': date.today().strftime('%d/%m/%Y'),
    }


# ============================================================
# ĐĂNG NHẬP / ĐĂNG XUẤT
# ============================================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        user = database.verify_login(username, password)
        if user is None:
            flash('Sai tên đăng nhập, mật khẩu, hoặc tài khoản đã bị khóa.', 'error')
            return redirect(url_for('login'))

        session['user_id'] = user['id']
        session['username'] = user['username']
        session['fullname'] = user['fullname']
        session['role'] = user['role']

        flash(f'Xin chào {user["fullname"]}!', 'success')
        return redirect(url_for('index'))

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        fullname = request.form.get('fullname', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not fullname or not username or not password:
            flash('Vui lòng nhập đầy đủ thông tin.', 'error')
            return render_template('register.html', fullname=fullname, username=username)

        if len(password) < MIN_PASSWORD_LEN:
            flash(f'Mật khẩu tối thiểu {MIN_PASSWORD_LEN} ký tự.', 'error')
            return render_template('register.html', fullname=fullname, username=username)

        if password != confirm_password:
            flash('Mật khẩu nhập lại không khớp.', 'error')
            return render_template('register.html', fullname=fullname, username=username)

        if database.username_exists(username):
            flash('Tên đăng nhập đã tồn tại. Vui lòng chọn tên khác.', 'error')
            return render_template('register.html', fullname=fullname, username=username)

        database.add_user(username, fullname, password, role='user')
        flash('Đăng ký tài khoản thành công! Vui lòng đăng nhập.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Đã đăng xuất.', 'success')
    return redirect(url_for('login'))


# ============================================================
# TRANG CHỦ (MENU CHÍNH)
# ============================================================

def _resolve_dashboard_gates(args, all_gate_names):
    """Phân giải danh sách cổng được chọn trên Dashboard (None = tất cả cổng)."""
    raw = args.get('gates')
    if raw is None:
        top_gate = _current_gate_name()
        if top_gate and top_gate in all_gate_names:
            return [top_gate]
        return None
    raw = raw.strip()
    if not raw or raw == 'all':
        return None
    if raw == 'none':
        return []
    chosen = [g.strip() for g in raw.split(',') if g.strip() in all_gate_names]
    if set(chosen) == set(all_gate_names):
        return None
    return chosen


def _gate_allowed_area_names(gate_row, all_areas):
    """Xác định tập tên khu đỗ thuộc phạm vi 1 cổng (dựa trên area_names hoặc vehicle_type_ids/vehicle_type_id)."""
    raw_areas = [x.strip() for x in (gate_row.get('area_names') or '').split(',') if x.strip()]
    if raw_areas:
        lower_set = {x.lower() for x in raw_areas}
        return {a['name'] for a in all_areas if a['name'].strip().lower() in lower_set}
    vt_ids = {int(x) for x in (gate_row.get('vehicle_type_ids') or '').split(',') if x.strip().isdigit()}
    if not vt_ids and gate_row.get('vehicle_type_id'):
        vt_ids = {int(gate_row['vehicle_type_id'])}
    if vt_ids:
        specific = {a['name'] for a in all_areas if a.get('vehicle_type_id') in vt_ids}
        if specific:
            return specific
        return {a['name'] for a in all_areas if a.get('vehicle_type_id') is None}
    return {a['name'] for a in all_areas}


def _build_dashboard_data(args):
    active_gate_rows = [dict(z) for z in database.get_parking_zones(status='active')]
    main_gate = _get_main_gate_dict()
    gate_options = ['Tất cả các cổng', 'Cổng chính'] + [g['name'] for g in active_gate_rows]
    selected_gates = _resolve_dashboard_gates(args, gate_options)
    start, end, range_key, label = parse_stats_range(args)
    stats = database.get_statistics_for_gates(start.isoformat(), end.isoformat(), gate_names=selected_gates)

    all_area_stats = database.area_stats()
    all_areas = [dict(a) for a in database.get_areas()]
    if selected_gates is None:
        area_stats = all_area_stats
    elif not selected_gates:
        area_stats = {}
    elif 'Trung tâm' in selected_gates or 'Tất cả các cổng' in selected_gates:
        area_stats = all_area_stats
    else:
        gate_by_name = {g['name']: g for g in active_gate_rows}
        gate_by_name['Cổng chính'] = main_gate
        allowed_names = set()
        for gname in selected_gates:
            g_row = gate_by_name.get(gname)
            if g_row:
                allowed_names |= _gate_allowed_area_names(g_row, all_areas)
        area_stats = {k: v for k, v in all_area_stats.items() if k in allowed_names}

    counts = {'total': 0, 'available': 0, 'occupied': 0, 'maintenance': 0}
    for a in area_stats.values():
        counts['total'] += a.get('total', 0)
        counts['available'] += a.get('available', 0)
        counts['occupied'] += a.get('occupied', 0)
        counts['maintenance'] += a.get('maintenance', 0)

    recent_records = database.get_recent_records_for_gates(gate_names=selected_gates, limit=8)
    effective_selected = gate_options if selected_gates is None else selected_gates
    if selected_gates is None or len(effective_selected) == len(gate_options):
        gate_filter_label = 'Tất cả cổng'
    elif len(effective_selected) == 0:
        gate_filter_label = 'Chưa chọn cổng'
    elif len(effective_selected) == 1:
        gate_filter_label = effective_selected[0]
    else:
        gate_filter_label = f"{len(effective_selected)} cổng đã chọn"
    return {
        'counts': counts,
        'stats': stats,
        'area_stats': area_stats,
        'recent_records': recent_records,
        'range_key': range_key,
        'range_label': label,
        'date_from': start.isoformat(),
        'date_to': end.isoformat(),
        'today_iso': date.today().isoformat(),
        'gate_options': gate_options,
        'selected_gates': effective_selected,
        'all_gates_selected': selected_gates is None,
        'gate_filter_label': gate_filter_label,
    }


@app.route('/')
@login_required
def index():
    counts = database.slot_counts()
    if session.get('role') == 'user':      # người dùng: trang chủ riêng, chỉ có 4 chức năng
        return render_template('user_home.html', counts=counts, today=date.today().isoformat(),
                               vehicles=database.get_user_vehicles(session['user_id']),
                               area_stats=database.area_stats())
    data = _build_dashboard_data(request.args)
    return render_template('index.html', **data)


@app.route('/api/dashboard')
@login_required
@staff_required
def api_dashboard():
    data = _build_dashboard_data(request.args)
    return jsonify(data)


# ============================================================
# SƠ ĐỒ BÃI ĐỖ XE
# ============================================================

def _parking_context_for_gate():
    all_slots = database.get_all_slots()
    all_areas = []
    for row in database.get_areas():
        d = dict(row)
        d.setdefault('allowed_vehicle_type_id', d.get('vehicle_type_id'))
        d.setdefault('allowed_type_name', d.get('vehicle_type_name'))
        all_areas.append(d)
    all_slots_by_area = {a['name']: [] for a in all_areas}
    for slot in all_slots:
        all_slots_by_area.setdefault(slot['area'], []).append(slot)

    gate = _current_gate()
    assigned_names = []
    if gate:
        assigned_names = [x.strip() for x in (gate.get('area_names') or '').split(',') if x.strip()]

    if gate and assigned_names:
        assigned_lower = {x.lower() for x in assigned_names}
        areas = [a for a in all_areas if a['name'].strip().lower() in assigned_lower]
    elif gate and (gate.get('vehicle_type_ids') or gate.get('vehicle_type_id')):
        vt_ids = {
            int(x) for x in (gate.get('vehicle_type_ids') or '').split(',') if x.strip().isdigit()
        }
        if not vt_ids and gate.get('vehicle_type_id'):
            vt_ids = {int(gate['vehicle_type_id'])}
        specific = [a for a in all_areas if a.get('vehicle_type_id') in vt_ids]
        areas = specific if specific else [a for a in all_areas if a.get('vehicle_type_id') is None]
    else:
        areas = all_areas

    slots_by_area = {a['name']: all_slots_by_area.get(a['name'], []) for a in areas}
    counts = {'total': 0, 'available': 0, 'occupied': 0, 'maintenance': 0}
    for a_slots in slots_by_area.values():
        for s in a_slots:
            counts['total'] += 1
            st = s['status']
            if st in counts:
                counts[st] += 1
    return {
        'slots_by_area': slots_by_area,
        'counts': counts,
        'areas': areas,
        'all_areas': all_areas,
        'assigned_area_names': assigned_names,
        'current_gate_obj': gate,
        'vehicle_types': database.get_vehicle_types(),
    }


@app.route('/parking')
@login_required
def parking():
    ctx = _parking_context_for_gate()
    return render_template('parking.html', **ctx)


@app.route('/parking/export')
@login_required
def parking_export():
    import csv
    import io
    import unicodedata
    ctx = _parking_context_for_gate()
    buf = io.StringIO()
    buf.write('\ufeff')
    writer = csv.writer(buf)
    writer.writerow(['Khu vực', 'Tên ô', 'Trạng thái', 'Biển số', 'Loại xe', 'Lý do bảo trì'])
    status_labels = {'available': 'Còn trống', 'occupied': 'Đang có xe', 'maintenance': 'Bảo trì'}
    for area in ctx['areas']:
        area_d = dict(area)
        for s in ctx['slots_by_area'].get(area_d['name'], []):
            sd = dict(s)
            writer.writerow([
                f"Khu {area_d['name']}",
                sd.get('slot_name', ''),
                status_labels.get(sd.get('status'), sd.get('status', '')),
                sd.get('plate_number') or '',
                sd.get('vehicle_type_name') or area_d.get('allowed_type_name') or 'Tất cả loại xe',
                sd.get('maintenance_reason') or '',
            ])
    gate = ctx['current_gate_obj']
    if gate:
        raw_slug = unicodedata.normalize('NFKD', gate['name'].replace('đ', 'd').replace('Đ', 'D')).encode('ascii', 'ignore').decode()
        slug = re.sub(r'[^A-Za-z0-9_-]+', '_', raw_slug).strip('_') or 'cong'
        fname = f"so_do_bai_do_{slug}.csv"
    else:
        fname = "so_do_bai_do.csv"
    return Response(
        buf.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{fname}"'},
    )


@app.route('/parking/gate-areas', methods=['POST'])
@login_required
@staff_required
def parking_gate_areas_save():
    gate = _current_gate()
    if not gate:
        flash('Đang ở chế độ Trung tâm (hiển thị tất cả khu đỗ).', 'info')
        return redirect(url_for('parking'))
    selected = [a.strip() for a in request.form.getlist('area_names') if a.strip()]
    area_names = ','.join(selected)[:255]
    if gate['id'] == -1:
        database.set_setting('central_gate_area_names', area_names)
    else:
        database.save_parking_zone(
            gate['id'],
            gate['name'],
            gate.get('zone_type') or 'gate_inout',
            gate.get('location') or '',
            gate.get('vehicle_type_id'),
            gate.get('capacity') or 0,
            gate.get('status') or 'active',
            gate.get('note') or '',
            operating_hours=gate.get('operating_hours') or '24/7',
            area_names=area_names,
            vehicle_type_ids=gate.get('vehicle_type_ids') or '',
        )
    flash(f'Đã cập nhật khu đỗ hiển thị cho {gate["name"]}.', 'success')
    return redirect(url_for('parking'))


@app.route('/parking/<slot_name>/maintenance', methods=['POST'])
@login_required
@staff_required
def slot_maintenance(slot_name):
    action = request.form.get('maintenance_action')
    try:
        if action not in ('start', 'update', 'finish'):
            raise ValueError('Thao tác bảo trì không hợp lệ.')
        database.set_slot_maintenance(slot_name, action != 'finish', request.form.get('reason', ''),
                                      expected_status='available' if action == 'start' else 'maintenance')
        flash(f'Đã cập nhật trạng thái bảo trì ô {slot_name}.', 'success')
    except ValueError as error:
        flash(str(error), 'error')
    return redirect(url_for('parking'))


@app.route('/parking/areas/save', methods=['POST'])
@login_required
@admin_required
def parking_area_save():
    try:
        raw_id = request.form.get('area_id', '')
        area_id = _to_int(raw_id)
        raw_type = request.form.get('vehicle_type_id', '')
        type_id = _to_int(raw_type)
        if (raw_id and not area_id) or (raw_type and raw_type != 'all' and not type_id):
            raise ValueError('Khu hoặc loại xe không hợp lệ.')
        if area_id and not raw_type:
            raise ValueError('Hãy chọn loại xe được phép đỗ hoặc Tất cả loại xe.')
        slot_count = _to_int(request.form.get('slot_count')) if area_id is None else 0
        if area_id is None and (slot_count is None or not 1 <= slot_count <= 1000):
            raise ValueError('Vui lòng nhập số lượng ô đỗ từ 1 đến 1000.')
        new_name = (request.form.get('name') or '').strip()
        database.save_area(area_id, new_name, type_id, slot_count=slot_count,
                           note=request.form.get('note', ''))
        if area_id is None:
            gate = _current_gate()
            if gate:
                existing_areas = [x.strip() for x in (gate.get('area_names') or '').split(',') if x.strip()]
                if new_name and new_name.lower() not in {x.lower() for x in existing_areas}:
                    existing_areas.append(new_name)
                    if gate['id'] == -1:
                        database.set_setting('central_gate_area_names', ','.join(existing_areas)[:255])
                    else:
                        database.save_parking_zone(
                            gate['id'],
                            gate['name'],
                            gate.get('zone_type') or 'gate_inout',
                            gate.get('location') or '',
                            gate.get('vehicle_type_id'),
                            gate.get('capacity') or 0,
                            gate.get('status') or 'active',
                            gate.get('note') or '',
                            operating_hours=gate.get('operating_hours') or '24/7',
                            area_names=','.join(existing_areas)[:255],
                            vehicle_type_ids=gate.get('vehicle_type_ids') or '',
                        )
        flash('Đã lưu khu đỗ xe.', 'success')
    except ValueError as error:
        flash(str(error), 'error')
    return redirect(url_for('parking'))


@app.route('/parking/areas/<int:area_id>/delete', methods=['POST'])
@login_required
@admin_required
def parking_area_delete(area_id):
    try:
        database.delete_area(area_id)
        flash('Đã xóa khu và các ô đỗ trong khu.', 'success')
    except ValueError as error:
        flash(str(error), 'error')
    return redirect(url_for('parking'))


@app.route('/parking/<slot_name>/save', methods=['POST'])
@login_required
@admin_required
def parking_slot_save(slot_name):
    try:
        database.rename_slot(slot_name, request.form.get('slot_name'), request.form.get('expected_status'),
                              _to_int(request.form.get('record_id')), session.get('username') or str(session['user_id']))
        flash('Đã sửa tên ô đỗ.', 'success')
    except ValueError as error:
        flash(str(error), 'error')
    return redirect(url_for('parking'))


@app.route('/parking/slots/add', methods=['POST'])
@login_required
@admin_required
def parking_slot_add():
    try:
        database.add_slot(_to_int(request.form.get('area_id')), request.form.get('slot_name'))
        flash('Đã thêm ô đỗ.', 'success')
    except ValueError as error:
        flash(str(error), 'error')
    return redirect(url_for('parking'))


@app.route('/parking/<slot_name>/delete', methods=['POST'])
@login_required
@admin_required
def parking_slot_delete(slot_name):
    try:
        database.delete_slot(slot_name)
        flash(f'Đã xóa ô đỗ {slot_name}.', 'success')
    except ValueError as error:
        flash(str(error), 'error')
    return redirect(url_for('parking'))


@app.route('/parking/<slot_name>/move', methods=['POST'])
@login_required
@staff_required
def parking_vehicle_move(slot_name):
    try:
        record_id = _to_int(request.form.get('record_id'))
        if not record_id:
            raise ValueError('Thiếu thông tin xe. Hãy tải lại trang.')
        database.move_parked_vehicle(slot_name, request.form.get('target_slot'), record_id,
                                     session.get('username') or str(session['user_id']))
        flash('Đã di chuyển xe và lưu ghi chú vào lịch sử.', 'success')
    except ValueError as error:
        flash(str(error), 'error')
    return redirect(url_for('parking'))


@app.route('/parking/<slot_name>/remove', methods=['POST'])
@login_required
@staff_required
def parking_vehicle_remove(slot_name):
    try:
        record_id = _to_int(request.form.get('record_id'))
        if not record_id:
            raise ValueError('Thiếu thông tin xe. Hãy tải lại trang.')
        database.remove_parked_vehicle(slot_name, record_id, request.form.get('reason', ''),
                                       session.get('username') or str(session['user_id']))
        flash('Đã xóa xe khỏi ô; lượt gửi được giữ trong lịch sử với lý do xóa.', 'success')
    except ValueError as error:
        flash(str(error), 'error')
    return redirect(url_for('parking'))


# ============================================================
# XE VÀO / XE RA (ẢNH HOẶC CAMERA, 2 BƯỚC: NHẬN DIỆN -> XÁC NHẬN)
# ============================================================

TOKEN_RE = re.compile(r'^[0-9a-f]{12}$')
ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
# Mô hình OCR dùng chung (không an toàn khi chạy song song) -> các làn xếp lượt dùng.
CAMERA_OCR_LOCK = threading.Lock()
# Mỗi làn chỉ giữ tối đa 1 yêu cầu nhận diện đang chờ / đang chạy, để làn vào và
# làn ra không chặn nhau và không dồn hàng đợi khung hình.
LANE_OCR_LOCKS = {'entry': threading.Lock(), 'exit': threading.Lock()}
LIVE_OCR_WAIT_SECONDS = 1.0       # quét liên tục: bận thì bỏ khung, client tự thử lại
CAPTURE_OCR_WAIT_SECONDS = 30.0   # bấm "Chụp & quét"/tải ảnh: chờ tới lượt thay vì báo lỗi
MAX_CAMERA_FRAME_BYTES = 4 * 1024 * 1024
_last_camera_cleanup = float('-inf')


def clean_plate_input(text):
    """Chuẩn hóa biển số người dùng gõ về dạng có dấu '-' (61t32222 / 61-T3 2222 -> 61T3-2222)."""
    return normalize_plate(text)


def find_tmp(token):
    """Đường dẫn ảnh gốc tạm của token, hoặc None."""
    if not token or not TOKEN_RE.match(token):
        return None
    for name in os.listdir(TMP_FOLDER):
        if name.startswith(token + '.'):
            return os.path.join(TMP_FOLDER, name)
    return None


def drop_tmp(token):
    """Xóa ảnh gốc + ảnh đánh dấu tạm của token."""
    if not token or not TOKEN_RE.match(token):
        return
    for name in os.listdir(TMP_FOLDER):
        if name.startswith(token + '.') or name.startswith(token + '_ann'):
            try:
                os.remove(os.path.join(TMP_FOLDER, name))
            except OSError:
                pass


def cleanup_tmp(max_age_hours=6):
    """Dọn ảnh tạm bị bỏ dở (đã nhận diện nhưng không bấm Xác nhận)."""
    limit = datetime.now().timestamp() - max_age_hours * 3600
    for name in os.listdir(TMP_FOLDER):
        path = os.path.join(TMP_FOLDER, name)
        try:
            if os.path.getmtime(path) < limit:
                os.remove(path)
        except OSError:
            pass


def promote_tmp(token, prefix):
    """Chuyển ảnh tạm thành ảnh chính thức (in_/out_...). Trả về tên file mới."""
    src = find_tmp(token)
    ext = os.path.splitext(src)[1]
    filename = f"{prefix}_{token[:8]}{ext}"
    os.replace(src, os.path.join(UPLOAD_DIRS.get(prefix, IN_DIR), filename))
    drop_tmp(token)   # xóa nốt ảnh đánh dấu
    return filename


def gate_context(direction, token='', plate='', note='', form=None):
    """Thông tin xác nhận dùng chung cho trang đầy đủ và kết quả camera cập nhật trực tiếp."""
    token = token if find_tmp(token) else ''
    now = datetime.now()
    ctx = {'token': token, 'plate': plate, 'note': note, 'form': form or {}, 'now': now,
           'mode': None, 'record': None, 'fee_preview': None, 'preview_url': None,
           'type_options': [], 'slots_by_area': {}, 'entry_mode': None, 'no_slots': False,
           'registered': None, 'reg_month_ok': False, 'reg_expired': False, 'suggest': None,
           'reg_type': None, 'direction': direction, 'gate_error': None,
           'payment_methods': database.PAYMENT_METHODS,
           'source': 'upload' if request.form.get('source', request.args.get('source')) == 'upload' else 'camera'}

    if token and os.path.exists(os.path.join(TMP_FOLDER, f'{token}_ann.jpg')):
        ctx['preview_url'] = url_for('tmp_preview', filename=f'{token}_ann.jpg',
                                     v=int(os.path.getmtime(os.path.join(TMP_FOLDER, f'{token}_ann.jpg'))))

    ctx.update(
        vietqr_bank_bin=database.get_setting('vietqr_bank_bin', '970407'),
        vietqr_bank_name=database.get_setting('vietqr_bank_name', 'Techcombank'),
        vietqr_account_number=database.get_setting('vietqr_account_number', '19036888888'),
        vietqr_account_name=database.get_setting('vietqr_account_name', 'SMART PARKING'),
        vietqr_template=database.get_setting('vietqr_template', 'compact2'),
    )

    if token and len(plate_key(plate)) >= 4:
        registered = database.get_registered_vehicle(plate_key(plate))
        ctx['registered'] = registered
        ctx['reg_month_ok'] = month_ticket_valid(registered, now.date())
        ctx['reg_expired'] = bool(registered and registered['ticket_type'] == 'month'
                                  and not ctx['reg_month_ok'])
        ctx['suggest'] = None if registered else find_similar_registered(plate)
        record = database.find_open_record(plate)
        if direction == 'entry' and record is not None:
            ctx['gate_error'] = f'Xe {plate} đang gửi trong bãi. Hãy chọn Xe ra để làm thủ tục lấy xe.'
        elif direction == 'exit' and record is None:
            ctx['gate_error'] = f'Không tìm thấy xe {plate} đang gửi trong bãi. Hãy kiểm tra lại biển số hoặc chọn Xe vào.'
        elif direction == 'exit':
            fee, duration, fee_note = calc_fee(record, now)
            ctx.update(mode='exit', record=record,
                       fee_preview={'fee': fee, 'duration': duration, 'note': fee_note})
        else:
            slots_by_area = database.get_available_slots_by_area()
            ctx.update(
                mode='entry',
                entry_mode=database.get_user_setting(session['user_id'], 'entry_mode', 'auto'),
                slots_by_area=slots_by_area,
                no_slots=not any(slots_by_area.values()),
                type_options=[{'id': t['id'], 'name': t['name'],
                               'price': database.find_turn_price(t['id'], now)}
                              for t in database.get_vehicle_types()],
            )
            # Xe đã đăng ký (có loại xe): dùng luôn loại xe đã đăng ký, không cần chọn lại
            if registered and registered['vehicle_type_id']:
                ctx['reg_type'] = next((t for t in ctx['type_options']
                                        if t['id'] == registered['vehicle_type_id']), None)
    return ctx


def render_gate(direction, token='', plate='', note='', form=None):
    ctx = gate_context(direction, token, plate, note, form)
    ctx['counts'] = database.slot_counts()
    ctx['area_stats'] = database.area_stats()
    ctx['device_settings'] = get_device_settings()
    return render_template('gate.html', **ctx)


@app.route('/monitoring/parking')
@login_required
@staff_required
def parking_monitor():
    areas = database.get_areas()
    slots_by_area = {area['name']: [] for area in areas}
    for slot in database.get_all_slots():
        slots_by_area.setdefault(slot['area'], []).append(slot)
    return render_template('parking_monitor.html', areas=areas,
                           slots_by_area=slots_by_area, counts=database.slot_counts())


@app.route('/gate/select', methods=['POST'])
@login_required
@staff_required
def select_active_gate():
    gate_id = _to_int(request.form.get('gate_id'))
    if not gate_id:
        session.pop('selected_gate_id', None)
        flash('Đã chuyển sang Trung tâm (toàn bộ bãi xe).', 'success')
    elif gate_id == -1:
        session['selected_gate_id'] = -1
        flash('Đã chuyển sang Cổng chính. Dữ liệu bãi xe đã được cập nhật.', 'success')
    else:
        active_gates = [dict(z) for z in database.get_parking_zones(status='active')]
        gate_obj = next((g for g in active_gates if g['id'] == gate_id), None)
        if gate_obj:
            session['selected_gate_id'] = gate_obj['id']
            flash(f'Đã chuyển sang {gate_obj["name"]}. Dữ liệu bãi xe đã được cập nhật.', 'success')
        else:
            session.pop('selected_gate_id', None)
    target = request.form.get('next') or request.referrer or url_for('index')
    if 'gates=' in target:
        from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
        parts = urlsplit(target)
        q_pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != 'gates']
        target = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q_pairs), parts.fragment))
    return redirect(target)


@app.route('/gate')
@login_required
@staff_required
def gate():
    open_records = {record['id']: dict(record) for record in database.get_open_records()}
    cabin_slots = []
    now = datetime.now()
    for item in database.get_all_slots():
        slot = dict(item)
        slot['record'] = open_records.get(slot['record_id'])
        slot['preview_fee'], slot['preview_duration'] = 0, ''
        if slot['record']:
            slot['preview_fee'], slot['preview_duration'], _ = calc_fee(slot['record'], now)
        cabin_slots.append(slot)
    return render_template('cabin_parking.html',
                           areas=database.get_areas(), cabin_slots=cabin_slots,
                           counts=database.slot_counts())


@app.route('/gate/lanes')
@login_required
@staff_required
def gate_lanes():
    today = date.today().isoformat()
    records = [dict(record) for record in database.get_all_records()
               if record['status'] in ('IN', 'OUT')]
    open_list = [r for r in records if r['status'] == 'IN']
    exit_list = sorted((r for r in records if r['status'] == 'OUT'),
                       key=lambda r: r['exit_time'] or '', reverse=True)
    recent_list = sorted(
        records,
        key=lambda r: (r['exit_time'] if r['status'] == 'OUT' else r['entry_time']) or r['entry_time'] or '',
        reverse=True,
    )[:20]
    entry_record = open_list[0] if open_list else (records[0] if records else None)
    exit_record = exit_list[0] if exit_list else None
    now = datetime.now()
    for record in (*open_list[:20], *recent_list, entry_record, exit_record):
        if record is None:
            continue
        if record.get('status') == 'IN':
            if 'preview_fee' not in record:
                record['preview_fee'], record['preview_duration'], _ = calc_fee(record, now)
        else:
            record['preview_fee'] = record.get('fee') or 0
            record['preview_duration'] = ''
        if 'entry_image_url' not in record:
            for direction, folder in (('entry', IN_DIR), ('exit', OUT_DIR)):
                filename = record.get(f'{direction}_image')
                record[f'{direction}_image_url'] = (
                    url_for('static', filename=f"{'in' if direction == 'entry' else 'out'}/{filename}")
                    if filename and os.path.basename(filename) == filename
                    and os.path.isfile(os.path.join(folder, filename)) else None)
    return render_template('gate_menu.html',
                           counts=database.slot_counts(),
                           stats=database.get_statistics(today, today, gate_name=_current_gate_name()),
                           entry_record=entry_record, exit_record=exit_record,
                           open_records=open_list[:20], recent_exits=exit_list[:20],
                           recent_records=recent_list,
                           device_settings=get_device_settings())


@app.route('/gate/<direction>/camera', methods=['POST'])
@login_required
@staff_required
def gate_camera(direction):
    """Nhận diện một khung hình, chỉ lưu ảnh tạm; ghi nhận vào / ra vẫn qua nút Xác nhận."""
    if direction not in ('entry', 'exit'):
        abort(404)
    if request.form.get('action') == 'discard':
        drop_tmp(request.form.get('token', ''))
        return '', 204
    profile = request.form.get('profile', 'live')
    if profile not in ('live', 'capture'):
        return jsonify(error='Chế độ nhận diện camera không hợp lệ.'), 400
    file = request.files.get('image')
    if not file or not file.filename:
        return jsonify(error='Chưa có hình ảnh từ camera.'), 400
    frame = file.read(MAX_CAMERA_FRAME_BYTES + 1)
    if not frame or len(frame) > MAX_CAMERA_FRAME_BYTES:
        return jsonify(error='Ảnh camera phải nhỏ hơn 4 MB.'), 400
    # Mỗi làn tối đa 1 yêu cầu; hai làn vào/ra xếp lượt dùng chung mô hình OCR
    # (chờ có giới hạn) thay vì làn này trả lỗi "bận" khi làn kia đang quét.
    lane_lock = LANE_OCR_LOCKS[direction]
    if not lane_lock.acquire(blocking=False):
        return jsonify(error='Làn này đang nhận diện khung hình trước, sẽ tự thử lại.'), 429
    wait = CAPTURE_OCR_WAIT_SECONDS if profile == 'capture' else LIVE_OCR_WAIT_SECONDS
    if not CAMERA_OCR_LOCK.acquire(timeout=wait):
        lane_lock.release()
        return jsonify(error='Nhận diện đang bận, sẽ tự thử lại.'), 429
    ocr_held = True
    token = uuid.uuid4().hex[:12]
    path = os.path.join(TMP_FOLDER, token + '.jpg')
    try:
        global _last_camera_cleanup
        if time.monotonic() - _last_camera_cleanup > 60:
            cleanup_tmp()
            _last_camera_cleanup = time.monotonic()
        with open(path, 'wb') as out:
            out.write(frame)
        plate, annotated, rect, width, height, metrics = recognize_plate_live(path, details=True, accurate=profile == 'capture')
        # Giải phóng mô hình OCR ngay để làn còn lại được quét, phần còn lại chỉ là đọc DB/render.
        CAMERA_OCR_LOCK.release()
        ocr_held = False
        plate = clean_plate_input(plate)
        if not cv2.imwrite(os.path.join(TMP_FOLDER, token + '_ann.jpg'), annotated):
            raise OSError('Không lưu được ảnh xem trước.')
        ctx = gate_context(direction, token, plate)
        ctx['source'] = 'camera'
        confident = is_valid_plate_format(plate) and metrics['confidence'] >= 0.65
        return jsonify(
            token=token, plate=plate, plate_key=plate_key(plate),
            valid=confident,
            confidence=metrics['confidence'], elapsed_ms=metrics['elapsed_ms'], engine=metrics['engine'],
            rect=list(rect) if rect is not None else None,
            width=int(width), height=int(height), preview_url=ctx['preview_url'],
            checked_plate=plate if ctx['mode'] and confident else '',
            can_confirm=bool(confident and ctx['mode'] and not (ctx['mode'] == 'entry' and ctx['no_slots'])),
            html=render_template('_gate_result.html', **ctx),
        )
    except (ValueError, OSError) as error:
        drop_tmp(token)
        return jsonify(error=f'Không đọc được ảnh camera: {error}'), 400
    except Exception:
        drop_tmp(token)
        app.logger.exception('Không nhận diện được khung hình camera')
        return jsonify(error='Lỗi nhận diện camera. Hãy bấm Bắt đầu để thử lại hoặc chọn Tải ảnh.'), 500
    finally:
        if ocr_held:
            CAMERA_OCR_LOCK.release()
        lane_lock.release()


def _resolve_ip_camera_url(slot):
    setting_key = ip_camera.CAMERA_SLOT_SETTING_KEYS.get(slot)
    if not setting_key:
        abort(404)
    raw = (request.args.get('url') or '').strip()
    if not raw:
        raw = database.get_setting(setting_key, '').strip()
    return ip_camera.normalize_ip_camera_url(raw)


@app.route('/api/camera/test', methods=['POST'])
@login_required
@staff_required
def test_ip_camera():
    """Kiểm tra kết nối tới camera IP (IP Webcam / RTSP / HTTP MJPEG)."""
    payload = request.get_json(silent=True) or {}
    raw_url = (payload.get('url') or request.form.get('url') or '').strip()
    result = ip_camera.probe_ip_camera(raw_url)
    return jsonify(result), (200 if result['ok'] else 400)


@app.route('/api/camera/select-lane', methods=['POST'])
@login_required
@staff_required
def select_lane_camera():
    """Đồng bộ lựa chọn camera của Làn vào / Làn ra giữa trang đơn làn, 2 làn và Thiết lập."""
    payload = request.get_json(silent=True) or {}
    direction = (payload.get('direction') or '').strip()
    device = (payload.get('device') or '').strip()[:120]
    if direction not in ('entry', 'exit'):
        return jsonify(ok=False, error='Hướng làn không hợp lệ.'), 400
    if ip_camera.is_ip_camera_url(device):
        device = ip_camera.normalize_ip_camera_url(device) or device
    key = f'{direction}_plate_camera'
    database.set_setting(key, device)
    return jsonify(ok=True, key=key, device=device)


@app.route('/gate/camera-stream/<slot>')
@login_required
@staff_required
def gate_camera_stream(slot):
    """Proxy luồng MJPEG từ camera IP (IP Webcam Android / RTSP) về cùng origin."""
    url = _resolve_ip_camera_url(slot)
    if not url:
        return jsonify(error='Chưa cấu hình URL camera IP hợp lệ.'), 400
    try:
        cap, first_frame, _ = ip_camera.open_ip_capture(url)
    except Exception as error:
        return jsonify(error=str(error)), 502
    return Response(
        stream_with_context(ip_camera.stream_mjpeg_frames(cap, first_frame)),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0'},
    )


@app.route('/gate/camera-snapshot/<slot>')
@login_required
@staff_required
def gate_camera_snapshot(slot):
    """Chụp 1 khung hình JPEG từ camera IP."""
    url = _resolve_ip_camera_url(slot)
    if not url:
        return jsonify(error='Chưa cấu hình URL camera IP hợp lệ.'), 400
    try:
        jpeg_bytes = ip_camera.capture_ip_camera_jpeg(url)
    except Exception as error:
        return jsonify(error=str(error)), 502
    return Response(
        jpeg_bytes,
        mimetype='image/jpeg',
        headers={'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0'},
    )


def handle_gate(direction):
    if request.method == 'GET':
        return render_gate(direction, plate=normalize_plate(request.args.get('plate', '')[:32]))

    action = request.form.get('action', 'recognize')
    note = request.form.get('note', '').strip()
    token = request.form.get('token', '').strip()
    token = token if find_tmp(token) else ''
    plate = clean_plate_input(request.form.get('plate'))

    if action in ('confirm', 'pay'):
        return gate_confirm(direction, token, plate, note)
    return gate_recognize(direction, token, plate, note)


def _gate_inline_json(direction, ok, message='', token='', plate='', note='', form=None, extra=None):
    ctx = gate_context(direction, token, plate, note, form)
    payload = {
        'ok': ok,
        'message': message,
        'token': ctx['token'],
        'plate': ctx['plate'],
        'checked_plate': ctx['plate'] if ctx['mode'] else '',
        'preview_url': ctx['preview_url'] or '',
        'can_confirm': bool(ctx['mode'] and not (ctx['mode'] == 'entry' and ctx['no_slots'])),
        'html': render_template('_gate_result.html', **ctx),
    }
    if extra:
        payload.update(extra)
    return jsonify(payload)


def gate_recognize(direction, token, plate, note):
    """Bước 1: nhận diện biển số từ ảnh mới; hoặc (không chọn ảnh mới) làm mới thông tin theo biển số vừa sửa."""
    inline = request.form.get('inline') == '1'
    file = request.files.get('image')
    has_file = bool(file and file.filename)

    if has_file:
        cleanup_tmp()
        drop_tmp(token)                                   # bỏ ảnh tạm cũ (nếu có)
        ext = os.path.splitext(file.filename)[1].lower()
        ext = ext if ext in ALLOWED_EXT else '.jpg'
        token = uuid.uuid4().hex[:12]
        path = os.path.join(TMP_FOLDER, token + ext)
        file.save(path)
        try:
            # Dùng chung mô hình OCR với camera của làn còn lại -> chờ tới lượt.
            if not CAMERA_OCR_LOCK.acquire(timeout=CAPTURE_OCR_WAIT_SECONDS):
                raise RuntimeError('hệ thống nhận diện đang bận, vui lòng thử lại')
            try:
                plate, annotated = recognize_plate_annotated(path)
            finally:
                CAMERA_OCR_LOCK.release()
            cv2.imwrite(os.path.join(TMP_FOLDER, f'{token}_ann.jpg'), annotated)
        except Exception as e:
            drop_tmp(token)
            msg = f'Lỗi khi nhận diện biển số: {e}'
            if inline:
                return _gate_inline_json(direction, False, msg, note=note)
            flash(msg, 'error')
            return render_gate(direction, note=note)
        if len(plate_key(plate)) < 4:
            msg = ('Không nhận diện được biển số rõ ràng. Bạn có thể nhập biển số vào ô bên dưới '
                   'rồi bấm "Cập nhật biển số" để tiếp tục, hoặc chọn / chụp ảnh khác (đủ sáng, ít góc nghiêng).')
            if inline:
                return _gate_inline_json(direction, False, msg, token, plate, note)
            flash(msg, 'error')
        if inline:
            return _gate_inline_json(direction, True, '', token, plate, note)
        return render_gate(direction, token, plate, note)

    if token:
        if len(plate_key(plate)) < 4:
            msg = 'Biển số quá ngắn, vui lòng nhập lại (tối thiểu 4 ký tự).'
            if inline:
                return _gate_inline_json(direction, False, msg, token, plate, note)
            flash(msg, 'error')
        if inline:
            return _gate_inline_json(direction, True, '', token, plate, note)
        return render_gate(direction, token, plate, note)

    msg = 'Vui lòng chọn ảnh hoặc bật camera rồi chụp ảnh biển số.'
    if inline:
        return _gate_inline_json(direction, False, msg, note=note)
    flash(msg, 'error')
    return render_gate(direction, note=note)


def gate_confirm(direction, token, plate, note):
    """Bước 2: kiểm tra trạng thái xe và xác nhận đúng chiều vào / ra đã chọn."""
    inline = request.form.get('inline') == '1'

    def fail(msg, tok=token, pl=plate, frm=None):
        if inline:
            return _gate_inline_json(direction, False, msg, tok, pl, note, frm)
        flash(msg, 'error')
        return render_gate(direction, tok, pl, note, frm)

    if not token:
        return fail('Chưa có ảnh đã nhận diện (hoặc ảnh đã hết hạn). Vui lòng nhận diện từ ảnh tải lên hoặc chụp từ camera.', tok='', pl='')

    if len(plate_key(plate)) < 4:
        return fail('Biển số quá ngắn, vui lòng nhập lại (tối thiểu 4 ký tự).')

    # Người dùng vừa sửa biển số sau khi nhận diện -> phải xem lại thông tin theo biển số mới
    checked = clean_plate_input(request.form.get('checked_plate'))
    if plate_key(plate) != plate_key(checked):
        return fail('Biển số đã thay đổi — vui lòng xem lại thông tin bên dưới rồi bấm "Xác nhận" lần nữa.')

    record = database.find_open_record(plate)
    if direction == 'entry' and record is not None:
        return fail(f'Xe {plate} đang gửi trong bãi, không thể ghi nhận xe vào lần nữa.')
    if direction == 'exit' and record is None:
        return fail(f'Không tìm thấy xe {plate} đang gửi trong bãi, không thể xác nhận xe ra.')

    # ---------- XE RA ----------
    if direction == 'exit':
        now = datetime.now()
        fee, duration, fee_note = calc_fee(record, now)
        disc_val = _to_int(request.form.get('discount_value'), 0) or 0
        disc_unit = request.form.get('discount_unit', 'vnd')
        if disc_val > 0 and fee > 0:
            if disc_unit == 'percent':
                pct = min(100, max(0, disc_val))
                fee = max(0, round(fee * (100 - pct) / 100))
                fee_note = f'{fee_note} · giảm {pct}%'
            else:
                fee = max(0, fee - disc_val)
                fee_note = f'{fee_note} · giảm {disc_val:,} ₫'
        payment_method = request.form.get('payment_method')
        if payment_method is not None and payment_method not in database.PAYMENT_METHODS:
            return fail('Phương thức thanh toán không hợp lệ.', frm=request.form)
        filename = promote_tmp(token, 'out')
        try:
            exit_slot = database.close_record(
                record['id'], filename, fee, note,
                payment_method=payment_method,
                exit_gate=_current_gate_name(),
            )
        except ValueError as error:
            os.remove(os.path.join(OUT_DIR, filename))
            if inline:
                return _gate_inline_json(direction, False, str(error), note=note)
            flash(str(error), 'error')
            return redirect(url_for('exit_gate', source=request.form.get('source', 'upload')))
        invoice_print_url = url_for('invoice_print', record_id=record['id'])
        success_text = f'✅ Xe {plate} đã ra bãi (vị trí {exit_slot or "?"}). Thời gian gửi: {duration}. Phí: {fee:,} VNĐ ({fee_note}).'
        if inline:
            return _gate_inline_json(direction, True, success_text, extra={
                'record_id': record['id'],
                'print_invoice': record['id'] if request.form.get('action') == 'pay' else None,
                'invoice_print_url': invoice_print_url,
            })
        flash(
            Markup(
                f'✅ Xe <b>{plate}</b> đã ra bãi (vị trí {exit_slot or "?"}). '
                f'Thời gian gửi: {duration}. Phí: {fee:,} VNĐ ({fee_note}). '
                f'<a href="{invoice_print_url}" target="_blank" style="margin-left:8px;font-weight:600;text-decoration:underline;">🖨️ In hóa đơn</a>'
            ),
            'success'
        )
        if request.form.get('action') == 'pay':
            return redirect(url_for('exit_gate',
                                    source=request.form.get('source', 'upload'),
                                    print_invoice=record['id']))
        return redirect(url_for('exit_gate', source=request.form.get('source', 'upload')))

    # ---------- XE VÀO ----------
    form = request.form
    entry_mode = database.get_user_setting(session['user_id'], 'entry_mode', 'auto')

    all_types = database.get_vehicle_types()
    registered = database.get_registered_vehicle(plate_key(plate))
    type_id = _to_int(form.get('vehicle_type_id'))
    # Xe đã đăng ký (có loại xe còn tồn tại) -> lấy loại xe theo đăng ký, bỏ qua lựa chọn trên form
    if registered and registered['vehicle_type_id'] \
            and any(t['id'] == registered['vehicle_type_id'] for t in all_types):
        type_id = registered['vehicle_type_id']
    vehicle_type = next((t for t in all_types if t['id'] == type_id), None)
    if vehicle_type is None:
        return fail('Vui lòng chọn loại xe.', frm=form)
    entry_price = database.find_turn_price(type_id, datetime.now())
    month_ok = month_ticket_valid(registered, date.today())
    if entry_price is None and not month_ok:
        return fail(f'Chưa có giá cho "{vehicle_type["name"]}" lúc {datetime.now():%H:%M}. '
                    'Vui lòng nhờ nhân viên/admin bổ sung ở trang Giá xe.', frm=form)

    if entry_mode == 'auto':
        chosen_slot = database.find_free_slot(vehicle_type_id=type_id)
        if not chosen_slot:
            return fail('Không còn ô trống phù hợp với loại xe đã chọn.', frm=form)
    else:
        chosen_slot = form.get('slot_name', '').strip()
        if not chosen_slot:
            return fail('Vui lòng chọn một vị trí đỗ.', frm=form)
        if not database.is_slot_available(chosen_slot, vehicle_type_id=type_id):
            return fail(f'Ô {chosen_slot} không còn trống hoặc không phù hợp với loại xe. Hãy chọn ô khác.', frm=form)

    filename = promote_tmp(token, 'in')
    try:
        _, chosen_slot = database.create_parking_entry(
            plate, filename, None if entry_mode == 'auto' else chosen_slot,
            type_id, vehicle_type['name'], note,
            entry_gate=_current_gate_name(),
        )
    except ValueError as error:
        os.remove(os.path.join(IN_DIR, filename))
        if inline:
            return _gate_inline_json(direction, False, str(error), note=note)
        flash(str(error), 'error')
        return redirect(url_for('entry', source=request.form.get('source', 'upload')))
    if month_ok:
        price_text = f'Vé tháng còn hạn đến {registered["expires_on"]} (tài khoản {registered["username"]})'
    else:
        price_text = (f'Giá khung vào: {entry_price["amount"]:,} VNĐ (khung {entry_price["period_name"]}); '
                      'sang khung giờ khác sẽ cộng thêm phí khung đó')
    success_text = f'✅ Xe vào bãi thành công! Biển số: {plate} — {vehicle_type["name"]} — Vị trí: {chosen_slot} — {price_text}'
    if inline:
        return _gate_inline_json(direction, True, success_text)
    flash(success_text, 'success')
    return redirect(url_for('entry', source=request.form.get('source', 'upload')))


@app.route('/entry', methods=['GET', 'POST'])
@login_required
@staff_required
def entry():
    return handle_gate('entry')


@app.route('/exit', methods=['GET', 'POST'])
@login_required
@staff_required
def exit_gate():
    return handle_gate('exit')


# ============================================================
# LỊCH SỬ
# ============================================================

@app.route('/history')
@login_required
def history():
    keyword = request.args.get('plate', '').strip().upper()
    keyword_key = plate_key(keyword)     # tìm không phân biệt dấu '-' (61T32222 vẫn ra 61T3-2222)
    status_filter = request.args.get('status', 'all')
    if status_filter not in ('all', 'IN', 'OUT', 'DELETED'):
        status_filter = 'all'
    date_filter = request.args.get('date', '')
    time_from = request.args.get('time_from', '').strip()
    time_to = request.args.get('time_to', '').strip()
    time_field = 'exit' if request.args.get('time_field') == 'exit' else 'entry'
    if any(value and not TIME_RE.fullmatch(value) for value in (time_from, time_to)):
        flash('Khung giờ không hợp lệ. Vui lòng chọn giờ theo HH:MM.', 'error')
        time_from = time_to = ''
    if date_filter:
        try:
            date.fromisoformat(date_filter)
        except ValueError:
            flash('Ngày lọc không hợp lệ.', 'error')
            date_filter = ''

    records = database.get_all_records()
    is_user = session.get('role') == 'user'
    if is_user:    # người dùng chỉ xem lịch sử của các xe mình đã đăng ký
        my_keys = {v['plate_key'] for v in database.get_user_vehicles(session['user_id'])}
        records = [r for r in records if plate_key(r['plate_number']) in my_keys]

    in_count = sum(1 for r in records if r['status'] == 'IN')
    out_count = sum(1 for r in records if r['status'] == 'OUT')
    deleted_count = sum(1 for r in records if r['status'] == 'DELETED')
    today_str = datetime.now().strftime('%Y-%m-%d')
    today_count = sum(1 for r in records if (r['entry_time'] or '').startswith(today_str))

    def matches(r):
        if keyword and keyword not in (r['plate_number'] or '').upper() \
                and not (keyword_key and keyword_key in plate_key(r['plate_number'])):
            return False
        if status_filter != 'all' and r['status'] != status_filter:
            return False
        if date_filter or time_from or time_to:
            timestamp = r['entry_time'] if time_field == 'entry' else r['exit_time']
            if not timestamp:
                return False
            minute = timestamp[11:16]
            if time_from and time_to and time_from > time_to:
                if date_filter:
                    next_date = (date.fromisoformat(date_filter) + timedelta(days=1)).isoformat()
                    return ((timestamp.startswith(date_filter) and minute >= time_from) or
                            (timestamp.startswith(next_date) and minute <= time_to))
                if not (minute >= time_from or minute <= time_to):
                    return False
            else:
                if date_filter and not timestamp.startswith(date_filter):
                    return False
                if (time_from and minute < time_from) or (time_to and minute > time_to):
                    return False
        return True

    filtered = [r for r in records if matches(r)]
    time_periods = [p for p in database.get_periods() if p['kind'] == 'time']
    selected_period = next((str(p['id']) for p in time_periods
                            if time_from == p['start_value'] and time_to == p['end_value']),
                           'custom' if time_from or time_to else '')

    return render_template(
        'history.html',
        records=filtered,
        keyword=keyword,
        status_filter=status_filter,
        date_filter=date_filter,
        total_count=len(records),
        in_count=in_count,
        out_count=out_count,
        deleted_count=deleted_count,
        time_from=time_from, time_to=time_to, time_field=time_field,
        time_periods=time_periods, selected_period=selected_period,
        today_count=today_count,
        user_mode=is_user,
    )


# ============================================================
# HÓA ĐƠN THU PHÍ GỬI XE
# ============================================================

@app.route('/invoices')
@login_required
def invoices():
    context = parking_invoices.invoice_context(request.args, session.get('role'), session['user_id'])
    return render_template('invoices.html', **context)


@app.route('/invoices/export')
@login_required
def invoices_export():
    from io import BytesIO
    context = parking_invoices.invoice_context(request.args, session.get('role'), session['user_id'])
    if context['errors']:
        abort(400, description=context['errors'][0])
    records = context['filtered']
    if request.args.get('ids'):
        try:
            selected = {int(value) for value in request.args['ids'].split(',')}
        except ValueError:
            abort(400)
        records = [record for record in records if record['id'] in selected]
    return send_file(BytesIO(parking_invoices.export_csv(records)),
                     mimetype='text/csv; charset=utf-8', as_attachment=True,
                     download_name=f'hoa-don-gui-xe_{date.today().isoformat()}.csv')


@app.route('/invoices/<int:record_id>/print')
@login_required
def invoice_print(record_id):
    invoice = next((item for item in parking_invoices.get_invoices(session.get('role'), session['user_id'])
                    if item['id'] == record_id), None)
    if invoice is None:
        abort(404)
    return render_template('invoice_print.html', invoice=invoice)


# ============================================================
# THỐNG KÊ
# ============================================================

@app.route('/statistics')
@login_required
@staff_required
def statistics():
    start, end, range_key, label = parse_stats_range(request.args)
    gate_param = request.args.get('gate')
    gate_name = gate_param.strip() if gate_param is not None else _current_gate_name()
    stats = database.get_statistics_for_gates(
        start.isoformat(),
        end.isoformat(),
        [gate_name] if gate_name else None,
    )
    area_stats = database.area_stats()
    if gate_name:
        gate_row = next((dict(z) for z in database.get_parking_zones(status='active') if (z['name'] or '').strip() == gate_name), None)
        if gate_row and (gate_row.get('area_names') or '').strip():
            allowed_areas = {a.strip() for a in gate_row['area_names'].split(',') if a.strip()}
            if allowed_areas:
                area_stats = {k: v for k, v in area_stats.items() if k in allowed_areas}
    records = database.get_records_between(start.isoformat(), end.isoformat(), gate_name=gate_name)
    view_mode = request.args.get('view', 'chart')
    if request.args.get('type') == 'eod' and 'view' not in request.args:
        view_mode = 'report'
    if view_mode not in ('chart', 'report'):
        view_mode = 'chart'
    concern = request.args.get('concern', 'revenue')
    if concern not in ('revenue', 'areas', 'records'):
        concern = 'revenue'
    eod_template = request.args.get('template', 'a4')
    if eod_template not in ('a4', 'k80', 'thermal'):
        eod_template = 'a4'
    eod_data = build_eod_report_data(report_date_iso=end.isoformat(), gate_name=gate_name)
    qs_dict = {'range': range_key, 'from': start.isoformat(), 'to': end.isoformat()}
    if gate_param is not None:
        qs_dict['gate'] = gate_name
    export_qs = urlencode(qs_dict)
    return render_template('statistics.html', stats=stats, area_stats=area_stats,
                           records=records, view_mode=view_mode, concern=concern,
                           eod_template=eod_template, eod_data=eod_data,
                           generated_at=datetime.now().strftime('%d/%m/%Y %H:%M'),
                           range_key=range_key, range_label=label,
                           date_from=start.isoformat(), date_to=end.isoformat(),
                           today_iso=date.today().isoformat(),
                           gate_choices=_employee_gate_choices(),
                           selected_gate_filter=gate_name,
                           export_qs=export_qs)


@app.route('/statistics/export/<fmt>')
@login_required
@staff_required
def statistics_export(fmt):
    """Xuất báo cáo trang Thống kê ra file Excel (.xlsx) hoặc PDF (.pdf) theo kỳ đang chọn."""
    if fmt not in ('xlsx', 'pdf'):
        abort(404)
    start, end, _range_key, label = parse_stats_range(request.args)
    gate_param = request.args.get('gate')
    gate_name = gate_param.strip() if gate_param is not None else _current_gate_name()
    payload = export_stats.make_payload(
        stats=database.get_statistics(start.isoformat(), end.isoformat(), gate_name=gate_name),
        area_stats=database.area_stats(),
        records=database.get_records_between(start.isoformat(), end.isoformat(), gate_name=gate_name),
        range_label=label,
        date_from=start.isoformat(),
        date_to=end.isoformat(),
        generated_by=session.get('fullname') or session.get('username') or '—',
    )
    try:
        buf, mimetype, ext = export_stats.build(fmt, payload)
    except export_stats.ExportError as e:
        flash(str(e), 'error')
        return redirect(url_for('statistics', **request.args))
    return send_file(
        buf,
        as_attachment=True,
        download_name=f'thong-ke_{start}_{end}.{ext}',
        mimetype=mimetype,
    )


def parse_stats_range(args):
    """Đọc bộ lọc thời gian của trang Thống kê -> (ngày bắt đầu, ngày kết thúc, mã lọc, nhãn hiển thị)."""
    today = date.today()
    key = args.get('range', 'today')
    if key == 'yesterday':
        d = today - timedelta(days=1)
        return d, d, key, 'hôm qua'
    if key == '7days':
        return today - timedelta(days=6), today, key, '7 ngày qua'
    if key == '30days':
        return today - timedelta(days=29), today, key, '30 ngày qua'
    if key == 'custom':
        try:
            start = date.fromisoformat(args.get('from', ''))
            end = date.fromisoformat(args.get('to', '')) if args.get('to') else start
        except ValueError:
            start = end = today
        if start > end:
            start, end = end, start
        if start == end:
            return start, end, key, f'ngày {start:%d/%m/%Y}'
        return start, end, key, f'{start:%d/%m/%Y} – {end:%d/%m/%Y}'
    return today, today, 'today', 'hôm nay'


# ============================================================
# CÀI ĐẶT CÁ NHÂN (MỌI NGƯỜI DÙNG TỰ CHỌN)
# ============================================================

DEVICE_SETTING_DEFAULTS = {
    'entry_plate_camera': '',
    'entry_overview_camera': '',
    'exit_plate_camera': '',
    'exit_overview_camera': '',
    'entry_barrier_port': 'COM3',
    'exit_barrier_port': 'COM4',
    'barrier_baudrate': '9600',
    'auto_open_barrier': '0',
    'printer_port': 'Mặc định trình duyệt',
}


def get_device_settings():
    return {
        key: database.get_setting(key, default)
        for key, default in DEVICE_SETTING_DEFAULTS.items()
    }


STORE_SETTING_DEFAULTS = {
    'store_name': 'Smart Parking Trung Tâm',
    'store_phone': '0901 234 567',
    'store_email': 'hotro@smartparking.vn',
    'store_type': 'Bãi xe thông minh 24/7',
    'store_address': '',
    'store_province': '',
    'store_district': '',
    'store_ward': '',
    'store_note': '',
}

ZONE_TYPE_LABELS = {
    'gate_inout': '2 làn (Vào & Ra)',
    'gate_in': 'Làn vào',
    'gate_out': 'Làn ra',
    'area': 'Khu vực đỗ xe',
}


def get_store_settings():
    return {key: database.get_setting(key, default) for key, default in STORE_SETTING_DEFAULTS.items()}


EMPLOYEE_SETTING_DEFAULTS = {
    'shift_morning': '06:00 - 14:00',
    'shift_afternoon': '14:00 - 22:00',
    'shift_night': '22:00 - 06:00',
    'emp_shifts_json': '',
    'emp_attendance_mode': 'shift',
    'emp_flex_start': '07:30',
    'emp_flex_end': '15:30',
    'emp_checkin_window_start': '04:30',
    'emp_checkin_window_end': '18:30',
    'emp_break_enabled': '0',
    'emp_break_start': '11:00',
    'emp_break_end': '12:00',
    'emp_standard_hours': '8',
    'emp_convert_hours_enabled': '0',
    'emp_auto_checkin': '0',
    'emp_unscheduled_checkin': '1',
    'emp_unscheduled_auto_approve': '1',
    'emp_multi_shift_single_punch': '0',
    'emp_checkin_software': '1',
    'emp_checkin_photo': '0',
    'emp_late_enabled': '1',
    'emp_late_grace_minutes': '10',
    'emp_early_leave_enabled': '1',
    'emp_early_leave_grace_minutes': '0',
    'emp_ot_before_enabled': '1',
    'emp_overtime_before_minutes': '0',
    'emp_ot_after_enabled': '1',
    'emp_overtime_after_minutes': '0',
    'emp_ot_actual_all': '0',
    'emp_overtime_enabled': '0',
    'emp_payroll_cutoff_day': '25',
    'emp_default_salary_type': 'shift',
    'emp_hourly_calc_mode': 'actual',
    'emp_auto_create_paysheet': '1',
    'emp_auto_update_paysheet': '1',
    'emp_salary_templates_json': '',
    'emp_allowances_json': '',
    'emp_deductions_json': '',
    'emp_work_days_json': '{}',
    'emp_holidays_json': '[]',
}


def get_employee_settings():
    return {key: database.get_setting(key, default) for key, default in EMPLOYEE_SETTING_DEFAULTS.items()}


DEFAULT_EMPLOYEE_SHIFTS = [
    {'id': 1, 'name': 'Ca sáng', 'start': '06:00', 'end': '14:00', 'checkin_start': '05:00', 'checkin_end': '15:00', 'gates': ['Cổng chính'], 'active': True},
    {'id': 2, 'name': 'Ca chiều', 'start': '14:00', 'end': '22:00', 'checkin_start': '13:00', 'checkin_end': '23:00', 'gates': ['Cổng chính'], 'active': True},
    {'id': 3, 'name': 'Ca đêm', 'start': '22:00', 'end': '06:00', 'checkin_start': '21:00', 'checkin_end': '07:00', 'gates': ['Cổng chính'], 'active': True},
]


def _shift_duration_label(start_str: str, end_str: str) -> str:
    try:
        sh, sm = [int(x) for x in start_str.split(':')[:2]]
        eh, em = [int(x) for x in end_str.split(':')[:2]]
        mins = (eh * 60 + em) - (sh * 60 + sm)
        if mins <= 0:
            mins += 24 * 60
        return f"{mins // 60} giờ {mins % 60} phút"
    except Exception:
        return "8 giờ 0 phút"


def get_employee_shifts():
    import json
    raw = database.get_setting('emp_shifts_json', '')
    if raw:
        try:
            items = json.loads(raw)
            if isinstance(items, list) and items:
                out = []
                for s in items:
                    st = s.get('start', '06:00')
                    en = s.get('end', '14:00')
                    gates = s.get('gates') or ['Cổng chính']
                    out.append({
                        'id': int(s.get('id') or 0),
                        'name': s.get('name', 'Ca làm việc'),
                        'start': st,
                        'end': en,
                        'checkin_start': s.get('checkin_start', st),
                        'checkin_end': s.get('checkin_end', en),
                        'gates': gates,
                        'gates_csv': ','.join(gates),
                        'gates_label': ', '.join(gates),
                        'active': bool(s.get('active', True)),
                        'time_range': f"{st} - {en}",
                        'duration_label': _shift_duration_label(st, en),
                    })
                return out
        except Exception:
            pass
    out = []
    for s in DEFAULT_EMPLOYEE_SHIFTS:
        item = dict(s)
        item['gates_csv'] = ','.join(item['gates'])
        item['gates_label'] = ', '.join(item['gates'])
        item['time_range'] = f"{item['start']} - {item['end']}"
        item['duration_label'] = _shift_duration_label(item['start'], item['end'])
        out.append(item)
    return out


DEFAULT_SALARY_TEMPLATES = [
    {
        'id': 1,
        'name': 'Ca trực tiêu chuẩn',
        'note': 'Áp dụng cho nhân viên trực cổng',
        'salary_type': 'shift',
        'salary_amount': 300000,
        'bonus_enabled': False,
        'bonus_type': 'Theo doanh thu',
        'bonus_amount': 0,
        'commission_enabled': False,
        'commission_type': 'Theo dịch vụ',
        'commission_rate': 0,
        'allowance_enabled': True,
        'allowance_amount': 500000,
        'allowances': [
            {'name': 'Phụ cấp ăn ca', 'type': 'Phụ cấp cố định hàng tháng', 'amount': 500000},
        ],
        'deduction_enabled': False,
        'deduction_amount': 0,
        'deduction_note': '',
        'deductions': [],
    },
]
DEFAULT_ALLOWANCES = [
    {'id': 1, 'name': 'Phụ cấp ăn ca', 'type': 'Phụ cấp hàng tháng cố định', 'amount': 500000, 'min_hours_enabled': False, 'min_hours': 0},
]
DEFAULT_DEDUCTIONS = [
    {'id': 1, 'name': 'Đi muộn / Về sớm', 'type': 'Đi muộn', 'condition': 'count', 'amount': 50000},
]


def _get_json_catalog(setting_key: str, default_items: list):
    import json
    raw = database.get_setting(setting_key, '')
    if raw:
        try:
            items = json.loads(raw)
            if isinstance(items, list):
                return items
        except Exception:
            pass
    return [dict(x) for x in default_items]


def get_employee_salary_templates():
    return _get_json_catalog('emp_salary_templates_json', DEFAULT_SALARY_TEMPLATES)


def get_employee_allowances():
    return _get_json_catalog('emp_allowances_json', DEFAULT_ALLOWANCES)


def get_employee_deductions():
    return _get_json_catalog('emp_deductions_json', DEFAULT_DEDUCTIONS)


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    section_param = request.args.get('section', 'devices')
    if section_param == 'vehicles':
        return redirect(url_for('pricing') + '#types')
    if section_param == 'employee' and request.method == 'GET':
        return redirect(url_for('employee_settings'))
    settings_section = (
        section_param if section_param in ('payment', 'devices', 'store', 'gates') else 'devices'
    )
    if session.get('role') == 'user':      # người dùng: trang cài đặt tài khoản riêng
        return render_user_settings()

    if request.method == 'POST':
        setting_type = request.form.get('setting_type')
        if setting_type == 'devices':
            if session.get('role') not in ('admin', 'manager'):
                abort(403)
            for key in DEVICE_SETTING_DEFAULTS:
                if key == 'auto_open_barrier':
                    val = '1' if request.form.get(key) == '1' else '0'
                else:
                    val = request.form.get(key, '').strip()[:120]
                    if key.endswith('_camera') and ip_camera.is_ip_camera_url(val):
                        val = ip_camera.normalize_ip_camera_url(val) or val
                database.set_setting(key, val)
            flash('Đã lưu cấu hình thiết bị.', 'success')
            return redirect(url_for('settings', section='devices'))

        if setting_type == 'payment':
            if session.get('role') not in ('admin', 'manager'):
                abort(403)
            bank_bin = request.form.get('vietqr_bank_bin', '').strip()
            bank_name = request.form.get('vietqr_bank_name', '').strip()
            acc_num = request.form.get('vietqr_account_number', '').strip()
            acc_name = request.form.get('vietqr_account_name', '').strip().upper()
            template = request.form.get('vietqr_template', 'compact2').strip()

            if not acc_num or not bank_bin:
                flash('Vui lòng chọn ngân hàng và nhập số tài khoản hợp lệ.', 'error')
                return redirect(url_for('settings', section='payment'))

            database.set_setting('vietqr_bank_bin', bank_bin)
            database.set_setting('vietqr_bank_name', bank_name or 'Ngân hàng')
            database.set_setting('vietqr_account_number', acc_num)
            database.set_setting('vietqr_account_name', acc_name or 'SMART PARKING')
            database.set_setting('vietqr_template', template or 'compact2')
            flash('Đã lưu cấu hình tài khoản nhận tiền VietQR thành công.', 'success')
            return redirect(url_for('settings', section='payment'))

        if setting_type == 'store':
            if session.get('role') not in ('admin', 'manager'):
                abort(403)
            store_name = request.form.get('store_name', '').strip()[:160]
            if not store_name:
                flash('Vui lòng nhập tên bãi xe.', 'error')
                return redirect(url_for('settings', section='store'))
            for key in STORE_SETTING_DEFAULTS:
                val = request.form.get(key, '').strip()[:255]
                database.set_setting(key, val)
            flash('Đã cập nhật thông tin bãi xe.', 'success')
            return redirect(url_for('settings', section='store'))

        if setting_type == 'employee':
            if session.get('role') != 'admin':
                abort(403)
            for key, default in EMPLOYEE_SETTING_DEFAULTS.items():
                if key == 'emp_auto_checkin':
                    val = '1' if request.form.get(key) == '1' else '0'
                elif key == 'emp_late_grace_minutes':
                    val = str(max(0, min(120, _to_int(request.form.get(key), 10) or 0)))
                else:
                    val = request.form.get(key, default).strip()[:60] or default
                database.set_setting(key, val)
            flash('Đã lưu thiết lập nhân viên.', 'success')
            return redirect(url_for('settings', section='employee'))

        return redirect(url_for('settings'))

    vietqr_bank_bin = database.get_setting('vietqr_bank_bin', '970407')
    vietqr_bank_name = database.get_setting('vietqr_bank_name', 'Techcombank')
    vietqr_account_number = database.get_setting('vietqr_account_number', '19036888888')
    vietqr_account_name = database.get_setting('vietqr_account_name', 'SMART PARKING')
    vietqr_template = database.get_setting('vietqr_template', 'compact2')
    store_settings = get_store_settings()
    zone_status = request.args.get('zone_status', '').strip()
    zone_q = request.args.get('zone_q', '').strip()
    lane_type = request.args.get('lane_type', '').strip()
    all_gates = [dict(z) for z in database.get_parking_zones()]
    gate_names_lower = {g['name'].strip().lower() for g in all_gates if g.get('name')}

    staff_users = [dict(u) for u in database.get_staff_users()]
    open_shifts_by_uid = {}
    try:
        for att in database.get_employee_attendance(limit=200):
            if att['status'] == 'working' and not att['check_out'] and att['user_id'] not in open_shifts_by_uid:
                open_shifts_by_uid[att['user_id']] = att['zone_name'] or ''
    except Exception:
        open_shifts_by_uid = {}

    def _staff_entry(u, active_zone=''):
        role_label = 'Quản trị viên' if u.get('role') == 'admin' else (u.get('position') or 'Nhân viên vận hành')
        return {
            'id': u['id'],
            'fullname': u.get('fullname') or u['username'],
            'username': u['username'],
            'role_label': role_label,
            'status': u.get('status') or 'active',
            'active_zone': active_zone,
        }

    gates = [dict(z) for z in database.get_parking_zones(status=zone_status, q=zone_q)]
    if lane_type in ('gate_in', 'gate_out', 'gate_inout'):
        gates = [g for g in gates if g.get('zone_type') == lane_type]

    vt_rows = database.get_vehicle_types()
    vt_map = {vt['id']: vt['name'] for vt in vt_rows}

    def _resolve_vt_display(raw_ids, fallback_id=None):
        ids = [int(x) for x in (raw_ids or '').split(',') if x.strip().isdigit()]
        if not ids and fallback_id:
            ids = [int(fallback_id)]
        names = [vt_map[i] for i in ids if i in vt_map]
        csv = ','.join(str(i) for i in ids if i in vt_map)
        label = ', '.join(names) if names else 'Tất cả loại xe'
        return csv, label

    def _wb_tokens(raw_wb):
        return [p.strip().lower() for p in (raw_wb or '').split(',') if p.strip()]

    for g in gates:
        g_lower = (g.get('name') or '').strip().lower()
        matched_staff = []
        for u in staff_users:
            wb_tokens = _wb_tokens(u.get('work_branch'))
            az = (open_shifts_by_uid.get(u['id']) or '').strip().lower()
            if g_lower in wb_tokens or (az and az == g_lower):
                matched_staff.append(_staff_entry(u, active_zone=open_shifts_by_uid.get(u['id'], '')))
        g['staff'] = matched_staff
        g['staff_count'] = len(matched_staff)
        g['operating_hours'] = g.get('operating_hours') or '24/7'
        g['is_central'] = False
        vt_csv, vt_label = _resolve_vt_display(g.get('vehicle_type_ids'), g.get('vehicle_type_id'))
        g['vehicle_type_ids'] = vt_csv
        g['vehicle_type_name'] = vt_label

    central_staff = []
    central_aliases = {'cổng chính', 'cong chinh', 'trung tâm', 'trung tam', 'bãi xe trung tâm'}
    for u in staff_users:
        wb_tokens = _wb_tokens(u.get('work_branch'))
        if not wb_tokens or any(t in central_aliases or t not in gate_names_lower for t in wb_tokens):
            central_staff.append(_staff_entry(u, active_zone=open_shifts_by_uid.get(u['id'], '')))

    raw_central_location = database.get_setting('central_gate_location')
    central_location = (store_settings.get('store_address') or 'Toàn bộ bãi xe') if raw_central_location is None else (raw_central_location or 'Toàn bộ bãi xe')
    central_zone_type = database.get_setting('central_gate_zone_type', 'gate_inout')
    if central_zone_type not in ZONE_TYPE_LABELS:
        central_zone_type = 'gate_inout'
    central_hours = database.get_setting('central_gate_hours', '24/7') or '24/7'
    central_vt_id = _to_int(database.get_setting('central_gate_vehicle_type_id', ''))
    central_vt_ids_raw = database.get_setting('central_gate_vehicle_type_ids', '')
    central_vt_csv, central_vt_name = _resolve_vt_display(central_vt_ids_raw, central_vt_id)
    raw_central_note = database.get_setting('central_gate_note')
    if raw_central_note is None:
        central_note = store_settings.get('store_note') or 'Cổng mặc định của bãi xe.'
    else:
        central_note = raw_central_note

    central_match_q = (
        not zone_q
        or zone_q.lower() in 'cổng chính'
        or zone_q.lower() in 'trung tâm'
        or zone_q.lower() in (store_settings.get('store_name') or '').lower()
        or zone_q.lower() in central_location.lower()
    )
    central_gate = None
    if zone_status in ('', 'active') and lane_type in ('', central_zone_type) and central_match_q:
        central_gate = {
            'id': 0,
            'is_central': True,
            'name': 'Cổng chính',
            'subtitle': store_settings.get('store_name') or 'Cổng mặc định của bãi xe',
            'zone_type': central_zone_type,
            'location': central_location,
            'vehicle_type_id': central_vt_id or '',
            'vehicle_type_ids': central_vt_csv,
            'vehicle_type_name': central_vt_name,
            'operating_hours': central_hours,
            'status': 'active',
            'note': central_note,
            'staff': central_staff,
            'staff_count': len(central_staff),
        }

    return render_template(
        'settings.html',
        settings_section=settings_section,
        banks=VIETNAM_BANKS,
        vietqr_bank_bin=vietqr_bank_bin,
        vietqr_bank_name=vietqr_bank_name,
        vietqr_account_number=vietqr_account_number,
        vietqr_account_name=vietqr_account_name,
        vietqr_template=vietqr_template,
        device_settings=get_device_settings(),
        store_settings=store_settings,
        employee_settings=get_employee_settings(),
        emp_total_count=len(staff_users),
        emp_salary_configured_count=sum(1 for u in staff_users if u.get('salary_type') or u.get('salary_amount')),
        salary_types=parking_employees.SALARY_TYPES,
        central_gate=central_gate,
        gates=gates,
        zone_status=zone_status,
        zone_q=zone_q,
        lane_type=lane_type,
        zone_type_labels=ZONE_TYPE_LABELS,
        vehicle_types=database.get_vehicle_types(),
        wheel_group=request.args.get('wheel_group', '').strip(),
        vehicle_q=request.args.get('vehicle_q', '').strip(),
    )


@app.route('/settings/zones/save', methods=['POST'])
@login_required
@staff_required
def save_zone():
    zone_id = _to_int(request.form.get('zone_id'))
    is_central = request.form.get('is_central') == '1' or zone_id == 0
    name = request.form.get('name', '').strip()[:80]
    zone_type = request.form.get('zone_type', 'gate_inout')
    if zone_type not in ZONE_TYPE_LABELS:
        zone_type = 'gate_inout'
    location = request.form.get('location', '').strip()[:160]
    selected_areas = [a.strip() for a in request.form.getlist('area_names') if a.strip()]
    area_names = ','.join(selected_areas)[:255]
    selected_vt_ids = [str(_to_int(x)) for x in request.form.getlist('vehicle_type_ids') if _to_int(x)]
    vehicle_type_id = _to_int(request.form.get('vehicle_type_id')) or None
    if not selected_vt_ids and vehicle_type_id:
        selected_vt_ids = [str(vehicle_type_id)]
    vehicle_type_ids_csv = ','.join(dict.fromkeys(selected_vt_ids))
    single_vt_id = int(selected_vt_ids[0]) if len(selected_vt_ids) == 1 else None
    operating_hours = request.form.get('operating_hours', '').strip()[:60] or '24/7'
    try:
        capacity = max(0, int(request.form.get('capacity') or 0))
    except ValueError:
        capacity = 0
    status = 'inactive' if request.form.get('status') == 'inactive' else 'active'
    note = request.form.get('note', '').strip()[:255]

    if is_central:
        database.set_setting('central_gate_location', location)
        database.set_setting('central_gate_zone_type', zone_type)
        database.set_setting('central_gate_hours', operating_hours)
        database.set_setting('central_gate_vehicle_type_id', str(single_vt_id or ''))
        database.set_setting('central_gate_vehicle_type_ids', vehicle_type_ids_csv)
        database.set_setting('central_gate_note', note)
        flash('Đã cập nhật cấu hình Cổng chính.', 'success')
        return redirect(url_for('settings', section='gates'))

    if not name:
        flash('Vui lòng nhập tên cổng.', 'error')
        return redirect(url_for('settings', section='gates'))
    if name.lower() in ('cổng chính', 'cong chinh', 'trung tâm', 'trung tam'):
        flash('Tên "Cổng chính" và "Trung tâm" đã được hệ thống sử dụng, vui lòng chọn tên cổng khác.', 'error')
        return redirect(url_for('settings', section='gates'))
    try:
        database.save_parking_zone(zone_id, name, zone_type, location, single_vt_id, capacity, status, note,
                                   operating_hours=operating_hours, area_names=area_names,
                                   vehicle_type_ids=vehicle_type_ids_csv)
        flash('Đã lưu cài đặt cổng.', 'success')
    except Exception:
        flash(f'Tên cổng "{name}" đã tồn tại.', 'error')
    return redirect(url_for('settings', section='gates'))


@app.route('/settings/zones/<int:zone_id>/toggle', methods=['POST'])
@login_required
@staff_required
def toggle_zone(zone_id):
    database.toggle_parking_zone(zone_id)
    flash('Đã cập nhật trạng thái cổng.', 'success')
    return redirect(url_for('settings', section='gates'))


@app.route('/settings/zones/<int:zone_id>/delete', methods=['POST'])
@login_required
@staff_required
def delete_zone(zone_id):
    database.delete_parking_zone(zone_id)
    flash('Đã xóa cổng.', 'success')
    return redirect(url_for('settings', section='gates'))


# ============================================================
# BẢNG GIÁ XE (AI CŨNG XEM; ADMIN / NHÂN VIÊN CHỈNH SỬA)
# ============================================================

TIME_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


def _to_int(value, default=None):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


@app.route('/pricing')
@login_required
def pricing():
    return render_template(
        'pricing.html',
        periods=database.get_periods(),
        vehicle_types=database.get_vehicle_types(),
        prices=database.get_prices(),
        ticket_labels=database.TICKET_LABELS,
        can_edit=session.get('role') in ('admin', 'manager'),
    )


@app.route('/pricing/export')
@login_required
def pricing_export():
    import csv
    import io
    vts = database.get_vehicle_types()
    periods = database.get_periods()
    prices = database.get_prices()
    pm = {(p['vehicle_type_id'], p['period_id']): p['amount'] for p in prices}
    wg_labels = {'2w': 'Xe 2 bánh', '4w': 'Xe 4 bánh', 'other': 'Khác'}

    buf = io.StringIO()
    buf.write('\ufeff')
    writer = csv.writer(buf)
    header = ['Loại phương tiện', 'Nhóm xe', 'Miễn phí đầu (phút)', 'Block đầu', 'Giờ tiếp theo', 'Giá trần 24h', 'Vé tháng cố định']
    header.extend(f"{p['name']} ({p['start_value']}-{p['end_value']})" for p in periods)
    writer.writerow(header)
    for vt in vts:
        row = [
            vt['name'],
            wg_labels.get(vt['wheel_group'] if 'wheel_group' in vt.keys() else '2w', 'Xe 2 bánh'),
            vt['free_minutes'],
            f"{vt['first_block_amount']} / {vt['first_block_hours']}h" if vt['first_block_hours'] else 'Theo khung giờ',
            vt['next_hour_amount'] if vt['first_block_hours'] else 0,
            vt['daily_cap'] or 'Không giới hạn',
            vt['monthly_price'] if vt['monthly_price'] is not None else 'Theo khung ngày',
        ]
        for p in periods:
            amt = pm.get((vt['id'], p['id']))
            row.append(amt if amt is not None else '')
        writer.writerow(row)
    return Response(
        buf.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="bang_gia_gui_xe.csv"'},
    )


@app.route('/pricing/period/save', methods=['POST'])
@login_required
@staff_required
def pricing_period_save():
    period_id = _to_int(request.form.get('id'))
    name = request.form.get('name', '').strip()
    kind = request.form.get('kind', 'time')
    start = request.form.get('start_value', '').strip()
    end = request.form.get('end_value', '').strip()

    if not name:
        flash('Vui lòng nhập tên khung thời gian.', 'error')
    elif kind not in ('time', 'day'):
        flash('Kiểu khung thời gian không hợp lệ.', 'error')
    elif database.period_name_taken(name, period_id):
        flash(f'Khung thời gian "{name}" đã tồn tại.', 'error')
    elif kind == 'time' and not (TIME_RE.match(start) and TIME_RE.match(end)):
        flash('Giờ bắt đầu/kết thúc phải có dạng HH:MM (vd 05:00).', 'error')
    elif kind == 'day' and not (
            _to_int(start) and _to_int(end)
            and 1 <= _to_int(start) <= 31 and 1 <= _to_int(end) <= 31
            and _to_int(start) <= _to_int(end)):
        flash('Ngày bắt đầu/kết thúc phải từ 1 đến 31 và ngày bắt đầu không lớn hơn ngày kết thúc.', 'error')
    else:
        if kind == 'day':
            start, end = f"{_to_int(start):02d}", f"{_to_int(end):02d}"
        database.save_period(period_id, name, kind, start, end)
        flash(f'Đã lưu khung thời gian "{name}".', 'success')
    return redirect(url_for('pricing'))


@app.route('/pricing/period/<int:period_id>/delete', methods=['POST'])
@login_required
@staff_required
def pricing_period_delete(period_id):
    database.delete_period(period_id)
    flash('Đã xóa khung thời gian (và các giá liên quan).', 'success')
    return redirect(url_for('pricing'))


@app.route('/pricing/type/save', methods=['POST'])
@login_required
@staff_required
def pricing_type_save():
    type_id = _to_int(request.form.get('id'))
    name = request.form.get('name', '').strip()
    grace = _to_int(request.form.get('grace_minutes', '0'))
    cap = _to_int(request.form.get('daily_cap', '0'))
    fields = ('free_minutes', 'first_block_hours', 'first_block_amount', 'next_hour_amount')
    policy = {key: _to_int(request.form.get(key, '0')) for key in fields}
    raw_monthly = request.form.get('monthly_price', '').strip()
    monthly = _to_int(raw_monthly) if raw_monthly else None
    wheel_group = request.form.get('wheel_group', '').strip()
    if wheel_group not in ('2w', '4w', 'other'):
        nl = name.lower()
        wheel_group = '4w' if ('ô tô' in nl or 'o to' in nl or 'xe tải' in nl or '4 bánh' in nl) else '2w'
    invalid = any(value is None or not 0 <= value <= 2147483647 for value in policy.values())
    invalid = invalid or (raw_monthly != '' and (monthly is None or not 0 <= monthly <= 2147483647))
    invalid = invalid or (policy['free_minutes'] is not None and policy['free_minutes'] > 1440)
    invalid = invalid or (policy['first_block_hours'] is not None and policy['first_block_hours'] > 24)
    invalid = invalid or (policy['first_block_hours'] == 0 and (policy['first_block_amount'] or policy['next_hour_amount']))
    if invalid or grace is None or cap is None or not 0 <= grace <= 1440 or not 0 <= cap <= 2147483647:
        flash('Cấu hình không hợp lệ: số phút từ 0–1440, block từ 0–24 giờ, tiền là số nguyên không âm tối đa 2.147.483.647 đồng. Khi tắt block, phí block và giờ tiếp theo phải bằng 0.', 'error')
    elif not name:
        flash('Vui lòng nhập tên loại xe.', 'error')
    elif database.vehicle_type_name_taken(name, type_id):
        flash(f'Loại xe "{name}" đã tồn tại.', 'error')
    else:
        database.save_vehicle_type(type_id, name, grace, cap, **policy, monthly_price=monthly, wheel_group=wheel_group)
        flash(f'Đã lưu loại xe "{name}".', 'success')
    if request.form.get('next') == 'settings_vehicles':
        return redirect(url_for('settings', section='vehicles'))
    return redirect(url_for('pricing'))


@app.route('/pricing/type/<int:type_id>/delete', methods=['POST'])
@login_required
@staff_required
def pricing_type_delete(type_id):
    database.delete_vehicle_type(type_id)
    flash('Đã xóa loại xe (và các giá liên quan).', 'success')
    if request.form.get('next') == 'settings_vehicles':
        return redirect(url_for('settings', section='vehicles'))
    return redirect(url_for('pricing'))


@app.route('/pricing/price/save', methods=['POST'])
@login_required
@staff_required
def pricing_price_save():
    price_id = _to_int(request.form.get('id'))
    type_id = _to_int(request.form.get('vehicle_type_id'))
    period_id = _to_int(request.form.get('period_id'))
    amount = _to_int(request.form.get('amount'))
    ticket_type = request.form.get('ticket_type', 'turn')

    valid_types = {t['id'] for t in database.get_vehicle_types()}
    period_kinds = {p['id']: p['kind'] for p in database.get_periods()}

    if type_id not in valid_types or period_id not in period_kinds:
        flash('Vui lòng chọn loại xe và khung thời gian (tạo trước nếu chưa có).', 'error')
    elif amount is None or amount < 0:
        flash('Giá tiền phải là số nguyên không âm.', 'error')
    elif ticket_type not in database.TICKET_LABELS:
        flash('Loại vé không hợp lệ.', 'error')
    elif ticket_type == 'month' and period_kinds[period_id] != 'day':
        flash('Vé Tháng phải chọn khung thời gian kiểu "Theo ngày trong tháng" (vd: Tháng, ngày 01–30).', 'error')
    elif ticket_type == 'turn' and period_kinds[period_id] != 'time':
        flash('Vé Lượt phải chọn khung thời gian kiểu "Theo giờ" (vd: Sáng 05:00–12:59).', 'error')
    elif database.price_exists(type_id, period_id, price_id):
        flash('Loại xe này đã có giá cho khung thời gian đó, hãy sửa dòng có sẵn.', 'error')
    else:
        database.save_price(price_id, type_id, period_id, amount, ticket_type)
        flash('Đã lưu giá xe.', 'success')
    return redirect(url_for('pricing'))


@app.route('/pricing/price/<int:price_id>/delete', methods=['POST'])
@login_required
@staff_required
def pricing_price_delete(price_id):
    database.delete_price(price_id)
    flash('Đã xóa giá xe.', 'success')
    return redirect(url_for('pricing'))


# ============================================================
# QUẢN LÝ TÀI KHOẢN NGƯỜI DÙNG
#   - Admin: tạo tài khoản người dùng + nhân viên, sửa, đổi mật khẩu, khóa, xóa.
#   - Nhân viên (manager): chỉ thấy/tạo/sửa tài khoản NGƯỜI DÙNG (không tạo được nhân viên,
#     không đổi mật khẩu, không khóa/xóa).
#   - Tài khoản người dùng có thể đăng ký xe (biển số nhận diện từ ảnh hoặc nhập tay) + loại vé.
# ============================================================

TICKET_LABELS = {'turn': 'Vé lượt', 'month': 'Vé tháng'}
MIN_PASSWORD_LEN = 4
MAX_MONTHS = 36   # số tháng tối đa cho mỗi lần thuê / gia hạn


def add_months(d, n):
    """Cộng n tháng lịch (ngày vượt quá cuối tháng thì lấy ngày cuối tháng, vd 31/01 + 1 tháng = 28/02)."""
    y, m = divmod(d.month - 1 + n, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def month_ticket_period(start, months):
    """Vé tháng thuê từ ngày `start` trong `months` tháng -> ngày cuối cùng còn hiệu lực."""
    return add_months(start, months) - timedelta(days=1)


def build_price_info():
    """Giá theo loại xe để hiển thị khi đăng ký vé: giá tháng + các khung giá lượt."""
    today = date.today()
    info = {}
    for t in database.get_vehicle_types():
        mp = database.find_month_price(t['id'], today)
        info[t['id']] = {'month': mp['amount'] if mp else None, 'turn': []}
        if t['first_block_hours'] > 0:
            info[t['id']]['turn'].append({
                'name': f"Block đầu {t['first_block_hours']} giờ; sau đó {t['next_hour_amount']:,} ₫/giờ",
                'amount': t['first_block_amount'], 'start': '00:00', 'end': '23:59'})
    block_types = {t['id'] for t in database.get_vehicle_types() if t['first_block_hours'] > 0}
    for r in database.get_prices():
        if r['ticket_type'] == 'turn' and r['vehicle_type_id'] in info and r['vehicle_type_id'] not in block_types:
            info[r['vehicle_type_id']]['turn'].append(
                {'name': r['period_name'], 'amount': r['amount'],
                 'start': r['start_value'], 'end': r['end_value']})
    return info


@app.template_filter('vdate')
def vdate_filter(value):
    """2026-10-06 -> 06/10/2026"""
    try:
        return date.fromisoformat(value).strftime('%d/%m/%Y')
    except (TypeError, ValueError):
        return value or '—'


@app.template_filter('days_left')
def days_left_filter(value):
    """Số ngày còn lại từ hôm nay đến ngày YYYY-MM-DD (0 = hôm nay là ngày cuối)."""
    try:
        return (date.fromisoformat(value) - date.today()).days
    except (TypeError, ValueError):
        return 0


@app.template_filter('vnd')
def vnd_filter(value):
    return '{:,}'.format(int(value or 0)).replace(',', '.') + ' đ'


def can_manage_user(target):
    """Admin quản lý được mọi tài khoản; nhân viên chỉ quản lý tài khoản 'user'."""
    if target is None:
        return False
    if session.get('role') == 'admin':
        return True
    return session.get('role') == 'manager' and target['role'] == 'user'


def parse_vehicle_forms(form):
    """Đọc danh sách xe từ form (các ô cùng tên: plate, vehicle_type_id, ticket_type, months).
    Dòng không nhập biển số sẽ bị bỏ qua.
    Vé tháng: giá lấy từ Bảng giá (giá tháng x số tháng), bắt đầu tính từ HÔM NAY (lúc tạo).
    Trả về (danh sách xe hợp lệ, danh sách lỗi, dữ liệu để điền lại form)."""
    plates = form.getlist('plate')
    types = form.getlist('vehicle_type_id')
    tickets = form.getlist('ticket_type')
    months_list = form.getlist('months')
    type_names = {t['id']: t['name'] for t in database.get_vehicle_types()}
    today = date.today()

    vehicles, errors, prefill, seen = [], [], [], set()
    for i, raw in enumerate(plates):
        raw = (raw or '').strip()
        if not raw:
            continue
        get = lambda lst: lst[i] if i < len(lst) else ''
        prefill.append({'plate': raw, 'type': get(types), 'ticket': get(tickets) or 'turn',
                        'months': get(months_list) or '1'})

        plate = clean_plate_input(raw)
        key = plate_key(plate)
        label = f'Xe {raw}'
        if len(key) < 4:
            errors.append(f'{label}: biển số quá ngắn (tối thiểu 4 ký tự).')
            continue
        if key in seen:
            errors.append(f'{label}: biển số bị nhập trùng trong danh sách.')
            continue
        seen.add(key)
        owner = database.find_vehicle_owner(key)
        if owner is not None:
            errors.append(f'{label}: biển số đã được đăng ký cho tài khoản "{owner["username"]}".')
            continue
        type_id = _to_int(get(types))
        if type_id not in type_names:
            errors.append(f'{label}: vui lòng chọn loại xe.')
            continue
        ticket = get(tickets)
        if ticket not in TICKET_LABELS:
            ticket = 'turn'

        v = {'plate_number': plate, 'key': key, 'vehicle_type_id': type_id, 'ticket_type': ticket,
             'expires_on': None, 'start_on': None, 'months': None, 'paid_amount': None}
        if ticket == 'month':
            months = _to_int(get(months_list))
            if not months or not 1 <= months <= MAX_MONTHS:
                errors.append(f'{label}: số tháng thuê phải từ 1 đến {MAX_MONTHS}.')
                continue
            price = database.find_month_price(type_id, today)
            if price is None:
                errors.append(f'{label}: Bảng giá chưa có giá vé tháng cho loại xe "{type_names[type_id]}". '
                              f'Hãy thêm giá tháng ở trang Giá xe hoặc chọn vé lượt.')
                continue
            v.update(start_on=today.isoformat(), months=months,
                     expires_on=month_ticket_period(today, months).isoformat(),
                     paid_amount=price['amount'] * months)
        vehicles.append(v)
    return vehicles, errors, prefill


def save_vehicles(user_id, vehicles):
    for v in vehicles:
        database.add_user_vehicle(user_id, v['plate_number'], v['key'], v['vehicle_type_id'],
                                  v['ticket_type'], v['expires_on'], v['start_on'], v['months'],
                                  v['paid_amount'])


def render_customers(**extra):
    context = parking_customers.customer_context(request.args)
    context.update(vehicle_types=database.get_vehicle_types(), ticket_labels=TICKET_LABELS,
                   today=date.today().isoformat(), price_info=build_price_info(), max_months=MAX_MONTHS,
                   min_password_len=MIN_PASSWORD_LEN,
                   form=None, form_vehicles=None, form_errors=[], edit_form=None, edit_errors=[],
                   open_modal=False, open_edit_modal=False)
    context.update(extra)
    return render_template('customers.html', **context)


def render_accounts(**extra):
    staff_users = database.get_staff_users()
    customers = database.get_customer_users()
    active_gates = [dict(z) for z in database.get_parking_zones(status='active')]
    context = parking_employees.employee_context(staff_users, request.args, active_gates=active_gates)
    parking_employees.attach_attendance(
        context['filtered_employees'],
        database.get_employee_attendance(limit=1000),
        month=context['filters']['month'],
    )
    context.update({
        'staff_users': staff_users,
        'customer_count': len(customers),
        'payroll_totals': parking_employees.payroll_totals(context['filtered_employees']),
        'zones': active_gates,
        'employee_shifts': [s for s in get_employee_shifts() if s['active']],
        'salary_templates_data': get_employee_salary_templates(),
        'salary_templates': [t['name'] for t in get_employee_salary_templates() if t.get('name')],
        'allowances_catalog': get_employee_allowances(),
        'deductions_catalog': get_employee_deductions(),
        'today': date.today().isoformat(),
        'active_tab': 'accounts',
        'form': None,
        'form_errors': [],
        'edit_form': None,
        'edit_errors': [],
        'open_modal': False,
        'open_edit_modal': False,
        'min_password_len': MIN_PASSWORD_LEN,
    })
    context.update(extra)
    return render_template('accounts.html', **context)


def render_users(**extra):
    return render_customers(**extra)


def render_edit_user(target, **extra):
    return render_template('edit_user.html', target=target,
                           vehicles=database.get_user_vehicles(target['id']),
                           vehicle_types=database.get_vehicle_types(),
                           ticket_labels=TICKET_LABELS, today=date.today().isoformat(),
                           price_info=build_price_info(), max_months=MAX_MONTHS,
                           **extra)


@app.route('/customers')
@login_required
@staff_required
def customers():
    return render_customers()


@app.route('/customers/export')
@login_required
@staff_required
def customers_export():
    from io import BytesIO
    context = parking_customers.customer_context(request.args)
    if context['filter_errors']:
        abort(400, description=context['filter_errors'][0])
    rows = context['filtered_customers']
    if request.args.get('ids'):
        try:
            selected = {int(value) for value in request.args['ids'].split(',')}
        except ValueError:
            abort(400)
        rows = [customer for customer in rows if customer['id'] in selected]
    return send_file(BytesIO(parking_customers.export_customers(rows)), as_attachment=True,
                     mimetype='text/csv; charset=utf-8', download_name=f'khach-hang_{date.today().isoformat()}.csv')


@app.route('/customers/<int:user_id>/profile', methods=['POST'])
@login_required
@staff_required
def customer_profile_save(user_id):
    target = database.get_user_by_id(user_id)
    if target is None or target['role'] != 'user' or not can_manage_user(target):
        abort(403)
    profile, errors = parking_customers.parse_profile(request.form)
    if errors:
        return render_customers(open_edit_modal=True,
                                edit_form=dict(profile, id=user_id, username=target['username'], code=f'KH{user_id:06d}'),
                                edit_errors=errors)
    database.update_customer_profile(user_id, **profile)
    flash('Đã cập nhật hồ sơ khách hàng.', 'success')
    return redirect(url_for('customers', open=user_id))


@app.route('/accounts')
@login_required
@admin_required
def accounts():
    return render_accounts()


@app.route('/accounts/export')
@login_required
@admin_required
def accounts_export():
    from io import BytesIO
    fmt = request.args.get('format', 'csv').lower()
    if fmt not in ('csv', 'xlsx', 'pdf'):
        abort(400)
    staff_users = database.get_staff_users()
    context = parking_employees.employee_context(staff_users, request.args)
    rows = context['filtered_employees']
    if request.args.get('ids'):
        try:
            selected = {int(value) for value in request.args['ids'].split(',')}
        except ValueError:
            abort(400)
        rows = [emp for emp in rows if emp['id'] in selected]
    parking_employees.attach_attendance(
        rows,
        database.get_employee_attendance(limit=1000),
        month=context['filters']['month'],
    )
    generated_by = session.get('fullname') or session.get('username') or 'Admin'
    data, mimetype, ext = parking_employees.export_employees_file(rows, fmt=fmt, generated_by=generated_by)
    return send_file(
        BytesIO(data),
        as_attachment=True,
        mimetype=mimetype,
        download_name=f'nhan-vien_{date.today().isoformat()}.{ext}',
    )


@app.route('/accounts/payroll/export')
@login_required
@admin_required
def accounts_payroll_export():
    from io import BytesIO
    fmt = request.args.get('format', 'xlsx').lower()
    if fmt not in ('xlsx', 'pdf', 'csv'):
        abort(400)
    staff_users = database.get_staff_users()
    context = parking_employees.employee_context(staff_users, request.args)
    rows = context['filtered_employees']
    if request.args.get('ids'):
        try:
            selected = {int(value) for value in request.args['ids'].split(',')}
        except ValueError:
            abort(400)
        rows = [emp for emp in rows if emp['id'] in selected]
    month = context['filters']['month']
    parking_employees.attach_attendance(
        rows,
        database.get_employee_attendance(limit=1000),
        month=month,
    )
    generated_by = session.get('fullname') or session.get('username') or 'Admin'
    data, mimetype, ext = parking_employees.export_payroll(rows, fmt=fmt, month=month, generated_by=generated_by)
    period_tag = month or date.today().isoformat()
    return send_file(
        BytesIO(data),
        as_attachment=True,
        mimetype=mimetype,
        download_name=f'bang-luong_{period_tag}.{ext}',
    )


@app.route('/accounts/<int:user_id>/profile', methods=['POST'])
@login_required
@admin_required
def employee_profile_save(user_id):
    target = database.get_user_by_id(user_id)
    if target is None or target['role'] not in ('admin', 'manager'):
        abort(403)
    emp_data = parking_employees.parse_employee_form(request.form)
    if target['username'] == 'admin':
        emp_data['role'] = 'admin'
    if not emp_data['fullname']:
        flash('Vui lòng nhập tên nhân viên.', 'error')
        return render_accounts(
            open_edit_modal=True,
            edit_form=dict(emp_data, id=user_id, username=target['username']),
            edit_errors=['Vui lòng nhập tên nhân viên.'],
        )
    database.update_employee_profile(user_id, **emp_data)
    flash('Đã cập nhật hồ sơ & thiết lập lương nhân viên.', 'success')
    return redirect(url_for('accounts', open=user_id))


@app.route('/attendance/check-in', methods=['POST'])
@login_required
@staff_required
def attendance_check_in():
    shift_name = request.form.get('shift_name', 'Ca ngày').strip()[:60] or 'Ca ngày'
    zone_name = request.form.get('zone_name', '').strip()[:80]
    note = request.form.get('note', '').strip()[:255]
    database.clock_in_employee(session['user_id'], shift_name=shift_name, zone_name=zone_name, note=note)
    flash(f'Đã chấm công vào {shift_name}.', 'success')
    return redirect(request.referrer or url_for('index'))


@app.route('/attendance/check-out', methods=['POST'])
@login_required
@staff_required
def attendance_check_out():
    note = request.form.get('note', '').strip()[:255]
    if database.clock_out_employee(session['user_id'], note=note):
        flash('Đã chấm công tan ca.', 'success')
    else:
        flash('Bạn chưa chấm công vào ca.', 'error')
    return redirect(request.referrer or url_for('index'))


@app.route('/accounts/<int:user_id>/attendance', methods=['POST'])
@login_required
@admin_required
def employee_add_attendance(user_id):
    target = database.get_user_by_id(user_id)
    if target is None or target['role'] not in ('admin', 'manager'):
        abort(403)
    work_date = request.form.get('work_date', '').strip() or date.today().isoformat()
    shift_name = request.form.get('shift_name', 'Ca ngày').strip()[:60] or 'Ca ngày'
    zone_name = request.form.get('zone_name', '').strip()[:80]
    status = request.form.get('status', 'completed')
    if status not in ('completed', 'late', 'leave', 'working'):
        status = 'completed'
    note = request.form.get('note', '').strip()[:255]
    check_in_time = request.form.get('check_in_time', '').strip()
    check_out_time = request.form.get('check_out_time', '').strip()
    ci = f"{work_date}T{check_in_time}:00" if check_in_time else ''
    co = f"{work_date}T{check_out_time}:00" if check_out_time else ''
    database.add_manual_attendance(user_id, work_date, shift_name, status, ci, co, zone_name, note)
    flash(f'Đã ghi nhận chấm công cho {target["fullname"]}.', 'success')
    return redirect(url_for('accounts', open=user_id))


def _week_window(week_str: str):
    """Trả về (monday_date, days_list, prev_week_str, next_week_str, week_label)."""
    from datetime import timedelta
    base = date.today()
    if week_str:
        try:
            base = date.fromisoformat(week_str)
        except ValueError:
            pass
    monday = base - timedelta(days=base.weekday())
    day_names = ['Thứ hai', 'Thứ ba', 'Thứ tư', 'Thứ năm', 'Thứ sáu', 'Thứ bảy', 'Chủ nhật']
    days = []
    today_iso = date.today().isoformat()
    for i in range(7):
        d = monday + timedelta(days=i)
        days.append({
            'iso': d.isoformat(),
            'label': day_names[i],
            'day_num': d.day,
            'is_today': d.isoformat() == today_iso,
        })
    week_num = monday.isocalendar()[1]
    week_label = f"Tuần {week_num} - Th. {monday.month:02d} {monday.year}"
    return (
        monday,
        days,
        (monday - timedelta(days=7)).isoformat(),
        (monday + timedelta(days=7)).isoformat(),
        week_label,
    )


def _employee_gate_choices():
    active_gates = [dict(z) for z in database.get_parking_zones(status='active')]
    choices = ['Cổng chính']
    for g in active_gates:
        gname = (g.get('name') or '').strip()
        if gname and gname.lower() not in ('cổng chính', 'cong chinh') and gname not in choices:
            choices.append(gname)
    return choices


def _schedule_expected_pay(emp: dict, shift_count: int) -> int:
    if not shift_count:
        return 0
    stype = emp.get('salary_type') or ''
    samount = int(emp.get('salary_amount') or 0)
    if not samount:
        return 0
    if stype == 'shift':
        return shift_count * samount
    if stype == 'hour':
        return shift_count * 8 * samount
    if stype == 'standard_day':
        return round(samount / 26 * shift_count)
    if stype == 'month':
        return samount
    return shift_count * samount


@app.route('/employees/schedule', methods=['GET', 'POST'])
@login_required
@admin_required
def employee_schedule():
    from datetime import timedelta
    if request.method == 'POST':
        schedule_id = _to_int(request.form.get('schedule_id'))
        uid = _to_int(request.form.get('user_id'))
        work_date = request.form.get('work_date', '').strip() or date.today().isoformat()
        shift_name = request.form.get('shift_name', 'Ca sáng').strip()[:60] or 'Ca sáng'
        gate_name = request.form.get('gate_name', 'Cổng chính').strip()[:120] or 'Cổng chính'
        note = request.form.get('note', '').strip()[:255]
        view_mode = request.form.get('view_mode', 'employee').strip()
        if view_mode not in ('employee', 'shift'):
            view_mode = 'employee'

        target = database.get_user_by_id(uid) if uid else None
        if target is None or target['role'] not in ('admin', 'manager'):
            flash('Vui lòng chọn nhân viên hợp lệ.', 'error')
        elif schedule_id:
            database.update_employee_schedule(schedule_id, uid, work_date, shift_name, gate_name, note)
            flash(f'Đã cập nhật lịch {shift_name} ({gate_name}) cho {target["fullname"]}.', 'success')
        else:
            target_uids = [uid]
            if request.form.get('apply_other_employees') == '1':
                for extra_raw in request.form.getlist('extra_user_ids'):
                    euid = _to_int(extra_raw)
                    if euid and euid not in target_uids:
                        eu = database.get_user_by_id(euid)
                        if eu and eu['role'] in ('admin', 'manager'):
                            target_uids.append(euid)

            dates_to_add = [work_date]
            if request.form.get('repeat_weekly') == '1':
                rep_days = {_to_int(d) for d in request.form.getlist('repeat_days') if _to_int(d) is not None}
                if rep_days:
                    try:
                        base_d = date.fromisoformat(work_date)
                    except ValueError:
                        base_d = date.today()
                    end_raw = request.form.get('repeat_end', '').strip()
                    try:
                        end_d = date.fromisoformat(end_raw) if end_raw else (base_d + timedelta(days=6))
                    except ValueError:
                        end_d = base_d + timedelta(days=6)
                    end_d = min(end_d, base_d + timedelta(days=56))
                    dates_to_add = []
                    cur_d = base_d
                    while cur_d <= end_d:
                        if cur_d.weekday() in rep_days:
                            dates_to_add.append(cur_d.isoformat())
                        cur_d += timedelta(days=1)
                    if not dates_to_add:
                        dates_to_add = [work_date]

            for t_uid in target_uids:
                for d_iso in dates_to_add:
                    database.add_employee_schedule(t_uid, d_iso, shift_name, gate_name, note)
            flash(f'Đã xếp {shift_name} ({gate_name}) cho {len(target_uids)} nhân viên.', 'success')
        return redirect(url_for(
            'employee_schedule',
            week=request.form.get('week', ''),
            gate=request.form.get('filter_gate', ''),
            q=request.form.get('filter_q', ''),
            view=view_mode,
        ))

    week_str = request.args.get('week', '').strip()
    gate_filter = request.args.get('gate', '').strip()
    q = request.args.get('q', '').strip().lower()
    view_mode = request.args.get('view', 'employee').strip()
    if view_mode not in ('employee', 'shift'):
        view_mode = 'employee'

    monday, days, prev_week, next_week, week_label = _week_window(week_str)
    gate_choices = _employee_gate_choices()

    staff_rows = [parking_employees.enrich_employee(u) for u in database.get_staff_users() if u['status'] == 'active']
    if gate_filter:
        gf_l = gate_filter.lower()
        staff_rows = [e for e in staff_rows if any(b.lower() == gf_l for b in e.get('work_branches_list', []))]
    if q:
        staff_rows = [e for e in staff_rows if q in (e['fullname'] + ' ' + e['code'] + ' ' + e['username']).lower()]

    sched_rows = database.get_employee_schedules(days[0]['iso'], days[-1]['iso'], gate_name=gate_filter)
    by_user_day = {}
    by_shift_day = {}
    user_shift_counts = {}
    for s in sched_rows:
        by_user_day.setdefault((s['user_id'], s['work_date']), []).append(s)
        by_shift_day.setdefault((s['shift_name'], s['work_date']), []).append(s)
        user_shift_counts[s['user_id']] = user_shift_counts.get(s['user_id'], 0) + 1

    total_expected_pay = 0
    for emp in staff_rows:
        cnt = user_shift_counts.get(emp['id'], 0)
        exp_pay = _schedule_expected_pay(emp, cnt)
        emp['week_shift_count'] = cnt
        emp['week_expected_pay'] = exp_pay
        total_expected_pay += exp_pay

    active_shifts = [s for s in get_employee_shifts() if s['active']]
    return render_template(
        'employee_schedule.html',
        active_page='employee_schedule',
        employees=staff_rows,
        days=days,
        week=monday.isoformat(),
        prev_week=prev_week,
        next_week=next_week,
        week_label=week_label,
        gate_choices=gate_choices,
        employee_shifts=active_shifts,
        gate_filter=gate_filter,
        q=request.args.get('q', '').strip(),
        view_mode=view_mode,
        by_user_day=by_user_day,
        by_shift_day=by_shift_day,
        total_expected_pay=total_expected_pay,
        today=date.today().isoformat(),
    )


@app.route('/employees/schedule/export')
@login_required
@admin_required
def employee_schedule_export():
    import csv, io
    from flask import Response
    week_str = request.args.get('week', '').strip()
    gate_filter = request.args.get('gate', '').strip()
    monday, days, _, _, week_label = _week_window(week_str)
    sched_rows = database.get_employee_schedules(days[0]['iso'], days[-1]['iso'], gate_name=gate_filter)
    buf = io.StringIO()
    buf.write('\ufeff')
    w = csv.writer(buf)
    w.writerow([f'LỊCH LÀM VIỆC - {week_label}'])
    w.writerow(['Ngày', 'Mã NV', 'Nhân viên', 'Ca làm việc', 'Cổng làm việc', 'Ghi chú'])
    for s in sched_rows:
        w.writerow([s['work_date'], s.get('employee_code') or '', s.get('fullname') or '', s['shift_name'], s['gate_name'], s.get('note') or ''])
    return Response(
        buf.getvalue().encode('utf-8'),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="lich_lam_viec_{monday.isoformat()}.csv"'},
    )


@app.route('/employees/schedule/<int:schedule_id>/delete', methods=['POST'])
@login_required
@admin_required
def employee_schedule_delete(schedule_id):
    database.delete_employee_schedule(schedule_id)
    flash('Đã xóa lịch ca làm việc.', 'success')
    return redirect(url_for('employee_schedule', week=request.form.get('week', ''), gate=request.form.get('gate', ''), q=request.form.get('q', '')))


@app.route('/employees/timesheet', methods=['GET', 'POST'])
@login_required
@admin_required
def employee_timesheet():
    if request.method == 'POST':
        att_id = _to_int(request.form.get('att_id'))
        uid = _to_int(request.form.get('user_id'))
        view_mode = request.form.get('view_mode', 'shift').strip()
        if view_mode not in ('shift', 'employee'):
            view_mode = 'shift'
        target = database.get_user_by_id(uid) if uid else None
        if target is None or target['role'] not in ('admin', 'manager'):
            flash('Vui lòng chọn nhân viên hợp lệ.', 'error')
        else:
            work_date = request.form.get('work_date', '').strip() or date.today().isoformat()
            shift_name = request.form.get('shift_name', 'Ca sáng').strip()[:60] or 'Ca sáng'
            zone_name = request.form.get('zone_name', 'Cổng chính').strip()[:80] or 'Cổng chính'
            work_mode = request.form.get('work_mode', '').strip()
            status = request.form.get('status', 'completed')
            if work_mode in ('leave_paid', 'leave_unpaid'):
                status = 'leave'
            elif status not in ('completed', 'late', 'leave', 'working', 'missing'):
                status = 'completed'
            note = request.form.get('note', '').strip()[:255]
            in_enabled = request.form.get('check_in_enabled')
            out_enabled = request.form.get('check_out_enabled')
            ci_t = request.form.get('check_in_time', '').strip() if (in_enabled is None or in_enabled == '1') else ''
            co_t = request.form.get('check_out_time', '').strip() if (out_enabled is None or out_enabled == '1') else ''
            if status != 'leave' and ((ci_t and not co_t) or (co_t and not ci_t)):
                status = 'missing'
            emp_set = get_employee_settings()
            if status == 'completed' and emp_set.get('emp_late_enabled') == '1' and ci_t:
                matched_sh = next((s for s in get_employee_shifts() if s['name'] == shift_name), None)
                if matched_sh and matched_sh['start'] < matched_sh['end']:
                    try:
                        sh_h, sh_m = [int(x) for x in matched_sh['start'].split(':')[:2]]
                        ci_h, ci_m = [int(x) for x in ci_t.split(':')[:2]]
                        grace = _to_int(emp_set.get('emp_late_grace_minutes'), 0) or 0
                        if (ci_h * 60 + ci_m) > (sh_h * 60 + sh_m + grace):
                            status = 'late'
                    except Exception:
                        pass
            ci = f"{work_date}T{ci_t}:00" if ci_t else ''
            co = f"{work_date}T{co_t}:00" if co_t else ''
            if att_id:
                database.update_employee_attendance(att_id, shift_name, zone_name, ci, co, status, note)
                flash(f'Đã cập nhật chấm công cho {target["fullname"]}.', 'success')
            else:
                database.add_manual_attendance(uid, work_date, shift_name, status, ci, co, zone_name, note)
                flash(f'Đã chấm công cho {target["fullname"]}.', 'success')
        return redirect(url_for(
            'employee_timesheet',
            week=request.form.get('week', ''),
            gate=request.form.get('filter_gate', ''),
            q=request.form.get('filter_q', ''),
            view=view_mode,
        ))

    week_str = request.args.get('week', '').strip()
    gate_filter = request.args.get('gate', '').strip()
    q = request.args.get('q', '').strip().lower()
    view_mode = request.args.get('view', 'shift').strip()
    if view_mode not in ('shift', 'employee'):
        view_mode = 'shift'
    monday, days, prev_week, next_week, week_label = _week_window(week_str)
    gate_choices = _employee_gate_choices()

    staff_rows = [parking_employees.enrich_employee(u) for u in database.get_staff_users() if u['status'] == 'active']
    if gate_filter:
        gf_l = gate_filter.lower()
        staff_rows = [e for e in staff_rows if any(b.lower() == gf_l for b in e.get('work_branches_list', []))]
    if q:
        staff_rows = [e for e in staff_rows if q in (e['fullname'] + ' ' + e['code'] + ' ' + e['username']).lower()]
    allowed_uids = {e['id'] for e in staff_rows}

    att_rows = [parking_employees._format_attendance_row(r) for r in database.get_employee_attendance(limit=1000)]
    start_iso, end_iso = days[0]['iso'], days[-1]['iso']
    today_iso = date.today().isoformat()
    by_user_day = {}
    by_shift_day = {}
    recorded_keys = set()
    for a in att_rows:
        wd = a.get('work_date') or ''
        if start_iso <= wd <= end_iso:
            if gate_filter and (a.get('zone_name') or '').strip().lower() != gate_filter.lower():
                continue
            if a['user_id'] not in allowed_uids:
                continue
            st = a.get('status') or 'completed'
            if st == 'missing':
                a['status_label'] = 'Chấm công thiếu'
            a['is_scheduled_only'] = False
            by_user_day.setdefault((a['user_id'], wd), []).append(a)
            by_shift_day.setdefault((a.get('shift_name') or 'Ca sáng', wd), []).append(a)
            recorded_keys.add((a['user_id'], wd, a.get('shift_name') or ''))

    # Merge scheduled shifts that do not yet have an attendance record
    sched_rows = database.get_employee_schedules(start_iso, end_iso, gate_name=gate_filter)
    for s in sched_rows:
        if s['user_id'] not in allowed_uids:
            continue
        key = (s['user_id'], s['work_date'], s['shift_name'])
        if key in recorded_keys:
            continue
        is_future = s['work_date'] > today_iso
        st = 'future' if is_future else 'unpunched'
        item = {
            'id': '',
            'schedule_id': s['id'],
            'user_id': s['user_id'],
            'fullname': s.get('fullname') or '',
            'employee_code': s.get('employee_code') or f"NV{s['user_id']:04d}",
            'work_date': s['work_date'],
            'shift_name': s['shift_name'],
            'zone_name': s.get('gate_name') or 'Cổng chính',
            'check_in_label': '--',
            'check_out_label': '--',
            'check_in_time': '',
            'check_out_time': '',
            'status': st,
            'status_label': 'Chưa đến giờ' if is_future else 'Chưa chấm công',
            'note': s.get('note') or '',
            'is_scheduled_only': True,
        }
        by_user_day.setdefault((s['user_id'], s['work_date']), []).append(item)
        by_shift_day.setdefault((s['shift_name'], s['work_date']), []).append(item)

    active_shifts = [s for s in get_employee_shifts() if s['active']]
    shift_has_items = {
        sh['name']: any(by_shift_day.get((sh['name'], d['iso'])) for d in days)
        for sh in active_shifts
    }

    return render_template(
        'employee_timesheet.html',
        active_page='employee_timesheet',
        employees=staff_rows,
        days=days,
        week=monday.isoformat(),
        prev_week=prev_week,
        next_week=next_week,
        week_label=week_label,
        gate_choices=gate_choices,
        employee_shifts=active_shifts,
        gate_filter=gate_filter,
        q=request.args.get('q', '').strip(),
        view_mode=view_mode,
        by_user_day=by_user_day,
        by_shift_day=by_shift_day,
        shift_has_items=shift_has_items,
        today=today_iso,
    )


@app.route('/employees/timesheet/<int:att_id>/delete', methods=['POST'])
@login_required
@admin_required
def employee_timesheet_delete(att_id):
    database.delete_employee_attendance(att_id)
    flash('Đã xóa bản ghi chấm công.', 'success')
    return redirect(url_for(
        'employee_timesheet',
        week=request.form.get('week', ''),
        gate=request.form.get('gate', ''),
        q=request.form.get('q', ''),
        view=request.form.get('view_mode', 'shift'),
    ))


def _format_work_period_range(work_period: str) -> str:
    import calendar
    wp = (work_period or '').strip()
    if len(wp) == 7 and wp[4] == '-':
        try:
            y, m = int(wp[:4]), int(wp[5:7])
            last_day = calendar.monthrange(y, m)[1]
            return f"01/{m:02d}/{y} - {last_day:02d}/{m:02d}/{y}"
        except Exception:
            pass
    return wp


@app.route('/employees/payroll', methods=['GET', 'POST'])
@login_required
@admin_required
def employee_payroll():
    if request.method == 'POST':
        pay_cycle = request.form.get('pay_cycle', 'Hàng tháng').strip()[:60] or 'Hàng tháng'
        work_period = request.form.get('work_period', '').strip() or date.today().strftime('%Y-%m')
        pay_branch = request.form.get('pay_branch', 'Cổng chính').strip()[:120] or 'Cổng chính'
        name = request.form.get('name', '').strip()[:160] or f"Bảng lương tháng {work_period[5:7]}/{work_period[:4]}"
        note = request.form.get('note', '').strip()[:255]
        scope = request.form.get('scope', 'all').strip()
        selected_uids = {_to_int(x) for x in request.form.getlist('selected_user_ids') if _to_int(x)}

        staff_users = [u for u in database.get_staff_users() if u['status'] == 'active']
        emps = [parking_employees.enrich_employee(u) for u in staff_users]
        if scope == 'custom' and selected_uids:
            emps = [e for e in emps if e['id'] in selected_uids]
        elif pay_branch and pay_branch.lower() not in ('tất cả các cổng', 'tat ca cac cong'):
            pb_l = pay_branch.lower()
            emps = [e for e in emps if any(b.lower() == pb_l for b in e.get('work_branches_list', []))]
        parking_employees.attach_attendance(emps, database.get_employee_attendance(limit=1000), month=work_period)
        totals = parking_employees.payroll_totals(emps)

        _, code = database.create_employee_paysheet(
            name=name,
            pay_cycle=pay_cycle,
            work_period=work_period,
            pay_branch=pay_branch,
            total_salary=totals['net_salary'],
            status='provisional',
            note=note,
            created_by=session.get('fullname') or session.get('username') or 'Admin',
        )
        flash(f'Đã tạo bảng tính lương {code} ({name}).', 'success')
        return redirect(url_for('employee_payroll'))

    q = request.args.get('q', '').strip()
    pay_branch = request.args.get('pay_branch', '').strip()
    pay_cycle_filter = request.args.get('pay_cycle', '').strip()
    statuses = request.args.getlist('status') or ['draft', 'provisional', 'finalized']
    paysheets = database.get_employee_paysheets(status_list=statuses, pay_branch=pay_branch, q=q)
    if pay_cycle_filter:
        paysheets = [p for p in paysheets if (p.get('pay_cycle') or '') == pay_cycle_filter]

    for p in paysheets:
        p['work_period_range'] = _format_work_period_range(p.get('work_period') or '')

    gate_choices = _employee_gate_choices()
    active_staff = [parking_employees.enrich_employee(u) for u in database.get_staff_users() if u['status'] == 'active']
    parking_employees.attach_attendance(active_staff, database.get_employee_attendance(limit=1000), month=date.today().strftime('%Y-%m'))

    totals = {
        'total_salary': sum(int(p.get('total_salary') or 0) for p in paysheets if p.get('status') != 'cancelled'),
        'paid_amount': sum(int(p.get('paid_amount') or 0) for p in paysheets if p.get('status') != 'cancelled'),
    }
    totals['remaining'] = max(0, totals['total_salary'] - totals['paid_amount'])

    return render_template(
        'employee_payroll.html',
        active_page='employee_payroll',
        paysheets=paysheets,
        totals=totals,
        gate_choices=gate_choices,
        pay_branch=pay_branch,
        pay_cycle_filter=pay_cycle_filter,
        statuses=statuses,
        q=q,
        staff_list=active_staff,
        current_month=date.today().strftime('%Y-%m'),
    )


@app.route('/employees/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def employee_settings():
    import json
    if request.method == 'POST':
        action = request.form.get('emp_action', 'save_settings')
        if action == 'quick_add_employees':
            import re
            import unicodedata
            fullnames = request.form.getlist('emp_fullname')
            phones = request.form.getlist('emp_phone')
            pay_branches = request.form.getlist('emp_pay_branch')
            work_branches = request.form.getlist('emp_work_branch')
            created = 0
            for idx, raw_name in enumerate(fullnames):
                fullname = (raw_name or '').strip()[:160]
                if not fullname:
                    continue
                phone = (phones[idx] if idx < len(phones) else '').strip()[:32]
                pay_branch = (pay_branches[idx] if idx < len(pay_branches) else '').strip()[:120] or 'Cổng chính'
                raw_wb = (work_branches[idx] if idx < len(work_branches) else '').strip()[:240]
                work_branch = raw_wb or 'Cổng chính'

                norm = unicodedata.normalize('NFKD', fullname.replace('Đ', 'D').replace('đ', 'd'))
                slug = re.sub(r'[^a-z0-9]+', '', norm.encode('ascii', 'ignore').decode('ascii').lower())[:16] or 'nv'
                cand = slug
                suffix = 1
                while database.username_exists(cand):
                    suffix += 1
                    cand = f"{slug}{suffix}"
                new_id = database.add_user(cand, fullname, '123456', 'manager')
                database.update_employee_profile(
                    new_id,
                    fullname=fullname,
                    role='manager',
                    phone=phone,
                    pay_branch=pay_branch,
                    work_branch=work_branch,
                )
                created += 1
            if created:
                flash(f'Đã thêm nhanh {created} nhân viên (mật khẩu mặc định: 123456).', 'success')
            else:
                flash('Vui lòng nhập ít nhất một tên nhân viên.', 'error')
            return redirect(url_for('employee_settings', tab='init'))

        if action == 'save_shift':
            shifts = get_employee_shifts()
            sid = _to_int(request.form.get('shift_id'))
            name = request.form.get('shift_name', '').strip()[:80]
            start_t = request.form.get('shift_start', '06:00').strip()[:10] or '06:00'
            end_t = request.form.get('shift_end', '14:00').strip()[:10] or '14:00'
            ci_start = request.form.get('checkin_start', start_t).strip()[:10] or start_t
            ci_end = request.form.get('checkin_end', end_t).strip()[:10] or end_t
            gates = [g.strip() for g in request.form.getlist('shift_gates') if g.strip()] or ['Cổng chính']
            if not name:
                flash('Vui lòng nhập tên ca làm việc.', 'error')
                return redirect(url_for('employee_settings', tab='attendance', view='shifts'))
            if sid:
                for s in shifts:
                    if s['id'] == sid:
                        s.update({'name': name, 'start': start_t, 'end': end_t, 'checkin_start': ci_start, 'checkin_end': ci_end, 'gates': gates})
                flash(f'Đã cập nhật ca "{name}".', 'success')
            else:
                next_id = max([s['id'] for s in shifts] or [0]) + 1
                shifts.append({'id': next_id, 'name': name, 'start': start_t, 'end': end_t, 'checkin_start': ci_start, 'checkin_end': ci_end, 'gates': gates, 'active': True})
                flash(f'Đã thêm ca "{name}".', 'success')
            clean_shifts = [{k: s[k] for k in ('id', 'name', 'start', 'end', 'checkin_start', 'checkin_end', 'gates', 'active')} for s in shifts]
            database.set_setting('emp_shifts_json', json.dumps(clean_shifts, ensure_ascii=False))
            return redirect(url_for('employee_settings', tab='attendance', view='shifts'))

        if action == 'toggle_shift':
            sid = _to_int(request.form.get('shift_id'))
            shifts = get_employee_shifts()
            for s in shifts:
                if s['id'] == sid:
                    s['active'] = not s['active']
            clean_shifts = [{k: s[k] for k in ('id', 'name', 'start', 'end', 'checkin_start', 'checkin_end', 'gates', 'active')} for s in shifts]
            database.set_setting('emp_shifts_json', json.dumps(clean_shifts, ensure_ascii=False))
            return redirect(url_for('employee_settings', tab='attendance', view='shifts'))

        if action == 'delete_shift':
            sid = _to_int(request.form.get('shift_id'))
            shifts = [s for s in get_employee_shifts() if s['id'] != sid]
            clean_shifts = [{k: s[k] for k in ('id', 'name', 'start', 'end', 'checkin_start', 'checkin_end', 'gates', 'active')} for s in shifts]
            database.set_setting('emp_shifts_json', json.dumps(clean_shifts, ensure_ascii=False))
            flash('Đã xóa ca làm việc.', 'success')
            return redirect(url_for('employee_settings', tab='attendance', view='shifts'))

        if action == 'save_salary_template':
            items = get_employee_salary_templates()
            tid = _to_int(request.form.get('tpl_id'))
            name = request.form.get('tpl_name', '').strip()[:120]
            note = request.form.get('tpl_note', '').strip()[:255]
            stype = request.form.get('tpl_salary_type', 'shift')
            if stype not in dict(parking_employees.SALARY_TYPES):
                stype = 'shift'
            samount = max(0, _to_int(request.form.get('tpl_salary_amount'), 0) or 0)
            b_en = request.form.get('tpl_bonus_enabled') == '1'
            b_type = request.form.get('tpl_bonus_type', 'Theo doanh thu').strip()[:120]
            b_amt = max(0, _to_int(request.form.get('tpl_bonus_amount'), 0) or 0)
            c_en = request.form.get('tpl_commission_enabled') == '1'
            c_type = request.form.get('tpl_commission_type', 'Theo dịch vụ').strip()[:120]
            try:
                c_rate = max(0.0, min(100.0, float(request.form.get('tpl_commission_rate') or 0)))
            except (TypeError, ValueError):
                c_rate = 0.0
            a_en = request.form.get('tpl_allowance_enabled') == '1'
            raw_allowances = request.form.get('tpl_allowances_json', '').strip()
            allowances_list = []
            if raw_allowances:
                try:
                    parsed_a = json.loads(raw_allowances)
                    if isinstance(parsed_a, list):
                        for row in parsed_a:
                            if not isinstance(row, dict):
                                continue
                            r_name = str(row.get('name') or '').strip()[:120]
                            r_type = str(row.get('type') or 'Phụ cấp cố định theo ngày').strip()[:120]
                            r_amt = max(0, _to_int(row.get('amount'), 0) or 0)
                            if r_name or r_amt > 0:
                                allowances_list.append({'name': r_name or 'Phụ cấp', 'type': r_type, 'amount': r_amt})
                except Exception:
                    allowances_list = []
            if allowances_list:
                a_amt = sum(r['amount'] for r in allowances_list)
            else:
                a_amt = max(0, _to_int(request.form.get('tpl_allowance_amount'), 0) or 0)
                if a_en and a_amt > 0:
                    allowances_list = [{'name': 'Phụ cấp', 'type': 'Phụ cấp cố định hàng tháng', 'amount': a_amt}]

            d_en = request.form.get('tpl_deduction_enabled') == '1'
            raw_deductions = request.form.get('tpl_deductions_json', '').strip()
            deductions_list = []
            if raw_deductions:
                try:
                    parsed_d = json.loads(raw_deductions)
                    if isinstance(parsed_d, list):
                        for row in parsed_d:
                            if not isinstance(row, dict):
                                continue
                            r_name = str(row.get('name') or '').strip()[:120]
                            r_type = str(row.get('type') or 'Đi muộn').strip()[:120]
                            r_rule = str(row.get('rule') or 'Theo block 30 phút').strip()[:120]
                            r_amt = max(0, _to_int(row.get('amount'), 0) or 0)
                            if r_name or r_amt > 0:
                                deductions_list.append({'name': r_name or 'Giảm trừ', 'type': r_type, 'rule': r_rule, 'amount': r_amt})
                except Exception:
                    deductions_list = []
            if deductions_list:
                d_amt = sum(r['amount'] for r in deductions_list)
            else:
                d_amt = max(0, _to_int(request.form.get('tpl_deduction_amount'), 0) or 0)
                if d_en and d_amt > 0:
                    deductions_list = [{'name': 'Đi muộn', 'type': 'Đi muộn', 'rule': 'Theo block 30 phút', 'amount': d_amt}]
            d_note = request.form.get('tpl_deduction_note', '').strip()[:160]
            if not name:
                flash('Vui lòng nhập tên mẫu lương.', 'error')
                return redirect(url_for('employee_settings', tab='payroll', view='templates'))
            payload = {
                'name': name, 'note': note, 'salary_type': stype, 'salary_amount': samount,
                'bonus_enabled': b_en, 'bonus_type': b_type, 'bonus_amount': b_amt,
                'commission_enabled': c_en, 'commission_type': c_type, 'commission_rate': c_rate,
                'allowance_enabled': a_en, 'allowance_amount': a_amt, 'allowances': allowances_list,
                'deduction_enabled': d_en, 'deduction_amount': d_amt, 'deduction_note': d_note, 'deductions': deductions_list,
            }
            if tid:
                for it in items:
                    if int(it.get('id') or 0) == tid:
                        it.update(payload)
                flash(f'Đã cập nhật mẫu lương "{name}".', 'success')
            else:
                next_id = max([int(it.get('id') or 0) for it in items] or [0]) + 1
                items.append(dict(payload, id=next_id))
                flash(f'Đã thêm mẫu lương "{name}".', 'success')
            database.set_setting('emp_salary_templates_json', json.dumps(items, ensure_ascii=False))
            return redirect(url_for('employee_settings', tab='payroll', view='templates'))

        if action == 'delete_salary_template':
            tid = _to_int(request.form.get('tpl_id'))
            items = [it for it in get_employee_salary_templates() if int(it.get('id') or 0) != tid]
            database.set_setting('emp_salary_templates_json', json.dumps(items, ensure_ascii=False))
            flash('Đã xóa mẫu lương.', 'success')
            return redirect(url_for('employee_settings', tab='payroll', view='templates'))

        if action == 'apply_salary_template':
            tpl_name = request.form.get('tpl_name', '').strip()
            selected_ids = {_to_int(x) for x in request.form.getlist('user_ids') if _to_int(x)}
            tpl = next((t for t in get_employee_salary_templates() if t.get('name') == tpl_name), None)
            if tpl:
                for u in database.get_staff_users():
                    uid = u['id']
                    if uid in selected_ids:
                        database.update_employee_profile(
                            uid,
                            salary_template=tpl_name,
                            salary_type=tpl.get('salary_type', 'shift'),
                            salary_amount=int(tpl.get('salary_amount') or 0),
                            allowance_enabled=1 if tpl.get('allowance_enabled') else 0,
                            allowance_amount=int(tpl.get('allowance_amount') or 0),
                            deduction_enabled=1 if tpl.get('deduction_enabled') else 0,
                            deduction_amount=int(tpl.get('deduction_amount') or 0),
                        )
                    elif (u['salary_template'] if 'salary_template' in u.keys() else '') == tpl_name:
                        database.update_employee_profile(uid, salary_template='')
                flash(f'Đã áp dụng mẫu lương "{tpl_name}" cho {len(selected_ids)} nhân viên.', 'success')
            return redirect(url_for('employee_settings', tab='payroll', view='templates'))

        if action == 'save_allowance':
            items = get_employee_allowances()
            aid = _to_int(request.form.get('item_id'))
            name = request.form.get('item_name', '').strip()[:120]
            atype = request.form.get('item_type', 'Phụ cấp cố định theo ngày').strip()[:120]
            amount = max(0, _to_int(request.form.get('item_amount'), 0) or 0)
            benefit_type = request.form.get('item_benefit_type', 'vnd').strip()
            if benefit_type not in ('vnd', 'percent'):
                benefit_type = 'vnd'
            min_h_en = request.form.get('item_min_hours_enabled') == '1'
            try:
                min_h = max(0.0, min(24.0, float(request.form.get('item_min_hours') or 0)))
            except (TypeError, ValueError):
                min_h = 0.0
            shift_allowances = []
            raw_sa = request.form.get('item_shift_allowances_json', '').strip()
            if atype == 'Phụ cấp theo ca làm việc' and raw_sa:
                try:
                    parsed_sa = json.loads(raw_sa)
                    if isinstance(parsed_sa, list):
                        for row in parsed_sa:
                            if not isinstance(row, dict):
                                continue
                            sname = str(row.get('shift_name') or '').strip()[:120]
                            samt = max(0, _to_int(row.get('amount'), 0) or 0)
                            if sname:
                                shift_allowances.append({'shift_name': sname, 'amount': samt})
                except Exception:
                    shift_allowances = []
                if shift_allowances and not amount:
                    amount = sum(r['amount'] for r in shift_allowances)
            if not name:
                flash('Vui lòng nhập tên phụ cấp.', 'error')
                return redirect(url_for('employee_settings', tab='payroll', view='allowances'))
            payload_a = {
                'name': name,
                'type': atype,
                'amount': amount,
                'benefit_type': benefit_type if atype in ('Phụ cấp hàng tháng cố định', 'Phụ cấp cố định hàng tháng', 'Phụ cấp hàng tháng tính trên số ngày công chuẩn') else 'vnd',
                'min_hours_enabled': min_h_en if atype == 'Phụ cấp cố định theo ngày' else False,
                'min_hours': min_h if (min_h_en and atype == 'Phụ cấp cố định theo ngày') else 0,
                'shift_allowances': shift_allowances if atype == 'Phụ cấp theo ca làm việc' else [],
            }
            if aid:
                for it in items:
                    if int(it.get('id') or 0) == aid:
                        it.update(payload_a)
                flash(f'Đã cập nhật phụ cấp "{name}".', 'success')
            else:
                next_id = max([int(it.get('id') or 0) for it in items] or [0]) + 1
                items.append(dict(payload_a, id=next_id))
                flash(f'Đã thêm phụ cấp "{name}".', 'success')
            database.set_setting('emp_allowances_json', json.dumps(items, ensure_ascii=False))
            return redirect(url_for('employee_settings', tab='payroll', view='allowances'))

        if action == 'delete_allowance':
            aid = _to_int(request.form.get('item_id'))
            items = [it for it in get_employee_allowances() if int(it.get('id') or 0) != aid]
            database.set_setting('emp_allowances_json', json.dumps(items, ensure_ascii=False))
            flash('Đã xóa phụ cấp.', 'success')
            return redirect(url_for('employee_settings', tab='payroll', view='allowances'))

        if action == 'save_deduction':
            items = get_employee_deductions()
            did = _to_int(request.form.get('item_id'))
            name = request.form.get('item_name', '').strip()[:120]
            dtype = request.form.get('item_type', 'Đi muộn').strip()[:120]
            cond = request.form.get('item_condition', 'count').strip()
            if cond not in ('count', 'salary_coef'):
                cond = 'count'
            amount = max(0, _to_int(request.form.get('item_amount'), 0) or 0)
            if not name:
                flash('Vui lòng nhập tên giảm trừ.', 'error')
                return redirect(url_for('employee_settings', tab='payroll', view='deductions'))
            payload_d = {
                'name': name,
                'type': dtype,
                'condition': cond,
                'amount': amount,
            }
            if did:
                for it in items:
                    if int(it.get('id') or 0) == did:
                        it.update(payload_d)
                flash(f'Đã cập nhật giảm trừ "{name}".', 'success')
            else:
                next_id = max([int(it.get('id') or 0) for it in items] or [0]) + 1
                items.append(dict(payload_d, id=next_id))
                flash(f'Đã thêm giảm trừ "{name}".', 'success')
            database.set_setting('emp_deductions_json', json.dumps(items, ensure_ascii=False))
            return redirect(url_for('employee_settings', tab='payroll', view='deductions'))

        if action == 'delete_deduction':
            did = _to_int(request.form.get('item_id'))
            items = [it for it in get_employee_deductions() if int(it.get('id') or 0) != did]
            database.set_setting('emp_deductions_json', json.dumps(items, ensure_ascii=False))
            flash('Đã xóa giảm trừ.', 'success')
            return redirect(url_for('employee_settings', tab='payroll', view='deductions'))

        if action == 'quick_save_attendance_mode':
            mode = request.form.get('emp_attendance_mode', 'shift')
            if mode not in ('shift', 'flex'):
                mode = 'shift'
            database.set_setting('emp_attendance_mode', mode)
            label = 'Chấm công theo ca làm việc' if mode == 'shift' else 'Chấm công theo khung giờ làm việc'
            flash(f'Đã chọn chế độ: {label}.', 'success')
            return redirect(url_for('employee_settings', tab='init'))

        if action == 'quick_save_checkin_methods':
            sw = '1' if request.form.get('emp_checkin_software') == '1' else '0'
            ph = '1' if request.form.get('emp_checkin_photo') == '1' else '0'
            database.set_setting('emp_checkin_software', sw)
            database.set_setting('emp_checkin_photo', ph)
            flash('Đã cập nhật hình thức chấm công.', 'success')
            return redirect(url_for('employee_settings', tab='init'))

        if action == 'quick_save_salary':
            uid = _to_int(request.form.get('user_id'))
            target = database.get_user_by_id(uid) if uid else None
            if target is None or target['role'] not in ('admin', 'manager'):
                flash('Nhân viên không hợp lệ.', 'error')
            else:
                stype = request.form.get('salary_type', '')
                if stype not in dict(parking_employees.SALARY_TYPES):
                    stype = ''
                samount = max(0, _to_int(request.form.get('salary_amount'), 0) or 0)
                a_en = 1 if request.form.get('allowance_enabled') == '1' else 0
                a_amt = max(0, _to_int(request.form.get('allowance_amount'), 0) or 0)
                d_en = 1 if request.form.get('deduction_enabled') == '1' else 0
                d_amt = max(0, _to_int(request.form.get('deduction_amount'), 0) or 0)
                d_note = request.form.get('deduction_note', '').strip()[:255]
                database.update_employee_profile(
                    uid,
                    salary_type=stype,
                    salary_amount=samount,
                    allowance_enabled=a_en,
                    allowance_amount=a_amt,
                    deduction_enabled=d_en,
                    deduction_amount=d_amt,
                    deduction_note=d_note,
                )
                flash(f'Đã cập nhật thiết lập lương cho {target["fullname"]}.', 'success')
            return redirect(url_for('employee_settings', tab='init', open_salary='1'))

        if action == 'save_work_days':
            gate_name = request.form.get('gate_name', '').strip()
            days = [d for d in request.form.getlist('work_days') if d in ('T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN')]
            try:
                wd_map = json.loads(database.get_setting('emp_work_days_json', '{}') or '{}')
            except Exception:
                wd_map = {}
            if gate_name:
                wd_map[gate_name] = days
                database.set_setting('emp_work_days_json', json.dumps(wd_map, ensure_ascii=False))
                flash(f'Đã cập nhật ngày làm việc cho {gate_name}.', 'success')
            return redirect(url_for('employee_settings', tab='schedule_rules'))

        if action == 'add_holiday':
            hid = _to_int(request.form.get('holiday_id'))
            name = request.form.get('holiday_name', '').strip()[:120]
            start_d = request.form.get('start_date', '').strip() or date.today().isoformat()
            end_d = request.form.get('end_date', '').strip() or start_d
            bonus_present = request.form.get('holiday_bonus_present') == '1'
            bonus_enabled = (request.form.get('holiday_bonus_enabled') == '1') if bonus_present else True
            bonus = max(0, _to_int(request.form.get('holiday_bonus'), 0) or 0) if bonus_enabled else 0
            try:
                days_cnt = max(1, (date.fromisoformat(end_d) - date.fromisoformat(start_d)).days + 1)
            except ValueError:
                days_cnt = 1
            try:
                holidays = json.loads(database.get_setting('emp_holidays_json', '[]') or '[]')
            except Exception:
                holidays = []
            if name:
                payload_h = {
                    'name': name,
                    'start_date': start_d,
                    'end_date': end_d,
                    'days': days_cnt,
                    'bonus_enabled': bonus_enabled,
                    'bonus': bonus,
                }
                if hid:
                    for h in holidays:
                        if int(h.get('id') or 0) == hid:
                            h.update(payload_h)
                    flash(f'Đã cập nhật kỳ nghỉ lễ "{name}".', 'success')
                else:
                    next_id = max([int(h.get('id') or 0) for h in holidays] or [0]) + 1
                    holidays.append(dict(payload_h, id=next_id))
                    flash(f'Đã thêm kỳ nghỉ lễ "{name}".', 'success')
                database.set_setting('emp_holidays_json', json.dumps(holidays, ensure_ascii=False))
            else:
                flash('Vui lòng nhập tên kỳ lễ tết.', 'error')
            return redirect(url_for('employee_settings', tab='schedule_rules'))

        if action == 'delete_holiday':
            hid = _to_int(request.form.get('holiday_id'))
            try:
                holidays = json.loads(database.get_setting('emp_holidays_json', '[]') or '[]')
            except Exception:
                holidays = []
            holidays = [h for h in holidays if int(h.get('id') or 0) != hid]
            database.set_setting('emp_holidays_json', json.dumps(holidays, ensure_ascii=False))
            flash('Đã xóa kỳ nghỉ lễ.', 'success')
            return redirect(url_for('employee_settings', tab='schedule_rules'))

        bool_keys = {
            'emp_auto_checkin', 'emp_unscheduled_checkin', 'emp_unscheduled_auto_approve', 'emp_multi_shift_single_punch',
            'emp_overtime_enabled', 'emp_auto_create_paysheet', 'emp_auto_update_paysheet',
            'emp_break_enabled', 'emp_convert_hours_enabled', 'emp_late_enabled', 'emp_early_leave_enabled',
            'emp_ot_before_enabled', 'emp_ot_after_enabled', 'emp_ot_actual_all',
        }
        int_keys = {'emp_late_grace_minutes', 'emp_early_leave_grace_minutes', 'emp_overtime_before_minutes', 'emp_overtime_after_minutes', 'emp_standard_hours'}
        skip_keys = {
            'emp_work_days_json', 'emp_holidays_json', 'emp_shifts_json',
            'emp_salary_templates_json', 'emp_allowances_json', 'emp_deductions_json',
            'emp_checkin_software', 'emp_checkin_photo',
        }
        for key, default in EMPLOYEE_SETTING_DEFAULTS.items():
            if key in skip_keys:
                continue
            if key in bool_keys:
                val = '1' if request.form.get(key) == '1' else '0'
            elif key in int_keys:
                upper = 24 if key == 'emp_standard_hours' else 120
                val = str(max(0, min(upper, _to_int(request.form.get(key), int(default)) or 0)))
            else:
                val = request.form.get(key, default).strip()[:60] or default
            database.set_setting(key, val)
        flash('Đã lưu thiết lập nhân viên.', 'success')
        return redirect(url_for('employee_settings', tab=request.form.get('active_tab', 'attendance')))

    emp_set = get_employee_settings()
    staff_users = [dict(u) for u in database.get_staff_users()]
    try:
        wd_map = json.loads(emp_set.get('emp_work_days_json') or '{}')
    except Exception:
        wd_map = {}
    try:
        holidays = json.loads(emp_set.get('emp_holidays_json') or '[]')
    except Exception:
        holidays = []

    default_days = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']
    gate_work_days = []
    for gname in _employee_gate_choices():
        days_list = wd_map.get(gname, default_days)
        gate_work_days.append({
            'name': gname,
            'days_list': days_list,
            'days_csv': ','.join(days_list),
            'days_label': ', '.join(days_list) if days_list else 'Chưa chọn ngày',
            'active': len(days_list) > 0,
        })

    active_tab = request.args.get('tab', 'init')
    if active_tab not in ('init', 'attendance', 'payroll', 'schedule_rules'):
        active_tab = 'init'

    tpl_usage_counts = {}
    for u in staff_users:
        tname = (u.get('salary_template') or '').strip()
        if tname:
            tpl_usage_counts[tname] = tpl_usage_counts.get(tname, 0) + 1

    return render_template(
        'employee_settings.html',
        employee_settings=emp_set,
        emp_total_count=len(staff_users),
        emp_salary_configured_count=sum(1 for u in staff_users if u.get('salary_type') or u.get('salary_amount')),
        enriched_staff=[parking_employees.enrich_employee(u) for u in staff_users],
        salary_types=parking_employees.SALARY_TYPES,
        gate_work_days=gate_work_days,
        holidays=holidays,
        shifts=get_employee_shifts(),
        salary_templates_data=get_employee_salary_templates(),
        tpl_usage_counts=tpl_usage_counts,
        allowances_catalog=get_employee_allowances(),
        deductions_catalog=get_employee_deductions(),
        att_view=request.args.get('view', ''),
        pay_view=request.args.get('view', ''),
        active_tab=active_tab,
        open_salary=(request.args.get('open_salary') == '1'),
        today=date.today().isoformat(),
    )


@app.route('/employees/payroll/<int:paysheet_id>/status', methods=['POST'])
@login_required
@admin_required
def employee_payroll_status(paysheet_id):
    new_status = request.form.get('status', '')
    if new_status not in ('draft', 'provisional', 'finalized', 'cancelled'):
        abort(400)
    paid_amount = request.form.get('paid_amount')
    paid_int = int(paid_amount) if (paid_amount is not None and paid_amount != '') else None
    database.update_employee_paysheet_status(paysheet_id, new_status, paid_amount=paid_int)
    flash('Đã cập nhật trạng thái bảng lương.', 'success')
    return redirect(url_for('employee_payroll'))


@app.route('/users')
@login_required
@staff_required
def users():
    if request.args.get('tab') == 'accounts' and session.get('role') == 'admin':
        return redirect(url_for('accounts'))
    return redirect(url_for('customers'))


@app.route('/customers/recognize-plate', methods=['POST'])
@app.route('/users/recognize-plate', methods=['POST'])
@login_required
@staff_required
def recognize_user_plate():
    """Nhận diện biển số từ ảnh tải lên (trả JSON) để điền vào ô biển số khi đăng ký xe."""
    file = request.files.get('image')
    if not file or not file.filename:
        return jsonify(error='Chưa chọn ảnh.'), 400
    ext = os.path.splitext(file.filename)[1].lower()
    ext = ext if ext in ALLOWED_EXT else '.jpg'
    path = os.path.join(TMP_FOLDER, f'reg_{uuid.uuid4().hex[:12]}{ext}')
    file.save(path)
    try:
        plate, _ = recognize_plate(path)
    except Exception as e:
        return jsonify(error=f'Lỗi khi nhận diện biển số: {e}'), 500
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    plate = clean_plate_input(plate)
    if len(plate_key(plate)) < 4:
        return jsonify(plate='', error='Không nhận diện được biển số rõ ràng, vui lòng nhập tay hoặc chọn ảnh khác.')
    return jsonify(plate=plate)


@app.route('/customers/add', methods=['POST'])
@login_required
@staff_required
def add_customer():
    username = request.form.get('username', '').strip()
    fullname = request.form.get('fullname', '').strip()
    password = request.form.get('password', '')

    vehicles, errors, prefill = parse_vehicle_forms(request.form)
    profile, profile_errors = parking_customers.parse_profile(request.form)
    errors.extend(profile_errors)

    if not username or not fullname or not password:
        errors.insert(0, 'Vui lòng nhập đầy đủ thông tin.')
    elif len(password) < MIN_PASSWORD_LEN:
        errors.insert(0, f'Mật khẩu tối thiểu {MIN_PASSWORD_LEN} ký tự.')
    elif database.username_exists(username):
        errors.insert(0, 'Tên đăng nhập đã tồn tại.')

    if errors:
        for e in errors:
            flash(e, 'error')
        return render_customers(open_modal=True,
                                form=dict(profile, username=username), form_errors=errors,
                                form_vehicles=prefill)

    new_id = database.add_user(username, fullname, password, 'user')
    database.update_customer_profile(new_id, **profile)
    save_vehicles(new_id, vehicles)
    extra = f' và đăng ký {len(vehicles)} xe' if vehicles else ''
    total = sum(v['paid_amount'] or 0 for v in vehicles)
    if total:
        extra += f' — tiền vé tháng cần thu: {vnd_filter(total)}'
    flash(f'Đã thêm khách hàng "{username}"{extra}.', 'success')
    return redirect(url_for('customers', open=new_id))


@app.route('/accounts/add', methods=['POST'])
@login_required
@admin_required
def add_account():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    emp_data = parking_employees.parse_employee_form(request.form)
    fullname = emp_data['fullname']
    role = emp_data['role']

    errors = []
    if not username or not fullname or not password:
        errors.append('Vui lòng nhập đầy đủ thông tin.')
    elif len(password) < MIN_PASSWORD_LEN:
        errors.append(f'Mật khẩu tối thiểu {MIN_PASSWORD_LEN} ký tự.')
    elif database.username_exists(username):
        errors.append('Tên đăng nhập đã tồn tại.')

    if errors:
        for e in errors:
            flash(e, 'error')
        return render_accounts(open_modal=True,
                               form=dict(emp_data, username=username),
                               form_errors=errors)

    new_id = database.add_user(username, fullname, password, role)
    database.update_employee_profile(new_id, **emp_data)
    role_name = 'Quản trị viên' if role == 'admin' else 'Nhân viên vận hành'
    flash(f'Đã tạo tài khoản {role_name} "{username}".', 'success')
    return redirect(url_for('accounts', open=new_id))


@app.route('/users/add', methods=['POST'])
@login_required
@staff_required
def add_user():
    role = request.form.get('role', 'user')
    if role in ('manager', 'admin') and session.get('role') == 'admin':
        return add_account()
    return add_customer()


@app.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@staff_required
def edit_user(user_id):
    target = database.get_user_by_id(user_id)
    if not can_manage_user(target):
        flash('Bạn không có quyền sửa tài khoản này.', 'error')
        return redirect(url_for('users'))

    if request.method == 'GET':
        return render_edit_user(target)

    fullname = request.form.get('fullname', '').strip()
    if not fullname:
        flash('Họ tên không được để trống.', 'error')
        return redirect(url_for('edit_user', user_id=user_id))

    role = target['role']
    # Chỉ admin được đổi vai trò (người dùng <-> nhân viên); không đổi vai trò của chính admin.
    if session.get('role') == 'admin' and target['role'] != 'admin':
        new_role = request.form.get('role', role)
        if new_role in ('user', 'manager'):
            role = new_role
    database.update_user(user_id, fullname, role)
    if user_id == session.get('user_id'):
        session['fullname'] = fullname
    flash('Đã cập nhật thông tin tài khoản.', 'success')
    return redirect(url_for('edit_user', user_id=user_id))


@app.route('/users/<int:user_id>/password', methods=['POST'])
@login_required
@admin_required
def change_user_password(user_id):
    target = database.get_user_by_id(user_id)
    if target is None:
        flash('Không tìm thấy tài khoản.', 'error')
        return redirect(url_for('users'))
    new_pw = request.form.get('new_password', '')
    confirm = request.form.get('confirm_password', '')
    if len(new_pw) < MIN_PASSWORD_LEN:
        flash(f'Mật khẩu mới tối thiểu {MIN_PASSWORD_LEN} ký tự.', 'error')
    elif new_pw != confirm:
        flash('Mật khẩu nhập lại không khớp.', 'error')
    else:
        database.set_user_password(user_id, new_pw)
        flash(f'Đã đổi mật khẩu cho tài khoản "{target["username"]}".', 'success')
    return redirect(url_for('edit_user', user_id=user_id))


@app.route('/users/<int:user_id>/vehicles/add', methods=['POST'])
@login_required
@staff_required
def add_user_vehicles(user_id):
    target = database.get_user_by_id(user_id)
    if not can_manage_user(target):
        flash('Bạn không có quyền sửa tài khoản này.', 'error')
        return redirect(url_for('users'))
    if target['role'] != 'user':
        flash('Chỉ tài khoản người dùng mới đăng ký xe và vé.', 'error')
        return redirect(url_for('edit_user', user_id=user_id))

    vehicles, errors, prefill = parse_vehicle_forms(request.form)
    if not vehicles and not errors:
        errors.append('Vui lòng nhập hoặc nhận diện biển số xe cần đăng ký.')
    if errors:
        for e in errors:
            flash(e, 'error')
        return render_edit_user(target, form_vehicles=prefill)
    save_vehicles(user_id, vehicles)
    total = sum(v['paid_amount'] or 0 for v in vehicles)
    money = f' — tiền vé tháng cần thu: {vnd_filter(total)}' if total else ''
    flash(f'Đã đăng ký {len(vehicles)} xe cho tài khoản "{target["username"]}"{money}.', 'success')
    return redirect(url_for('edit_user', user_id=user_id))


def renew_vehicle(vehicle, months):
    """Thuê thêm tháng: gia hạn vé tháng (nối tiếp ngày hết hạn nếu còn hạn) hoặc đổi vé lượt -> vé tháng
    (bắt đầu tính từ hôm nay). Tiền = giá tháng trong Bảng giá x số tháng; ghi vào nhật ký doanh thu.
    Trả về (thông báo lỗi hoặc None, {'start','expires','total'})."""
    if not months or not 1 <= months <= MAX_MONTHS:
        return f'Số tháng thuê phải từ 1 đến {MAX_MONTHS}.', None
    today = date.today()
    price = database.find_month_price(vehicle['vehicle_type_id'], today)
    if price is None:
        return 'Bảng giá chưa có giá vé tháng cho loại xe này.', None
    total = price['amount'] * months

    active = (vehicle['ticket_type'] == 'month' and vehicle['expires_on']
              and vehicle['expires_on'] >= today.isoformat())
    if active:   # còn hạn -> nối tiếp từ ngày hết hạn cũ
        new_start = date.fromisoformat(vehicle['expires_on']) + timedelta(days=1)
        start_on = vehicle['start_on'] or vehicle['created_at'][:10]
        all_months = (vehicle['months'] or 0) + months
        paid = (vehicle['paid_amount'] or 0) + total
    else:        # vé lượt hoặc đã hết hạn -> bắt đầu từ hôm nay
        new_start, start_on, all_months, paid = today, today.isoformat(), months, total
    expires_on = month_ticket_period(new_start, months).isoformat()
    database.set_vehicle_month_ticket(vehicle['id'], start_on, expires_on, all_months, paid)
    database.add_ticket_payment(vehicle['id'], vehicle['plate_number'], total, months)   # ghi vào doanh thu
    return None, {'start': new_start.isoformat(), 'expires': expires_on, 'total': total}


@app.route('/users/<int:user_id>/vehicles/<int:vehicle_id>/renew', methods=['POST'])
@login_required
@staff_required
def renew_user_vehicle(user_id, vehicle_id):
    """Thuê thêm tháng: gia hạn vé tháng (nối tiếp ngày hết hạn nếu còn hạn) hoặc đổi vé lượt -> vé tháng
    (bắt đầu tính từ hôm nay). Tiền = giá tháng trong Bảng giá x số tháng."""
    target = database.get_user_by_id(user_id)
    vehicle = database.get_user_vehicle(vehicle_id)
    if not can_manage_user(target) or vehicle is None or vehicle['user_id'] != user_id:
        flash('Bạn không có quyền thực hiện thao tác này.', 'error')
        return redirect(url_for('users'))
    back = redirect(url_for('edit_user', user_id=user_id))

    months = _to_int(request.form.get('months'))
    error, info = renew_vehicle(vehicle, months)
    if error:
        flash(error, 'error')
        return back
    flash(f'Đã thuê {months} tháng cho xe {vehicle["plate_number"]}: '
          f'{vdate_filter(info["start"])} → {vdate_filter(info["expires"])} — cần thu {vnd_filter(info["total"])}.',
          'success')
    return back


@app.route('/users/<int:user_id>/vehicles/<int:vehicle_id>/delete', methods=['POST'])
@login_required
@staff_required
def remove_user_vehicle(user_id, vehicle_id):
    target = database.get_user_by_id(user_id)
    vehicle = database.get_user_vehicle(vehicle_id)
    if not can_manage_user(target) or vehicle is None or vehicle['user_id'] != user_id:
        flash('Bạn không có quyền thực hiện thao tác này.', 'error')
        return redirect(url_for('users'))
    database.delete_user_vehicle(vehicle_id)
    flash(f'Đã hủy đăng ký xe {vehicle["plate_number"]}.', 'success')
    return redirect(url_for('edit_user', user_id=user_id))


@app.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_user(user_id):
    target = database.get_user_by_id(user_id)
    if target and target['username'] == 'admin':
        flash('Không thể khóa tài khoản admin.', 'error')
        return redirect(request.referrer or url_for('accounts'))
    database.toggle_user_status(user_id)
    flash('Đã cập nhật trạng thái tài khoản.', 'success')
    if target and target['role'] == 'user':
        return redirect(request.referrer or url_for('customers'))
    return redirect(request.referrer or url_for('accounts'))


@app.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def remove_user(user_id):
    target = database.get_user_by_id(user_id)
    if target and target['username'] == 'admin':
        flash('Không thể xóa tài khoản admin.', 'error')
        return redirect(request.referrer or url_for('accounts'))
    is_cust = target and target['role'] == 'user'
    database.delete_user(user_id)
    flash('Đã xóa tài khoản thành công.', 'success')
    return redirect(request.referrer or (url_for('customers') if is_cust else url_for('accounts')))


# ============================================================
# NGƯỜI DÙNG TỰ PHỤC VỤ (/me/...): đổi mật khẩu, gia hạn vé, đổi biển số, đăng ký thêm xe
# ============================================================

MAX_SELF_CHANGES = 3   # số lần tối đa người dùng tự đổi mật khẩu / tự đổi biển số


def render_user_settings(**extra):
    me = database.get_user_by_id(session['user_id'])
    return render_template('user_settings.html', me=me,
                           vehicles=database.get_user_vehicles(me['id']),
                           vehicle_types=database.get_vehicle_types(),
                           ticket_labels=TICKET_LABELS, today=date.today().isoformat(),
                           price_info=build_price_info(), max_months=MAX_MONTHS,
                           max_changes=MAX_SELF_CHANGES, **extra)


def my_vehicle(vehicle_id):
    """Xe đăng ký của chính người đang đăng nhập (hoặc None)."""
    v = database.get_user_vehicle(vehicle_id)
    return v if v is not None and v['user_id'] == session['user_id'] else None


@app.route('/me/password', methods=['POST'])
@login_required
@user_required
def me_password():
    me = database.get_user_by_id(session['user_id'])
    current = request.form.get('current_password', '')
    new_pw = request.form.get('new_password', '')
    confirm = request.form.get('confirm_password', '')
    if me['password_changes'] >= MAX_SELF_CHANGES:
        flash(f'Bạn đã đổi mật khẩu đủ {MAX_SELF_CHANGES} lần. Vui lòng liên hệ nhân viên nếu cần đổi thêm.', 'error')
    elif current != me['password']:
        flash('Mật khẩu hiện tại không đúng.', 'error')
    elif len(new_pw) < MIN_PASSWORD_LEN:
        flash(f'Mật khẩu mới tối thiểu {MIN_PASSWORD_LEN} ký tự.', 'error')
    elif new_pw == current:
        flash('Mật khẩu mới phải khác mật khẩu hiện tại.', 'error')
    elif new_pw != confirm:
        flash('Mật khẩu nhập lại không khớp.', 'error')
    else:
        database.change_own_password(me['id'], new_pw)
        left = MAX_SELF_CHANGES - me['password_changes'] - 1
        flash(f'Đã đổi mật khẩu. Bạn còn {left} lần đổi mật khẩu.', 'success')
    return redirect(url_for('settings') + '#password')


@app.route('/me/vehicles/<int:vehicle_id>/renew', methods=['POST'])
@login_required
@user_required
def me_renew(vehicle_id):
    vehicle = my_vehicle(vehicle_id)
    if vehicle is None:
        flash('Không tìm thấy xe đăng ký.', 'error')
        return redirect(url_for('settings'))
    months = _to_int(request.form.get('months'))
    error, info = renew_vehicle(vehicle, months)
    if error:
        flash(error, 'error')
    else:
        flash(f'Đã gia hạn {months} tháng cho xe {vehicle["plate_number"]}: '
              f'{vdate_filter(info["start"])} → {vdate_filter(info["expires"])}. '
              f'Số tiền cần thanh toán: {vnd_filter(info["total"])}.', 'success')
    return redirect(url_for('settings') + '#vehicles')


@app.route('/me/vehicles/<int:vehicle_id>/plate', methods=['POST'])
@login_required
@user_required
def me_change_plate(vehicle_id):
    vehicle = my_vehicle(vehicle_id)
    back = redirect(url_for('settings') + '#vehicles')
    if vehicle is None:
        flash('Không tìm thấy xe đăng ký.', 'error')
        return back
    me = database.get_user_by_id(session['user_id'])
    if me['plate_changes'] >= MAX_SELF_CHANGES:
        flash(f'Bạn đã đổi biển số đủ {MAX_SELF_CHANGES} lần. Vui lòng liên hệ nhân viên nếu cần đổi thêm.', 'error')
        return back
    plate = clean_plate_input(request.form.get('plate', ''))
    key = plate_key(plate)
    if len(key) < 4:
        flash('Biển số mới quá ngắn (tối thiểu 4 ký tự).', 'error')
        return back
    if key == vehicle['plate_key']:
        flash('Biển số mới trùng với biển số hiện tại.', 'error')
        return back
    if database.find_vehicle_owner(key) is not None:
        flash('Biển số này đã được đăng ký cho một tài khoản khác.', 'error')
        return back
    if any(plate_key(r['plate_number']) == vehicle['plate_key'] for r in database.get_open_records()):
        flash('Xe đang gửi trong bãi, không thể đổi biển số lúc này. Hãy đổi sau khi lấy xe ra.', 'error')
        return back
    database.change_vehicle_plate(vehicle_id, me['id'], plate, key)
    left = MAX_SELF_CHANGES - me['plate_changes'] - 1
    flash(f'Đã đổi biển số {vehicle["plate_number"]} → {plate}. Bạn còn {left} lần đổi biển số.', 'success')
    return back


@app.route('/me/vehicles/add', methods=['POST'])
@login_required
@user_required
def me_add_vehicle():
    vehicles, errors, prefill = parse_vehicle_forms(request.form)
    if not vehicles and not errors:
        errors.append('Vui lòng nhập biển số xe cần đăng ký.')
    if errors:
        for e in errors:
            flash(e, 'error')
        return render_user_settings(prefill=prefill[0] if prefill else None)
    save_vehicles(session['user_id'], vehicles[:1])
    v = vehicles[0]
    money = f' Số tiền vé tháng cần thanh toán: {vnd_filter(v["paid_amount"])}.' if v['paid_amount'] else ''
    flash(f'Đã đăng ký thêm xe {v["plate_number"]}.{money}', 'success')
    return redirect(url_for('settings') + '#vehicles')


if __name__ == '__main__':
    # threaded=True: mỗi yêu cầu (làn vào, làn ra, luồng camera) chạy trên luồng riêng.
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
