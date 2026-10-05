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
import uuid
import re
import functools
from datetime import datetime, timedelta

# --- Kiểm tra thư viện cần thiết đã được cài đủ chưa ---
try:
    from flask import (
        Flask, render_template, request, redirect, url_for, flash, session
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

import database
from plate_recognition import recognize_plate_annotated
from plate_utils import normalize_plate, plate_key

BASE_DIR = os.path.dirname(__file__)
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
TMP_FOLDER = os.path.join(UPLOAD_FOLDER, 'tmp')   # ảnh tạm giữa bước "Nhận diện" và bước "Xác nhận"
os.makedirs(TMP_FOLDER, exist_ok=True)

FEE_PER_HOUR = 5000  # đơn giá DỰ PHÒNG (5.000 VNĐ/giờ) — chỉ dùng cho xe cũ chưa có loại xe / không còn giá

app = Flask(__name__)
app.secret_key = 'demo-smart-parking-secret-key'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

with app.app_context():
    database.init_db()


# ============================================================
# TIỆN ÍCH
# ============================================================

def save_upload(file_storage, prefix: str):
    ext = os.path.splitext(file_storage.filename)[1].lower() or '.jpg'
    filename = f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file_storage.save(path)
    return filename, path


def calc_fee(record, exit_time: datetime):
    """Tính phí khi xe ra.
    - Xe có loại xe và còn giá LƯỢT phù hợp với khung giờ lúc xe VÀO -> tính theo bảng giá (1 lượt).
    - Ngược lại (xe cũ chưa có loại xe, hoặc giá đã bị xóa) -> dùng đơn giá dự phòng theo giờ.
    Trả về (phí, thời gian gửi, mô tả cách tính)."""
    entry_time = datetime.fromisoformat(record['entry_time'])
    duration = timedelta(seconds=int((exit_time - entry_time).total_seconds()))

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
    os.replace(src, os.path.join(UPLOAD_FOLDER, filename))
    drop_tmp(token)   # xóa nốt ảnh đánh dấu
    return filename


def render_gate(token='', plate='', note='', form=None):
    """Dựng trang /gate. Có biển số hợp lệ -> xác định xe VÀO hay xe RA và chuẩn bị thông tin tương ứng."""
    token = token if find_tmp(token) else ''
    now = datetime.now()
    ctx = {'token': token, 'plate': plate, 'note': note, 'form': form or {}, 'now': now,
           'mode': None, 'record': None, 'fee_preview': None, 'preview_url': None,
           'type_options': [], 'slots_by_area': {}, 'entry_mode': None, 'no_slots': False}

    if token and os.path.exists(os.path.join(TMP_FOLDER, f'{token}_ann.jpg')):
        ctx['preview_url'] = url_for('static', filename=f'uploads/tmp/{token}_ann.jpg',
                                     v=int(os.path.getmtime(os.path.join(TMP_FOLDER, f'{token}_ann.jpg'))))

    if token and len(plate_key(plate)) >= 4:
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
    return render_template('gate.html', **ctx)


@app.route('/gate', methods=['GET', 'POST'])
@login_required
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

    type_id = _to_int(form.get('vehicle_type_id'))
    vehicle_type = next((t for t in database.get_vehicle_types() if t['id'] == type_id), None)
    if vehicle_type is None:
        flash('Vui lòng chọn loại xe.', 'error')
        return render_gate(token, plate, note, form)
    entry_price = database.find_turn_price(type_id, datetime.now())
    if entry_price is None:
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
    flash(f'✅ Xe vào bãi thành công! Biển số: {plate} — {vehicle_type["name"]} — Vị trí: {chosen_slot} '
          f'— Giá: {entry_price["amount"]:,} VNĐ/lượt (khung {entry_price["period_name"]})', 'success')
    return redirect(url_for('gate'))


@app.route('/entry')
@login_required
def entry():
    return redirect(url_for('gate'))


@app.route('/exit')
@login_required
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
    )


# ============================================================
# THỐNG KÊ
# ============================================================

@app.route('/statistics')
@login_required
def statistics():
    stats = database.get_statistics()
    slot_stats = database.slot_counts()
    area_stats = database.area_stats()
    return render_template('statistics.html', stats=stats, slot_stats=slot_stats, area_stats=area_stats)


# ============================================================
# CÀI ĐẶT CÁ NHÂN (MỌI NGƯỜI DÙNG TỰ CHỌN)
# ============================================================

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
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
# QUẢN LÝ NGƯỜI DÙNG (CHỈ ADMIN)
# ============================================================

@app.route('/users')
@login_required
@admin_required
def users():
    all_users = database.get_all_users()
    return render_template('users.html', users=all_users)


@app.route('/users/add', methods=['POST'])
@login_required
@admin_required
def add_user():
    username = request.form.get('username', '').strip()
    fullname = request.form.get('fullname', '').strip()
    password = request.form.get('password', '')
    role = request.form.get('role', 'user')

    if not username or not fullname or not password:
        flash('Vui lòng nhập đầy đủ thông tin.', 'error')
        return redirect(url_for('users'))

    if database.username_exists(username):
        flash('Tên đăng nhập đã tồn tại.', 'error')
        return redirect(url_for('users'))

    database.add_user(username, fullname, password, role)
    flash(f'Đã thêm người dùng "{username}".', 'success')
    return redirect(url_for('users'))


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


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
