"""
database.py
Lớp thao tác dữ liệu (Data Access Layer) cho hệ thống bãi đỗ xe thông minh.
Sử dụng SQLite - phù hợp cho demo, không cần cài đặt server DB riêng.

Bao gồm:
 - Lịch sử xe vào/ra (parking_records)
 - Sơ đồ vị trí đỗ xe theo khu A/B/C (parking_slots)
 - Người dùng hệ thống, đăng nhập (users)
 - Các hàm thống kê cho trang Thống kê
"""

import sqlite3
import os
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, 'parking.db')
SCHEMA_PATH = os.path.join(BASE_DIR, 'schema.sql')

AREAS = ['A', 'B', 'C']
SLOTS_PER_AREA = 20


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # cho phép truy cập cột theo tên
    return conn


def init_db():
    """Khởi tạo database theo file schema.sql, seed dữ liệu mẫu (vị trí đỗ, tài khoản)."""
    conn = get_connection()
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        conn.executescript(f.read())

    # Migration nhẹ: nếu bảng parking_records cũ (từ bản trước) chưa có cột slot_name
    for col_sql in ("ALTER TABLE parking_records ADD COLUMN slot_name TEXT",
                    "ALTER TABLE parking_records ADD COLUMN vehicle_type_id INTEGER",
                    "ALTER TABLE parking_records ADD COLUMN vehicle_type_name TEXT",
                    "ALTER TABLE parking_records ADD COLUMN note TEXT"):
        try:
            conn.execute(col_sql)
        except sqlite3.OperationalError:
            pass  # cột đã tồn tại

    conn.commit()

    # Seed 60 vị trí đỗ (A01..A20, B01..B20, C01..C20) nếu bảng đang trống
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM parking_slots")
    if cur.fetchone()['c'] == 0:
        rows = []
        for area in AREAS:
            for i in range(1, SLOTS_PER_AREA + 1):
                rows.append((f"{area}{i:02d}", area))
        conn.executemany(
            "INSERT INTO parking_slots (slot_name, area, status) VALUES (?, ?, 'available')",
            rows
        )
        conn.commit()

    # Seed tài khoản mặc định nếu bảng users đang trống
    cur.execute("SELECT COUNT(*) AS c FROM users")
    if cur.fetchone()['c'] == 0:
        default_users = [
            ('admin', 'Quản trị viên', '123456', 'admin', 'active'),
            ('nhanvien01', 'Nhân Viên 01', '123456', 'manager', 'active'),
        ]
        conn.executemany(
            "INSERT INTO users (username, fullname, password, role, status) VALUES (?, ?, ?, ?, ?)",
            default_users
        )
        conn.commit()

    # Seed cài đặt mặc định: chế độ chọn vị trí đỗ xe = 'manual' (tự mình chọn)
    cur.execute("SELECT COUNT(*) AS c FROM settings WHERE key = 'entry_mode'")
    if cur.fetchone()['c'] == 0:
        conn.execute("INSERT INTO settings (key, value) VALUES ('entry_mode', 'manual')")
        conn.commit()

    conn.close()
    seed_pricing()


# ============================================================
# LỊCH SỬ XE VÀO / RA
# ============================================================

def add_entry_record(plate_number: str, entry_image: str, slot_name: str = None,
                     vehicle_type_id: int = None, vehicle_type_name: str = None,
                     note: str = None) -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO parking_records
               (plate_number, entry_time, entry_image, slot_name, vehicle_type_id, vehicle_type_name, note, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'IN')""",
        (plate_number, datetime.now().isoformat(timespec='seconds'), entry_image, slot_name,
         vehicle_type_id, vehicle_type_name, note or None)
    )
    conn.commit()
    record_id = cur.lastrowid
    conn.close()
    return record_id


def find_open_record(plate_number: str):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT * FROM parking_records
           WHERE plate_number = ? AND status = 'IN'
           ORDER BY entry_time DESC LIMIT 1""",
        (plate_number,)
    )
    row = cur.fetchone()
    conn.close()
    return row


