"""
app.py
Ứng dụng web Flask cho hệ thống Bãi đỗ xe thông minh (bản ghép đầy đủ chức năng).

Chức năng:
  /login, /logout   - Đăng nhập / đăng xuất
  /                  - Menu chính (trang chủ)
  /parking           - Sơ đồ bãi đỗ theo khu A/B/C (dữ liệu thật từ DB)
  /gate              - Xe vào / ra (gộp 1 trang): chọn ảnh -> "Nhận diện biển số" -> xem ảnh đánh dấu
                       -> "Xác nhận". Biển số chưa có trong bãi = xe VÀO (chọn loại xe + vị trí),
                       biển số đang gửi = xe RA (tính phí theo bảng giá, trả vị trí)
  /entry, /exit      - Đường dẫn cũ, tự chuyển sang /gate
  /history           - Lịch sử toàn bộ lượt gửi xe (có bộ lọc)
  /statistics        - Thống kê tổng quan
  /pricing           - Bảng giá xe: khung thời gian, loại xe, giá (ai cũng xem, admin/nhân viên chỉnh sửa)
  /settings          - Cài đặt cá nhân (mỗi người tự chọn, không cần admin/nhân viên)
  /users             - Quản lý người dùng (chỉ admin)
"""

import os
import sys
import calendar
import uuid
import re
import functools
from datetime import datetime, timedelta, date

# Thư mục py/ chứa các module (config, database, plate_recognition, ...)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'py'))

