"""
app.py
Ứng dụng web Flask cho hệ thống Bãi đỗ xe thông minh (bản ghép đầy đủ chức năng).

Chức năng:
  /login, /logout   - Đăng nhập / đăng xuất
  /                  - Menu chính (trang chủ)
  /parking           - Sơ đồ bãi đỗ theo khu A/B/C (dữ liệu thật từ DB)
  /entry             - Xe vào bãi: upload ảnh -> OCR biển số -> gán vị trí -> lưu DB
  /exit              - Xe ra bãi : upload ảnh -> OCR biển số -> đối chiếu -> tính phí -> trả vị trí
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
from datetime import datetime

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
from plate_recognition import recognize_plate

BASE_DIR = os.path.dirname(__file__)
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

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
    duration = exit_time - entry_time

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
# XE VÀO / XE RA (OCR BIỂN SỐ)
# ============================================================

@app.route('/entry', methods=['GET', 'POST'])
@login_required
def entry():
    # Chế độ gán vị trí là lựa chọn riêng của từng người dùng ('auto' hoặc 'manual')
    entry_mode = database.get_user_setting(session['user_id'], 'entry_mode', 'manual')

    if request.method == 'POST':
        file = request.files.get('image')

        if not file or file.filename == '':
            flash('Vui lòng chọn ảnh chụp xe/biển số.', 'error')
            return redirect(url_for('entry'))

        # Loại xe bắt buộc phải chọn và phải có giá lượt tại thời điểm này
        type_id = _to_int(request.form.get('vehicle_type_id'))
        vehicle_type = next((t for t in database.get_vehicle_types() if t['id'] == type_id), None)
        if vehicle_type is None:
            flash('Vui lòng chọn loại xe.', 'error')
            return redirect(url_for('entry'))
        entry_price = database.find_turn_price(type_id, datetime.now())
        if entry_price is None:
            flash(f'Chưa có giá cho "{vehicle_type["name"]}" lúc {datetime.now():%H:%M}. '
                  'Vui lòng nhờ nhân viên/admin bổ sung ở trang Giá xe.', 'error')
            return redirect(url_for('entry'))

        if entry_mode == 'auto':
            # Chế độ tự động: hệ thống tự chọn 1 vị trí trống bất kỳ, không cần người dùng chọn
            chosen_slot = database.find_free_slot()
            if not chosen_slot:
                flash('Bãi đỗ đã hết chỗ trống! Không thể nhận thêm xe.', 'error')
                return redirect(url_for('entry'))
        else:
            # Chế độ tự chọn: bắt buộc người dùng chọn 1 vị trí cụ thể
            chosen_slot = request.form.get('slot_name', '').strip()
            if not chosen_slot:
                flash('Vui lòng chọn một vị trí đỗ.', 'error')
                return redirect(url_for('entry'))
            if not database.is_slot_available(chosen_slot):
                flash(f'Vị trí {chosen_slot} vừa có xe khác đỗ vào, vui lòng chọn vị trí khác.', 'error')
                return redirect(url_for('entry'))

        filename, path = save_upload(file, 'in')

        try:
            plate_text, _ = recognize_plate(path)
        except Exception as e:
            flash(f'Lỗi khi nhận diện biển số: {e}', 'error')
            return redirect(url_for('entry'))

        if not plate_text or len(plate_text) < 4:
            flash('Không nhận diện được biển số rõ ràng, vui lòng chụp lại (đủ sáng, ít góc nghiêng).', 'error')
            return redirect(url_for('entry'))

        if database.find_open_record(plate_text) is not None:
            flash(f'Xe {plate_text} đã có mặt trong bãi, chưa ra.', 'error')
            return redirect(url_for('entry'))

        # Kiểm tra lại lần cuối (tránh trường hợp 2 người/2 quy trình cùng chiếm 1 ô cùng lúc)
        if not database.is_slot_available(chosen_slot):
            if entry_mode == 'auto':
                chosen_slot = database.find_free_slot()
                if not chosen_slot:
                    flash('Bãi đỗ đã hết chỗ trống! Không thể nhận thêm xe.', 'error')
                    return redirect(url_for('entry'))
            else:
                flash(f'Vị trí {chosen_slot} vừa có xe khác đỗ vào, vui lòng chọn vị trí khác.', 'error')
                return redirect(url_for('entry'))

        database.add_entry_record(plate_text, filename, chosen_slot, type_id, vehicle_type['name'])
        database.occupy_slot(chosen_slot, plate_text)

        flash(f'✅ Xe vào bãi thành công! Biển số: {plate_text} — {vehicle_type["name"]} — Vị trí: {chosen_slot} '
              f'— Giá: {entry_price["amount"]:,} VNĐ/lượt (khung {entry_price["period_name"]})', 'success')
        return redirect(url_for('index'))

    slots_by_area = database.get_available_slots_by_area()
    now = datetime.now()
    type_options = []
    for t in database.get_vehicle_types():
        price = database.find_turn_price(t['id'], now)
        type_options.append({'id': t['id'], 'name': t['name'], 'price': price})
    return render_template('entry.html', slots_by_area=slots_by_area, entry_mode=entry_mode,
                           type_options=type_options, now=now)


@app.route('/exit', methods=['GET', 'POST'])
@login_required
def exit_gate():
    if request.method == 'POST':
        file = request.files.get('image')
        if not file or file.filename == '':
            flash('Vui lòng chọn ảnh chụp xe/biển số.', 'error')
            return redirect(url_for('exit_gate'))

        filename, path = save_upload(file, 'out')

        try:
            plate_text, _ = recognize_plate(path)
        except Exception as e:
            flash(f'Lỗi khi nhận diện biển số: {e}', 'error')
            return redirect(url_for('exit_gate'))

        record = database.find_open_record(plate_text)
        if record is None:
            flash(f'⚠️ Không tìm thấy xe đang gửi với biển số "{plate_text or "(không rõ)"}".', 'error')
            return redirect(url_for('exit_gate'))

        now = datetime.now()
        fee, duration, fee_note = calc_fee(record, now)
        database.close_record(record['id'], filename, fee)
        database.free_slot(record['slot_name'])

        flash(
            f'✅ Xe {plate_text} đã ra bãi (vị trí {record["slot_name"] or "?"}). '
            f'Thời gian gửi: {duration}. Phí: {fee:,} VNĐ ({fee_note})',
            'success'
        )
        return redirect(url_for('index'))

    return render_template('exit.html')


# ============================================================
# LỊCH SỬ
# ============================================================

@app.route('/history')
@login_required
def history():
    keyword = request.args.get('plate', '').strip().upper()
    status_filter = request.args.get('status', 'all')
    date_filter = request.args.get('date', '')

    records = database.get_all_records()

    in_count = sum(1 for r in records if r['status'] == 'IN')
    out_count = sum(1 for r in records if r['status'] == 'OUT')
    today_str = datetime.now().strftime('%Y-%m-%d')
    today_count = sum(1 for r in records if (r['entry_time'] or '').startswith(today_str))

    def matches(r):
        if keyword and keyword not in (r['plate_number'] or '').upper():
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
    valid_periods = {p['id'] for p in database.get_periods()}

    if type_id not in valid_types or period_id not in valid_periods:
        flash('Vui lòng chọn loại xe và khung thời gian (tạo trước nếu chưa có).', 'error')
    elif amount is None or amount < 0:
        flash('Giá tiền phải là số nguyên không âm.', 'error')
    elif ticket_type not in database.TICKET_LABELS:
        flash('Loại vé không hợp lệ.', 'error')
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