def close_record(record_id: int, exit_image: str, fee: int, note: str = None):
    """Đóng lượt gửi xe. Nếu có ghi chú lúc ra thì nối thêm vào ghi chú lúc vào (nếu có)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """UPDATE parking_records
           SET exit_time = ?, exit_image = ?, fee = ?, status = 'OUT',
               note = CASE
                        WHEN ? IS NULL THEN note
                        WHEN note IS NULL OR note = '' THEN 'Ra: ' || ?
                        ELSE note || ' | Ra: ' || ?
                      END
           WHERE id = ?""",
        (datetime.now().isoformat(timespec='seconds'), exit_image, fee,
         note or None, note, note, record_id)
    )
    conn.commit()
    conn.close()


def get_open_records():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM parking_records WHERE status = 'IN' ORDER BY entry_time DESC")
    rows = cur.fetchall()
    conn.close()
    return rows


def get_all_records():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM parking_records ORDER BY entry_time DESC")
    rows = cur.fetchall()
    conn.close()
    return rows


def count_open() -> int:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM parking_records WHERE status = 'IN'")
    n = cur.fetchone()['c']
    conn.close()
    return n


# ============================================================
# SƠ ĐỒ VỊ TRÍ ĐỖ XE
# ============================================================

def get_available_slots_by_area():
    """Trả về dict {area: [slot_row, ...]} chỉ gồm các vị trí đang trống — dùng cho trang xe vào chọn ô."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM parking_slots WHERE status = 'available' ORDER BY area, slot_name"
    )
    rows = cur.fetchall()
    conn.close()
    result = {a: [] for a in AREAS}
    for row in rows:
        result.setdefault(row['area'], []).append(row)
    return result


def is_slot_available(slot_name: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT status FROM parking_slots WHERE slot_name = ?", (slot_name,))
    row = cur.fetchone()
    conn.close()
    return row is not None and row['status'] == 'available'


def get_all_slots():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM parking_slots ORDER BY area, slot_name")
    rows = cur.fetchall()
    conn.close()
    return rows


def find_free_slot(area: str = None):
    """Tìm 1 vị trí trống (ưu tiên theo khu nếu chỉ định). Trả về slot_name hoặc None."""
    conn = get_connection()
    cur = conn.cursor()
    if area:
        cur.execute(
            "SELECT slot_name FROM parking_slots WHERE status = 'available' AND area = ? ORDER BY slot_name LIMIT 1",
            (area,)
        )
    else:
        cur.execute(
            "SELECT slot_name FROM parking_slots WHERE status = 'available' ORDER BY area, slot_name LIMIT 1"
        )
    row = cur.fetchone()
    conn.close()
    return row['slot_name'] if row else None


def occupy_slot(slot_name: str, plate_number: str):
    conn = get_connection()
    conn.execute(
        "UPDATE parking_slots SET status = 'occupied', plate_number = ? WHERE slot_name = ?",
        (plate_number, slot_name)
    )
    conn.commit()
    conn.close()


def free_slot(slot_name: str):
    if not slot_name:
        return
    conn = get_connection()
    conn.execute(
        "UPDATE parking_slots SET status = 'available', plate_number = NULL WHERE slot_name = ?",
        (slot_name,)
    )
    conn.commit()
    conn.close()


def set_slot_maintenance(slot_name: str, in_maintenance: bool):
    conn = get_connection()
    new_status = 'maintenance' if in_maintenance else 'available'
    conn.execute(
        "UPDATE parking_slots SET status = ?, plate_number = NULL WHERE slot_name = ?",
        (new_status, slot_name)
    )
    conn.commit()
    conn.close()


def slot_counts():
    """Trả về dict {available, occupied, maintenance, total}."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT status, COUNT(*) AS c FROM parking_slots GROUP BY status")
    counts = {'available': 0, 'occupied': 0, 'maintenance': 0}
    for row in cur.fetchall():
        counts[row['status']] = row['c']
    counts['total'] = sum(counts.values())
    conn.close()
    return counts


def area_stats():
    """Trả về dict {area: {total, occupied, available, percent}} cho trang thống kê."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT area, status, COUNT(*) AS c FROM parking_slots GROUP BY area, status"
    )
    result = {a: {'total': 0, 'occupied': 0, 'available': 0, 'maintenance': 0} for a in AREAS}
    for row in cur.fetchall():
        area = row['area']
        result.setdefault(area, {'total': 0, 'occupied': 0, 'available': 0, 'maintenance': 0})
        result[area][row['status']] = row['c']
        result[area]['total'] += row['c']
    for area, data in result.items():
        data['percent'] = round((data['occupied'] / data['total'] * 100) if data['total'] else 0, 1)
    conn.close()
    return result