# --- Kiểm tra thư viện cần thiết đã được cài đủ chưa ---
try:
    from flask import (
        Flask, render_template, request, redirect, url_for, flash, session,
        send_from_directory, jsonify
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

from config import TMP_DIR, IN_DIR, OUT_DIR, TEMPLATES_HTML_DIR, TEMPLATES_CSS_DIR
import database
from plate_recognition import recognize_plate_annotated, recognize_plate
from plate_utils import normalize_plate, plate_key

TMP_FOLDER = TMP_DIR   # ảnh tạm (cache/tmp) giữa bước "Nhận diện" và bước "Xác nhận"
UPLOAD_DIRS = {'in': IN_DIR, 'out': OUT_DIR}   # static/in: xe vào, static/out: xe ra

FEE_PER_HOUR = 5000  # đơn giá DỰ PHÒNG (5.000 VNĐ/giờ) — chỉ dùng cho xe cũ chưa có loại xe / không còn giá

app = Flask(__name__, template_folder=TEMPLATES_HTML_DIR)
app.secret_key = 'demo-smart-parking-secret-key'


@app.route('/css/<path:filename>')
def css_files(filename):
    """Phục vụ file CSS đặt trong templates/css/."""
    return send_from_directory(TEMPLATES_CSS_DIR, filename)


@app.route('/tmp-preview/<path:filename>')
def tmp_preview(filename):
    """Phục vụ ảnh đánh dấu tạm trong cache/tmp/ (chỉ cho người đã đăng nhập)."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return send_from_directory(TMP_FOLDER, filename)

with app.app_context():
    database.init_db()


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
    - Xe có loại xe và còn giá LƯỢT phù hợp với khung giờ lúc xe VÀO -> tính theo bảng giá (1 lượt).
    - Ngược lại (xe cũ chưa có loại xe, hoặc giá đã bị xóa) -> dùng đơn giá dự phòng theo giờ.
    Trả về (phí, thời gian gửi, mô tả cách tính)."""
    entry_time = datetime.fromisoformat(record['entry_time'])
    duration = timedelta(seconds=int((exit_time - entry_time).total_seconds()))

    # Xe đã đăng ký VÉ THÁNG còn hạn -> miễn phí lượt này
    reg = database.get_registered_vehicle(plate_key(record['plate_number']))
    if month_ticket_valid(reg, exit_time.date()):
        return 0, duration, (f"Vé tháng của tài khoản {reg['username']} "
                             f"(còn hạn đến {reg['expires_on']}) · miễn phí")

    price = database.find_turn_price(record['vehicle_type_id'], entry_time)
    if price is not None:
        note = (f"{record['vehicle_type_name'] or 'Loại xe'} · khung {price['period_name']} "
                f"({price['start']}–{price['end']}) · 1 lượt")
        return price['amount'], duration, note

    total_seconds = duration.total_seconds()
    hours = int(total_seconds // 3600)
    if total_seconds % 3600 > 0:
        hours += 1
    hours = max(1, hours)
    return hours * FEE_PER_HOUR, duration, f"đơn giá dự phòng {FEE_PER_HOUR:,}đ/giờ × {hours} giờ"


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


@app.context_processor
def inject_user():
    return {
        'current_user_fullname': session.get('fullname'),
        'current_user_role': session.get('role'),
        'role_label': ROLE_LABELS.get(session.get('role'), 'Người dùng'),
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


@app.route('/logout')
def logout():
    session.clear()
    flash('Đã đăng xuất.', 'success')
    return redirect(url_for('login'))


# ============================================================
# TRANG CHỦ (MENU CHÍNH)
# ============================================================

@app.route('/')
@login_required
def index():
    counts = database.slot_counts()
    if session.get('role') == 'user':      # người dùng: trang chủ riêng, chỉ có 4 chức năng
        return render_template('user_home.html', counts=counts, today=date.today().isoformat(),
                               vehicles=database.get_user_vehicles(session['user_id']))
    total_in = database.count_open()
    return render_template('index.html', counts=counts, total_in=total_in)


# ============================================================
# SƠ ĐỒ BÃI ĐỖ XE
# ============================================================

@app.route('/parking')
@login_required
def parking():
    slots = database.get_all_slots()
    slots_by_area = {'A': [], 'B': [], 'C': []}
    for slot in slots:
        slots_by_area.setdefault(slot['area'], []).append(slot)
    counts = database.slot_counts()
    return render_template('parking.html', slots_by_area=slots_by_area, counts=counts)


@app.route('/parking/<slot_name>/maintenance', methods=['POST'])
@login_required
@staff_required
def slot_maintenance(slot_name):
    slots = {s['slot_name']: s for s in database.get_all_slots()}
    slot = slots.get(slot_name)
    if slot is None:
        flash('Không tìm thấy vị trí đỗ.', 'error')
    elif slot['status'] == 'occupied':
        flash(f'Không thể đưa {slot_name} vào bảo trì vì đang có xe đỗ.', 'error')
    else:
        going_to_maintenance = slot['status'] != 'maintenance'
        database.set_slot_maintenance(slot_name, going_to_maintenance)
        if going_to_maintenance:
            flash(f'{slot_name} đã được đưa vào bảo trì.', 'success')
        else:
            flash(f'{slot_name} đã kết thúc bảo trì.', 'success')
    return redirect(url_for('parking'))


# ============================================================
# XE VÀO / XE RA — GỘP 1 TRANG (OCR BIỂN SỐ, 2 BƯỚC: NHẬN DIỆN -> XÁC NHẬN)
# ============================================================

TOKEN_RE = re.compile(r'^[0-9a-f]{12}$')
ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}


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


def render_gate(token='', plate='', note='', form=None):
    """Dựng trang /gate. Có biển số hợp lệ -> xác định xe VÀO hay xe RA và chuẩn bị thông tin tương ứng."""
    token = token if find_tmp(token) else ''
    now = datetime.now()
    ctx = {'token': token, 'plate': plate, 'note': note, 'form': form or {}, 'now': now,
           'mode': None, 'record': None, 'fee_preview': None, 'preview_url': None,
           'type_options': [], 'slots_by_area': {}, 'entry_mode': None, 'no_slots': False,
           'registered': None, 'reg_month_ok': False, 'reg_expired': False, 'suggest': None,
           'reg_type': None}

    if token and os.path.exists(os.path.join(TMP_FOLDER, f'{token}_ann.jpg')):
        ctx['preview_url'] = url_for('tmp_preview', filename=f'{token}_ann.jpg',
                                     v=int(os.path.getmtime(os.path.join(TMP_FOLDER, f'{token}_ann.jpg'))))

    if token and len(plate_key(plate)) >= 4:
        registered = database.get_registered_vehicle(plate_key(plate))
        ctx['registered'] = registered
        ctx['reg_month_ok'] = month_ticket_valid(registered, now.date())
        ctx['reg_expired'] = bool(registered and registered['ticket_type'] == 'month'
                                  and not ctx['reg_month_ok'])
        ctx['suggest'] = None if registered else find_similar_registered(plate)
        record = database.find_open_record(plate)
        if record is not None:
            fee, duration, fee_note = calc_fee(record, now)
            ctx.update(mode='exit', record=record,
                       fee_preview={'fee': fee, 'duration': duration, 'note': fee_note})
        else:
            slots_by_area = database.get_available_slots_by_area()
            ctx.update(
                mode='entry',
                entry_mode=database.get_user_setting(session['user_id'], 'entry_mode', 'manual'),
                slots_by_area=slots_by_area,
                no_slots=not any(slots_by_area.get(a) for a in ('A', 'B', 'C')),
                type_options=[{'id': t['id'], 'name': t['name'],
                               'price': database.find_turn_price(t['id'], now)}
                              for t in database.get_vehicle_types()],
            )
            # Xe đã đăng ký (có loại xe): dùng luôn loại xe đã đăng ký, không cần chọn lại
            if registered and registered['vehicle_type_id']:
                ctx['reg_type'] = next((t for t in ctx['type_options']
                                        if t['id'] == registered['vehicle_type_id']), None)
    return render_template('gate.html', **ctx)


@app.route('/gate', methods=['GET', 'POST'])
@login_required
@staff_required
def gate():
    if request.method == 'GET':
        return render_gate()

    action = request.form.get('action', 'recognize')
    note = request.form.get('note', '').strip()
    token = request.form.get('token', '').strip()
    token = token if find_tmp(token) else ''
    plate = clean_plate_input(request.form.get('plate'))

    if action == 'confirm':
        return gate_confirm(token, plate, note)
    return gate_recognize(token, plate, note)


def gate_recognize(token, plate, note):
    """Bước 1: nhận diện biển số từ ảnh mới; hoặc (không chọn ảnh mới) làm mới thông tin theo biển số vừa sửa."""
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
            plate, annotated = recognize_plate_annotated(path)
            cv2.imwrite(os.path.join(TMP_FOLDER, f'{token}_ann.jpg'), annotated)
        except Exception as e:
            drop_tmp(token)
            flash(f'Lỗi khi nhận diện biển số: {e}', 'error')
            return render_gate(note=note)
        if len(plate_key(plate)) < 4:
            flash('Không nhận diện được biển số rõ ràng. Bạn có thể nhập biển số vào ô bên dưới '
                  'rồi bấm "Nhận diện biển số" để tiếp tục, hoặc chọn ảnh khác (đủ sáng, ít góc nghiêng).', 'error')
        return render_gate(token, plate, note)

    if token:
        if len(plate_key(plate)) < 4:
            flash('Biển số quá ngắn, vui lòng nhập lại (tối thiểu 4 ký tự).', 'error')
        return render_gate(token, plate, note)

    flash('Vui lòng chọn hình ảnh biển số.', 'error')
    return render_gate(note=note)


def gate_confirm(token, plate, note):
    """Bước 2: xác nhận. Biển số đang gửi trong bãi -> xe RA, ngược lại -> xe VÀO."""
    if not token:
        flash('Chưa có ảnh đã nhận diện (hoặc ảnh đã hết hạn). Vui lòng chọn ảnh và bấm "Nhận diện biển số".', 'error')
        return render_gate(note=note)

    if len(plate_key(plate)) < 4:
        flash('Biển số quá ngắn, vui lòng nhập lại (tối thiểu 4 ký tự).', 'error')
        return render_gate(token, plate, note)

    # Người dùng vừa sửa biển số sau khi nhận diện -> phải xem lại thông tin theo biển số mới
    checked = clean_plate_input(request.form.get('checked_plate'))
    if plate_key(plate) != plate_key(checked):
        flash('Biển số đã thay đổi — vui lòng xem lại thông tin bên dưới rồi bấm "Xác nhận" lần nữa.', 'error')
        return render_gate(token, plate, note)

    record = database.find_open_record(plate)

    # ---------- XE RA ----------
    if record is not None:
        now = datetime.now()
        fee, duration, fee_note = calc_fee(record, now)
        filename = promote_tmp(token, 'out')
        database.close_record(record['id'], filename, fee, note)
        database.free_slot(record['slot_name'])
        flash(
            f'✅ Xe {plate} đã ra bãi (vị trí {record["slot_name"] or "?"}). '
            f'Thời gian gửi: {duration}. Phí: {fee:,} VNĐ ({fee_note})',
            'success'
        )
        return redirect(url_for('gate'))

    # ---------- XE VÀO ----------
    form = request.form
    entry_mode = database.get_user_setting(session['user_id'], 'entry_mode', 'manual')

    all_types = database.get_vehicle_types()
    registered = database.get_registered_vehicle(plate_key(plate))
    type_id = _to_int(form.get('vehicle_type_id'))
    # Xe đã đăng ký (có loại xe còn tồn tại) -> lấy loại xe theo đăng ký, bỏ qua lựa chọn trên form
    if registered and registered['vehicle_type_id'] \
            and any(t['id'] == registered['vehicle_type_id'] for t in all_types):
        type_id = registered['vehicle_type_id']
    vehicle_type = next((t for t in all_types if t['id'] == type_id), None)
    if vehicle_type is None:
        flash('Vui lòng chọn loại xe.', 'error')
        return render_gate(token, plate, note, form)
    entry_price = database.find_turn_price(type_id, datetime.now())
    month_ok = month_ticket_valid(registered, date.today())
    if entry_price is None and not month_ok:
        flash(f'Chưa có giá cho "{vehicle_type["name"]}" lúc {datetime.now():%H:%M}. '
              'Vui lòng nhờ nhân viên/admin bổ sung ở trang Giá xe.', 'error')
        return render_gate(token, plate, note, form)

    if entry_mode == 'auto':
        chosen_slot = database.find_free_slot()
        if not chosen_slot:
            flash('Bãi đỗ đã hết chỗ trống! Không thể nhận thêm xe.', 'error')
            return render_gate(token, plate, note, form)
    else:
        chosen_slot = form.get('slot_name', '').strip()
        if not chosen_slot:
            flash('Vui lòng chọn một vị trí đỗ.', 'error')
            return render_gate(token, plate, note, form)
        if not database.is_slot_available(chosen_slot):
            flash(f'Vị trí {chosen_slot} vừa có xe khác đỗ vào, vui lòng chọn vị trí khác.', 'error')
            return render_gate(token, plate, note, form)

    filename = promote_tmp(token, 'in')
    database.add_entry_record(plate, filename, chosen_slot, type_id, vehicle_type['name'], note)
    database.occupy_slot(chosen_slot, plate)
    if month_ok:
        price_text = f'Vé tháng còn hạn đến {registered["expires_on"]} (tài khoản {registered["username"]})'
    else:
        price_text = f'Giá: {entry_price["amount"]:,} VNĐ/lượt (khung {entry_price["period_name"]})'
    flash(f'✅ Xe vào bãi thành công! Biển số: {plate} — {vehicle_type["name"]} — Vị trí: {chosen_slot} '
          f'— {price_text}', 'success')
    return redirect(url_for('gate'))


@app.route('/entry')
@login_required
@staff_required
def entry():
    return redirect(url_for('gate'))


@app.route('/exit')
@login_required
@staff_required
def exit_gate():
    return redirect(url_for('gate'))


# ============================================================
# LỊCH SỬ
# ============================================================

@app.route('/history')
@login_required
def history():
    keyword = request.args.get('plate', '').strip().upper()
    keyword_key = plate_key(keyword)     # tìm không phân biệt dấu '-' (61T32222 vẫn ra 61T3-2222)
    status_filter = request.args.get('status', 'all')
    date_filter = request.args.get('date', '')

    records = database.get_all_records()
    is_user = session.get('role') == 'user'
    if is_user:    # người dùng chỉ xem lịch sử của các xe mình đã đăng ký
        my_keys = {v['plate_key'] for v in database.get_user_vehicles(session['user_id'])}
        records = [r for r in records if plate_key(r['plate_number']) in my_keys]

    in_count = sum(1 for r in records if r['status'] == 'IN')
    out_count = sum(1 for r in records if r['status'] == 'OUT')
    today_str = datetime.now().strftime('%Y-%m-%d')
    today_count = sum(1 for r in records if (r['entry_time'] or '').startswith(today_str))

    def matches(r):
        if keyword and keyword not in (r['plate_number'] or '').upper() \
                and not (keyword_key and keyword_key in plate_key(r['plate_number'])):
            return False
        if status_filter != 'all' and r['status'] != status_filter:
            return False
        if date_filter and not (r['entry_time'] or '').startswith(date_filter):
            return False
        return True

    filtered = [r for r in records if matches(r)]

    return render_template(
        'history.html',
        records=filtered,
        keyword=keyword,
        status_filter=status_filter,
        date_filter=date_filter,
        total_count=len(records),
        in_count=in_count,
        out_count=out_count,
        today_count=today_count,
        user_mode=is_user,
    )


# ============================================================
# THỐNG KÊ
# ============================================================

@app.route('/statistics')
@login_required
@staff_required
def statistics():
    start, end, range_key, label = parse_stats_range(request.args)
    stats = database.get_statistics(start.isoformat(), end.isoformat())
    area_stats = database.area_stats()
    return render_template('statistics.html', stats=stats, area_stats=area_stats,
                           range_key=range_key, range_label=label,
                           date_from=start.isoformat(), date_to=end.isoformat(),
                           today_iso=date.today().isoformat())


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
    if key == 'month':
        return today.replace(day=1), today, key, 'tháng này'
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

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if session.get('role') == 'user':      # người dùng: trang cài đặt tài khoản riêng
        return render_user_settings()
    if request.method == 'POST':
        mode = request.form.get('entry_mode')
        if mode not in ('auto', 'manual'):
            flash('Lựa chọn không hợp lệ.', 'error')
            return redirect(url_for('settings'))
        database.set_user_setting(session['user_id'], 'entry_mode', mode)
        flash('Đã lưu cài đặt của bạn.', 'success')
        return redirect(url_for('settings'))

    entry_mode = database.get_user_setting(session['user_id'], 'entry_mode', 'manual')
    return render_template('settings.html', entry_mode=entry_mode)


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
    if not name:
        flash('Vui lòng nhập tên loại xe.', 'error')
    elif database.vehicle_type_name_taken(name, type_id):
        flash(f'Loại xe "{name}" đã tồn tại.', 'error')
    else:
        database.save_vehicle_type(type_id, name)
        flash(f'Đã lưu loại xe "{name}".', 'success')
    return redirect(url_for('pricing'))


@app.route('/pricing/type/<int:type_id>/delete', methods=['POST'])
@login_required
@staff_required
def pricing_type_delete(type_id):
    database.delete_vehicle_type(type_id)
    flash('Đã xóa loại xe (và các giá liên quan).', 'success')
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
    for r in database.get_prices():
        if r['ticket_type'] == 'turn' and r['vehicle_type_id'] in info:
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


def render_users(**extra):
    all_users = database.get_all_users()
    if session.get('role') != 'admin':
        all_users = [u for u in all_users if u['role'] == 'user']
    return render_template('users.html', users=all_users,
                           vehicles_by_user=database.get_vehicles_grouped(),
                           vehicle_types=database.get_vehicle_types(),
                           ticket_labels=TICKET_LABELS, today=date.today().isoformat(),
                           price_info=build_price_info(), max_months=MAX_MONTHS,
                           **extra)


def render_edit_user(target, **extra):
    return render_template('edit_user.html', target=target,
                           vehicles=database.get_user_vehicles(target['id']),
                           vehicle_types=database.get_vehicle_types(),
                           ticket_labels=TICKET_LABELS, today=date.today().isoformat(),
                           price_info=build_price_info(), max_months=MAX_MONTHS,
                           **extra)


@app.route('/users')
@login_required
@staff_required
def users():
    return render_users()


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


@app.route('/users/add', methods=['POST'])
@login_required
@staff_required
def add_user():
    username = request.form.get('username', '').strip()
    fullname = request.form.get('fullname', '').strip()
    password = request.form.get('password', '')
    role = request.form.get('role', 'user')
    # Nhân viên chỉ được tạo tài khoản người dùng; admin tạo được người dùng hoặc nhân viên.
    if session.get('role') != 'admin' or role not in ('user', 'manager'):
        role = 'user'

    vehicles, errors, prefill = ([], [], [])
    if role == 'user':
        vehicles, errors, prefill = parse_vehicle_forms(request.form)

    if not username or not fullname or not password:
        errors.insert(0, 'Vui lòng nhập đầy đủ thông tin.')
    elif len(password) < MIN_PASSWORD_LEN:
        errors.insert(0, f'Mật khẩu tối thiểu {MIN_PASSWORD_LEN} ký tự.')
    elif database.username_exists(username):
        errors.insert(0, 'Tên đăng nhập đã tồn tại.')

    if errors:
        for e in errors:
            flash(e, 'error')
        return render_users(open_modal=True,
                            form={'username': username, 'fullname': fullname, 'role': role},
                            form_vehicles=prefill)

    new_id = database.add_user(username, fullname, password, role)
    save_vehicles(new_id, vehicles)
    extra = f' và đăng ký {len(vehicles)} xe' if vehicles else ''
    total = sum(v['paid_amount'] or 0 for v in vehicles)
    if total:
        extra += f' — tiền vé tháng cần thu: {vnd_filter(total)}'
    flash(f'Đã thêm tài khoản "{username}"{extra}.', 'success')
    return redirect(url_for('users'))


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
        return redirect(url_for('users'))
    database.toggle_user_status(user_id)
    flash('Đã cập nhật trạng thái tài khoản.', 'success')
    return redirect(url_for('users'))


@app.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def remove_user(user_id):
    target = database.get_user_by_id(user_id)
    if target and target['username'] == 'admin':
        flash('Không thể xóa tài khoản admin.', 'error')
        return redirect(url_for('users'))
    database.delete_user(user_id)
    flash('Đã xóa người dùng.', 'success')
    return redirect(url_for('users'))


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
    app.run(debug=True, host='0.0.0.0', port=5000)