# ============================================================
# NGƯỜI DÙNG / ĐĂNG NHẬP
# ============================================================

def verify_login(username: str, password: str):
    """Trả về user row nếu đăng nhập đúng và tài khoản đang active, ngược lại None."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM users WHERE username = ? AND password = ?",
        (username, password)
    )
    row = cur.fetchone()
    conn.close()
    if row and row['status'] == 'active':
        return row
    return None


def get_user_by_id(user_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_all_users():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    return rows


def username_exists(username: str) -> bool:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE username = ?", (username,))
    exists = cur.fetchone() is not None
    conn.close()
    return exists


def add_user(username: str, fullname: str, password: str, role: str):
    conn = get_connection()
    conn.execute(
        "INSERT INTO users (username, fullname, password, role, status) VALUES (?, ?, ?, ?, 'active')",
        (username, fullname, password, role)
    )
    conn.commit()
    conn.close()


def toggle_user_status(user_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT status FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    if row:
        new_status = 'locked' if row['status'] == 'active' else 'active'
        conn.execute("UPDATE users SET status = ? WHERE id = ?", (new_status, user_id))
        conn.commit()
    conn.close()


def delete_user(user_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


# ============================================================
# THỐNG KÊ
# ============================================================

def get_statistics():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS c FROM parking_records")
    total_records = cur.fetchone()['c']

    cur.execute("SELECT COUNT(*) AS c FROM parking_records WHERE status = 'IN'")
    total_in = cur.fetchone()['c']

    cur.execute("SELECT COUNT(*) AS c FROM parking_records WHERE status = 'OUT'")
    total_out = cur.fetchone()['c']

    cur.execute("SELECT COALESCE(SUM(fee), 0) AS s FROM parking_records WHERE status = 'OUT'")
    total_revenue = cur.fetchone()['s']

    today_str = datetime.now().strftime('%Y-%m-%d')
    cur.execute(
        "SELECT COUNT(*) AS c FROM parking_records WHERE substr(entry_time, 1, 10) = ?",
        (today_str,)
    )
    today_entries = cur.fetchone()['c']

    cur.execute(
        "SELECT COALESCE(SUM(fee), 0) AS s FROM parking_records "
        "WHERE status = 'OUT' AND substr(exit_time, 1, 10) = ?",
        (today_str,)
    )
    today_revenue = cur.fetchone()['s']

    conn.close()

    return {
        'total_records': total_records,
        'total_in': total_in,
        'total_out': total_out,
        'total_revenue': total_revenue,
        'today_entries': today_entries,
        'today_revenue': today_revenue,
    }


# ============================================================
# CÀI ĐẶT HỆ THỐNG
# ============================================================

def get_setting(key: str, default: str = None) -> str:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return row['value'] if row else default


def set_setting(key: str, value: str):
    conn = get_connection()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value)
    )
    conn.commit()
    conn.close()


# ----- Cài đặt riêng của từng người dùng -----
# Lưu trong bảng settings với khóa dạng "user:<id>:<key>".
# Nếu người dùng chưa chọn, dùng giá trị mặc định chung (khóa không có tiền tố).

def get_user_setting(user_id: int, key: str, default: str = None) -> str:
    fallback = get_setting(key, default)
    return get_setting(f"user:{user_id}:{key}", fallback)


def set_user_setting(user_id: int, key: str, value: str):
    set_setting(f"user:{user_id}:{key}", value)


# ============================================================
# BẢNG GIÁ XE (khung thời gian / loại xe / giá)
# ============================================================

TICKET_LABELS = {'turn': 'Lượt', 'month': 'Tháng'}


def seed_pricing():
    """Seed dữ liệu mẫu cho bảng giá nếu cả 3 bảng đang trống."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT (SELECT COUNT(*) FROM price_periods) + (SELECT COUNT(*) FROM vehicle_types) "
                "+ (SELECT COUNT(*) FROM prices) AS c")
    if cur.fetchone()['c'] == 0:
        periods = [('Đêm', 'time', '00:00', '04:59'), ('Tháng', 'day', '01', '30'),
                   ('Tối', 'time', '17:00', '23:59'), ('Chiều', 'time', '13:00', '16:59'),
                   ('Sáng', 'time', '05:00', '12:59')]
        types = ['Xe máy điện', 'Xe đạp điện', 'Xe máy', 'Ô tô']
        conn.executemany("INSERT INTO price_periods (name, kind, start_value, end_value) VALUES (?,?,?,?)", periods)
        conn.executemany("INSERT INTO vehicle_types (name) VALUES (?)", [(t,) for t in types])
        prices = [('Xe máy điện', 'Sáng', 5000, 'turn'), ('Xe máy điện', 'Tối', 5000, 'turn'),
                  ('Xe máy điện', 'Chiều', 5000, 'turn'), ('Xe máy', 'Sáng', 5000, 'turn'),
                  ('Xe máy', 'Đêm', 10000, 'turn'), ('Xe máy', 'Tháng', 100000, 'month'),
                  ('Xe máy', 'Chiều', 5000, 'turn'), ('Ô tô', 'Chiều', 150000, 'turn'),
                  ('Ô tô', 'Sáng', 150000, 'turn'), ('Ô tô', 'Đêm', 300000, 'turn'),
                  ('Ô tô', 'Tối', 250000, 'turn')]
        for t, p, amt, tk in prices:
            conn.execute(
                "INSERT INTO prices (vehicle_type_id, period_id, amount, ticket_type) VALUES "
                "((SELECT id FROM vehicle_types WHERE name = ?), (SELECT id FROM price_periods WHERE name = ?), ?, ?)",
                (t, p, amt, tk))
        conn.commit()
    conn.close()


def _fetch(sql, params=()):
    conn = get_connection()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def _exec(sql, params=()):
    conn = get_connection()
    cur = conn.execute(sql, params)
    conn.commit()
    last = cur.lastrowid
    conn.close()
    return last


# ----- Khung thời gian -----

def get_periods():
    return _fetch("SELECT * FROM price_periods ORDER BY id")


def period_name_taken(name: str, exclude_id: int = None) -> bool:
    rows = _fetch("SELECT id FROM price_periods WHERE LOWER(name) = LOWER(?) AND id != ?",
                  (name, exclude_id or 0))
    return len(rows) > 0


def save_period(period_id, name, kind, start_value, end_value):
    if period_id:
        _exec("UPDATE price_periods SET name=?, kind=?, start_value=?, end_value=? WHERE id=?",
              (name, kind, start_value, end_value, period_id))
    else:
        _exec("INSERT INTO price_periods (name, kind, start_value, end_value) VALUES (?,?,?,?)",
              (name, kind, start_value, end_value))


def delete_period(period_id: int):
    _exec("DELETE FROM prices WHERE period_id = ?", (period_id,))
    _exec("DELETE FROM price_periods WHERE id = ?", (period_id,))


# ----- Loại xe -----

def get_vehicle_types():
    return _fetch("SELECT * FROM vehicle_types ORDER BY id")


def vehicle_type_name_taken(name: str, exclude_id: int = None) -> bool:
    rows = _fetch("SELECT id FROM vehicle_types WHERE LOWER(name) = LOWER(?) AND id != ?",
                  (name, exclude_id or 0))
    return len(rows) > 0


def save_vehicle_type(type_id, name):
    if type_id:
        _exec("UPDATE vehicle_types SET name=? WHERE id=?", (name, type_id))
    else:
        _exec("INSERT INTO vehicle_types (name) VALUES (?)", (name,))


def delete_vehicle_type(type_id: int):
    _exec("DELETE FROM prices WHERE vehicle_type_id = ?", (type_id,))
    _exec("DELETE FROM vehicle_types WHERE id = ?", (type_id,))


# ----- Giá (loại xe + thời gian) -----

def get_prices():
    return _fetch(
        "SELECT p.id, p.vehicle_type_id, p.period_id, p.amount, p.ticket_type, "
        "       v.name AS vehicle_name, t.name AS period_name, "
        "       t.start_value, t.end_value, t.kind "
        "FROM prices p "
        "JOIN vehicle_types v ON v.id = p.vehicle_type_id "
        "JOIN price_periods t ON t.id = p.period_id "
        "ORDER BY v.id, t.id")


def price_exists(vehicle_type_id: int, period_id: int, exclude_id: int = None) -> bool:
    rows = _fetch("SELECT id FROM prices WHERE vehicle_type_id=? AND period_id=? AND id != ?",
                  (vehicle_type_id, period_id, exclude_id or 0))
    return len(rows) > 0


def save_price(price_id, vehicle_type_id, period_id, amount, ticket_type):
    if price_id:
        _exec("UPDATE prices SET vehicle_type_id=?, period_id=?, amount=?, ticket_type=? WHERE id=?",
              (vehicle_type_id, period_id, amount, ticket_type, price_id))
    else:
        _exec("INSERT INTO prices (vehicle_type_id, period_id, amount, ticket_type) VALUES (?,?,?,?)",
              (vehicle_type_id, period_id, amount, ticket_type))


def delete_price(price_id: int):
    _exec("DELETE FROM prices WHERE id = ?", (price_id,))


# ----- Tra giá theo loại xe + thời điểm xe vào -----

def _hhmm_to_minutes(value: str) -> int:
    h, m = value.split(':')
    return int(h) * 60 + int(m)


def _minute_in_range(minute: int, start: int, end: int) -> bool:
    """Khoảng [start, end] tính cả hai đầu; nếu start > end thì là khoảng qua nửa đêm (vd 22:00-03:00)."""
    if start <= end:
        return start <= minute <= end
    return minute >= start or minute <= end


def find_turn_price(vehicle_type_id: int, when: datetime):
    """Tìm giá vé LƯỢT của loại xe tại thời điểm `when` (so khớp theo phút, bỏ qua giây).
    Trả về dict {amount, period_name, start, end} hoặc None nếu chưa có giá phù hợp.
    Nếu nhiều khung chồng lên nhau thì lấy khung được tạo trước."""
    if not vehicle_type_id:
        return None
    minute = when.hour * 60 + when.minute
    rows = _fetch(
        "SELECT p.amount, t.name AS period_name, t.start_value, t.end_value "
        "FROM prices p JOIN price_periods t ON t.id = p.period_id "
        "WHERE p.vehicle_type_id = ? AND p.ticket_type = 'turn' AND t.kind = 'time' "
        "ORDER BY t.id", (vehicle_type_id,))
    for r in rows:
        if _minute_in_range(minute, _hhmm_to_minutes(r['start_value']), _hhmm_to_minutes(r['end_value'])):
            return {'amount': r['amount'], 'period_name': r['period_name'],
                    'start': r['start_value'], 'end': r['end_value']}
    return None
