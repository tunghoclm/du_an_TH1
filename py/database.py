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

import glob
from contextlib import contextmanager
from config import DB_PATH, SQL_DIR
from plate_utils import plate_key

DEFAULT_AREAS = ['A', 'B', 'C']
SLOTS_PER_AREA = 6


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # cho phép truy cập cột theo tên
    return conn


def init_db():
    """Khởi tạo database theo file schema.sql, seed dữ liệu mẫu (vị trí đỗ, tài khoản)."""
    conn = get_connection()

    # Đọc TẤT CẢ file .sql trong thư mục SQL/ (tên file nào cũng được: schema.sql, cschema.sql, ...)
    sql_files = sorted(glob.glob(os.path.join(SQL_DIR, '*.sql')))
    if not sql_files:
        raise RuntimeError(f"Không tìm thấy file .sql nào trong thư mục: {SQL_DIR}")
    for path in sql_files:
        with open(path, 'r', encoding='utf-8-sig') as f:
            conn.executescript(f.read())

    # Kiểm tra các bảng bắt buộc đã được tạo chưa
    existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required = {'parking_records', 'parking_slots', 'parking_areas', 'users', 'settings',
                'price_periods', 'vehicle_types', 'prices', 'user_vehicles'}
    missing = required - existing
    if missing:
        raise RuntimeError(
            "Database thiếu bảng: " + ", ".join(sorted(missing)) + "\n"
            "Các file SQL đã đọc: " + ", ".join(os.path.basename(p) for p in sql_files) + "\n"
            "Hãy kiểm tra nội dung các file trong thư mục SQL/ (phải chứa lệnh CREATE TABLE cho các bảng trên).")

    # Migration nhẹ: nếu bảng parking_records cũ (từ bản trước) chưa có cột slot_name
    for col_sql in ("ALTER TABLE parking_records ADD COLUMN slot_name TEXT",
                    "ALTER TABLE parking_slots ADD COLUMN maintenance_reason TEXT",
                    "ALTER TABLE parking_records ADD COLUMN vehicle_type_id INTEGER",
                    "ALTER TABLE parking_records ADD COLUMN vehicle_type_name TEXT",
                    "ALTER TABLE parking_records ADD COLUMN note TEXT",
                    "ALTER TABLE user_vehicles ADD COLUMN start_on TEXT",
                    "ALTER TABLE user_vehicles ADD COLUMN months INTEGER",
                    "ALTER TABLE user_vehicles ADD COLUMN paid_amount INTEGER",
                    "ALTER TABLE users ADD COLUMN password_changes INTEGER NOT NULL DEFAULT 0",
                    "ALTER TABLE users ADD COLUMN plate_changes INTEGER NOT NULL DEFAULT 0"):
        try:
            conn.execute(col_sql)
        except sqlite3.OperationalError:
            pass  # cột đã tồn tại

    conn.commit()

    conn.execute('CREATE INDEX IF NOT EXISTS idx_record_slot_status ON parking_records(slot_name,status)')

    # Dữ liệu cũ: chưa có nhật ký thu tiền vé tháng -> lập từ các vé tháng đã đăng ký
    cur0 = conn.cursor()
    cur0.execute("SELECT COUNT(*) AS c FROM ticket_payments")
    if cur0.fetchone()['c'] == 0:
        conn.execute(
            "INSERT INTO ticket_payments (user_vehicle_id, plate_number, amount, months, paid_on, created_at) "
            "SELECT id, plate_number, paid_amount, months, COALESCE(start_on, substr(created_at, 1, 10)), created_at "
            "FROM user_vehicles WHERE ticket_type = 'month' AND paid_amount > 0")
        conn.commit()

    # Seed 18 vị trí đỗ (A01..A06, B01..B06, C01..C06) nếu bảng đang trống
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM parking_slots")
    initialized = conn.execute("SELECT 1 FROM settings WHERE key='parking_layout_initialized'").fetchone()
    if cur.fetchone()['c'] == 0 and conn.execute('SELECT COUNT(*) FROM parking_areas').fetchone()[0] == 0 and not initialized:
        rows = []
        for area in DEFAULT_AREAS:
            for i in range(1, SLOTS_PER_AREA + 1):
                rows.append((f"{area}{i:02d}", area))
        conn.executemany(
            "INSERT INTO parking_slots (slot_name, area, status) VALUES (?, ?, 'available')",
            rows
        )
    conn.execute('INSERT OR IGNORE INTO parking_areas (name) SELECT DISTINCT area FROM parking_slots')
    conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('parking_layout_initialized','1')")
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
           WHERE REPLACE(REPLACE(REPLACE(UPPER(plate_number), '-', ''), '.', ''), ' ', '') = ?
             AND status = 'IN'
           ORDER BY entry_time DESC LIMIT 1""",
        (plate_key(plate_number),)
    )
    row = cur.fetchone()
    conn.close()
    return row


def close_record(record_id: int, exit_image: str, fee: int, note: str = None):
    """Đóng lượt gửi xe. Nếu có ghi chú lúc ra thì nối thêm vào ghi chú lúc vào (nếu có)."""
    with _parking_transaction() as conn:
        record = conn.execute('SELECT * FROM parking_records WHERE id=?', (record_id,)).fetchone()
        if record is None or record['status'] != 'IN':
            raise ValueError('Lượt gửi đã được xử lý hoặc đã xóa. Hãy tải lại trang.')
        if record['slot_name']:
            slot = conn.execute('SELECT * FROM parking_slots WHERE slot_name=?', (record['slot_name'],)).fetchone()
            if slot is None:
                raise ValueError('Không tìm thấy ô đang giữ xe.')
            _slot_record(conn, slot, record_id)
        conn.execute(
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
        if record['slot_name']:
            conn.execute("UPDATE parking_slots SET status='available',plate_number=NULL WHERE slot_name=?", (record['slot_name'],))
        return record['slot_name']


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


@contextmanager
def _parking_transaction():
    conn = get_connection()
    try:
        conn.execute('BEGIN IMMEDIATE')
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def get_areas():
    return _fetch(
        "SELECT a.*, v.name AS vehicle_type_name FROM parking_areas a "
        "LEFT JOIN vehicle_types v ON v.id = a.vehicle_type_id ORDER BY a.id")


def save_area(area_id, name, vehicle_type_id=None, slot_count=0):
    name = (name or '').strip()
    if not name or len(name) > 60 or any(ord(c) < 32 for c in name):
        raise ValueError('Tên khu phải có từ 1 đến 60 ký tự.')
    with _parking_transaction() as conn:
        if vehicle_type_id is not None and not conn.execute('SELECT id FROM vehicle_types WHERE id=?', (vehicle_type_id,)).fetchone():
            raise ValueError('Loại xe không hợp lệ.')
        if conn.execute('SELECT id FROM parking_areas WHERE name=? COLLATE NOCASE AND id != ?',
                        (name, area_id or 0)).fetchone():
            raise ValueError('Tên khu đã tồn tại.')
        if area_id:
            area = conn.execute('SELECT * FROM parking_areas WHERE id=?', (area_id,)).fetchone()
            if area is None:
                raise ValueError('Không tìm thấy khu.')
            if vehicle_type_id is not None:
                occupied = conn.execute("SELECT * FROM parking_slots WHERE area=? AND status='occupied'", (area['name'],)).fetchall()
                for slot in occupied:
                    record = _slot_record(conn, slot)
                    if record['vehicle_type_id'] != vehicle_type_id:
                        raise ValueError('Khu còn xe thuộc loại khác. Hãy xử lý các xe đó trước khi đổi phân khu.')
            conn.execute('UPDATE parking_areas SET name=?, vehicle_type_id=? WHERE id=?', (name, vehicle_type_id, area_id))
            conn.execute('UPDATE parking_slots SET area=? WHERE area=?', (name, area['name']))
            return area_id
        if not isinstance(slot_count, int) or not 0 <= slot_count <= 1000:
            raise ValueError('Số lượng ô phải là số nguyên từ 1 đến 1000.')
        new_id = conn.execute('INSERT INTO parking_areas (name,vehicle_type_id) VALUES (?,?)', (name, vehicle_type_id)).lastrowid
        import re
        import unicodedata
        ascii_name = unicodedata.normalize('NFKD', name.replace('đ', 'D').replace('Đ', 'D')).encode('ascii', 'ignore').decode().upper()
        prefix = re.sub(r'[^A-Z0-9_-]', '', ascii_name)[:28].strip('_-') or f'K{new_id}'
        names = [f'{prefix}{i:02d}' for i in range(1, slot_count + 1)]
        existing = {r[0] for r in conn.execute('SELECT slot_name FROM parking_slots')}
        duplicate = next((n for n in names if n in existing), None)
        if duplicate:
            raise ValueError(f'Tên ô {duplicate} đã tồn tại. Hãy chọn tên khu khác.')
        conn.executemany("INSERT INTO parking_slots(slot_name,area,status) VALUES (?,?,'available')", [(n, name) for n in names])
        return new_id


def delete_area(area_id):
    with _parking_transaction() as conn:
        area = conn.execute('SELECT * FROM parking_areas WHERE id=?', (area_id,)).fetchone()
        if area is None:
            raise ValueError('Không tìm thấy khu.')
        occupied = conn.execute("SELECT 1 FROM parking_slots s WHERE s.area=? AND (s.status='occupied' OR "
                                "EXISTS (SELECT 1 FROM parking_records r WHERE r.slot_name=s.slot_name AND r.status='IN'))",
                                (area['name'],)).fetchone()
        if occupied:
            raise ValueError('Khu còn xe đang gửi. Hãy xử lý xe trước khi xóa khu.')
        conn.execute('DELETE FROM parking_slots WHERE area=?', (area['name'],))
        conn.execute('DELETE FROM parking_areas WHERE id=?', (area_id,))


def rename_slot(slot_name, new_name, expected_status, expected_record_id, actor):
    import re
    new_name = (new_name or '').strip().upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9_-]{0,31}', new_name):
        raise ValueError('Tên ô gồm tối đa 32 chữ cái không dấu, số, dấu - hoặc _.')
    with _parking_transaction() as conn:
        slot = conn.execute('SELECT * FROM parking_slots WHERE slot_name=?', (slot_name,)).fetchone()
        if slot is None or slot['status'] != expected_status:
            raise ValueError('Trạng thái ô đã thay đổi. Hãy tải lại trang.')
        record = None
        if slot['status'] == 'occupied':
            if not expected_record_id:
                raise ValueError('Thiếu thông tin xe. Hãy tải lại trang.')
            record = _slot_record(conn, slot, expected_record_id)
        elif conn.execute("SELECT 1 FROM parking_records WHERE slot_name=? AND status='IN'", (slot_name,)).fetchone():
            raise ValueError('Thông tin xe và ô chưa khớp. Hãy kiểm tra dữ liệu.')
        if new_name == slot_name:
            return
        if conn.execute('SELECT 1 FROM parking_slots WHERE slot_name=?', (new_name,)).fetchone():
            raise ValueError('Tên ô đỗ đã tồn tại.')
        conn.execute('UPDATE parking_slots SET slot_name=? WHERE slot_name=?', (new_name, slot_name))
        if record:
            note = _operation_note(record['note'], actor, f'Đã đổi tên ô {slot_name} thành {new_name}')
            conn.execute('UPDATE parking_records SET slot_name=?,note=? WHERE id=?', (new_name, note, record['id']))


def add_slot(area_id, slot_name):
    import re
    slot_name = (slot_name or '').strip().upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9_-]{0,31}', slot_name):
        raise ValueError('Tên ô gồm tối đa 32 chữ cái không dấu, số, dấu - hoặc _.')
    with _parking_transaction() as conn:
        area = conn.execute('SELECT * FROM parking_areas WHERE id=?', (area_id,)).fetchone()
        if area is None:
            raise ValueError('Không tìm thấy khu.')
        if conn.execute('SELECT 1 FROM parking_slots WHERE slot_name=?', (slot_name,)).fetchone():
            raise ValueError('Tên ô đỗ đã tồn tại.')
        conn.execute("INSERT INTO parking_slots(slot_name,area,status) VALUES (?,?,'available')", (slot_name, area['name']))
    return slot_name


def delete_slot(slot_name):
    with _parking_transaction() as conn:
        slot = conn.execute('SELECT * FROM parking_slots WHERE slot_name=?', (slot_name,)).fetchone()
        if slot is None:
            raise ValueError('Không tìm thấy ô đỗ.')
        if slot['status'] == 'occupied' or conn.execute("SELECT 1 FROM parking_records WHERE slot_name=? AND status='IN'", (slot_name,)).fetchone():
            raise ValueError('Ô còn xe đang gửi, không thể xóa ô.')
        conn.execute('DELETE FROM parking_slots WHERE slot_name=?', (slot_name,))


def get_available_slots_by_area(vehicle_type_id=None):
    areas = get_areas()
    result = {a['name']: [] for a in areas}
    for row in get_all_slots():
        if row['status'] == 'available' and row['record_id'] is None and (vehicle_type_id is None or
                row['allowed_vehicle_type_id'] is None or row['allowed_vehicle_type_id'] == vehicle_type_id):
            result.setdefault(row['area'], []).append(row)
    return result


def is_slot_available(slot_name, vehicle_type_id=None):
    rows = [s for s in get_all_slots() if s['slot_name'] == slot_name]
    return bool(rows and rows[0]['status'] == 'available' and rows[0]['record_id'] is None and
                (vehicle_type_id is None or rows[0]['allowed_vehicle_type_id'] is None or
                 rows[0]['allowed_vehicle_type_id'] == vehicle_type_id))


def get_all_slots():
    return _fetch(
        "SELECT s.*, a.id AS area_id, a.vehicle_type_id AS allowed_vehicle_type_id, "
        "(SELECT r.id FROM parking_records r WHERE r.slot_name=s.slot_name AND r.status='IN' "
        "ORDER BY r.id DESC LIMIT 1) AS record_id "
        "FROM parking_slots s JOIN parking_areas a ON a.name=s.area ORDER BY a.id,s.slot_name")


def find_free_slot(area=None, vehicle_type_id=None):
    for area_name, slots in get_available_slots_by_area(vehicle_type_id).items():
        if slots and (area is None or area_name == area):
            return slots[0]['slot_name']
    return None


def occupy_slot(slot_name, plate_number):
    with _parking_transaction() as conn:
        changed = conn.execute(
            "UPDATE parking_slots SET status='occupied',plate_number=?,maintenance_reason=NULL "
            "WHERE slot_name=? AND status='available'", (plate_number, slot_name))
        if changed.rowcount != 1:
            raise ValueError('Ô đỗ không còn trống.')


def free_slot(slot_name):
    if slot_name:
        _exec("UPDATE parking_slots SET status='available',plate_number=NULL,maintenance_reason=NULL WHERE slot_name=?", (slot_name,))


def set_slot_maintenance(slot_name, in_maintenance, reason='', expected_status=None):
    reason = (reason or '').strip()
    if in_maintenance and (not reason or len(reason) > 500):
        raise ValueError('Vui lòng nhập lý do bảo trì, tối đa 500 ký tự.')
    with _parking_transaction() as conn:
        slot = conn.execute('SELECT * FROM parking_slots WHERE slot_name=?', (slot_name,)).fetchone()
        if slot is None:
            raise ValueError('Không tìm thấy ô đỗ.')
        if slot['status'] == 'occupied' or conn.execute("SELECT 1 FROM parking_records WHERE slot_name=? AND status='IN'", (slot_name,)).fetchone():
            raise ValueError('Ô đang có xe, không thể bảo trì.')
        if expected_status and slot['status'] != expected_status:
            raise ValueError('Trạng thái ô đã thay đổi. Hãy tải lại trang.')
        conn.execute('UPDATE parking_slots SET status=?,plate_number=NULL,maintenance_reason=? WHERE slot_name=?',
                     ('maintenance' if in_maintenance else 'available', reason if in_maintenance else None, slot_name))


def _slot_record(conn, slot, expected_record_id=None):
    rows = conn.execute("SELECT * FROM parking_records WHERE slot_name=? AND status='IN'", (slot['slot_name'],)).fetchall()
    if (slot['status'] != 'occupied' or len(rows) != 1 or
            plate_key(rows[0]['plate_number']) != plate_key(slot['plate_number'])):
        raise ValueError('Thông tin xe trong ô đã thay đổi hoặc không khớp lịch sử. Hãy tải lại trang.')
    record = rows[0]
    if expected_record_id is not None and record['id'] != expected_record_id:
        raise ValueError('Xe trong ô đã thay đổi. Hãy tải lại trang trước khi thao tác.')
    return record


def _operation_note(previous, actor, text):
    stamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    item = f'[{stamp}] {actor}: {text}'
    return (previous + ' | ' if previous else '') + item


def move_parked_vehicle(source_name, target_name, expected_record_id, actor):
    with _parking_transaction() as conn:
        source = conn.execute('SELECT * FROM parking_slots WHERE slot_name=?', (source_name,)).fetchone()
        target = conn.execute('SELECT * FROM parking_slots WHERE slot_name=?', (target_name,)).fetchone()
        if source is None or target is None:
            raise ValueError('Không tìm thấy ô nguồn hoặc ô đích.')
        record = _slot_record(conn, source, expected_record_id)
        if source_name == target_name or source['area'] != target['area']:
            raise ValueError('Chỉ được chuyển sang ô khác trong cùng khu.')
        if target['status'] != 'available' or conn.execute("SELECT 1 FROM parking_records WHERE slot_name=? AND status='IN'", (target_name,)).fetchone():
            raise ValueError('Ô đích không còn trống.')
        allowed = conn.execute('SELECT vehicle_type_id FROM parking_areas WHERE name=?', (target['area'],)).fetchone()
        if allowed['vehicle_type_id'] is not None and allowed['vehicle_type_id'] != record['vehicle_type_id']:
            raise ValueError('Loại xe không phù hợp với khu.')
        note = _operation_note(record['note'], actor,
                               f"Đã di chuyển xe từ ô {source_name} sang ô {target_name} (khu {source['area']})")
        conn.execute("UPDATE parking_slots SET status='available',plate_number=NULL WHERE slot_name=?", (source_name,))
        conn.execute("UPDATE parking_slots SET status='occupied',plate_number=?,maintenance_reason=NULL WHERE slot_name=?",
                     (record['plate_number'], target_name))
        conn.execute('UPDATE parking_records SET slot_name=?,note=? WHERE id=?', (target_name, note, record['id']))


def remove_parked_vehicle(slot_name, expected_record_id, reason, actor):
    reason = (reason or '').strip()
    if not reason or len(reason) > 500:
        raise ValueError('Vui lòng nhập lý do xóa xe, tối đa 500 ký tự.')
    with _parking_transaction() as conn:
        slot = conn.execute('SELECT * FROM parking_slots WHERE slot_name=?', (slot_name,)).fetchone()
        if slot is None:
            raise ValueError('Không tìm thấy ô đỗ.')
        record = _slot_record(conn, slot, expected_record_id)
        note = _operation_note(record['note'], actor, f'Đã xóa xe khỏi ô {slot_name} — Lý do: {reason}')
        conn.execute("UPDATE parking_records SET status='DELETED',exit_time=?,fee=NULL,note=? WHERE id=?",
                     (datetime.now().isoformat(timespec='seconds'), note, record['id']))
        conn.execute("UPDATE parking_slots SET status='available',plate_number=NULL,maintenance_reason=NULL WHERE slot_name=?", (slot_name,))


def create_parking_entry(plate, image, slot_name, vehicle_type_id, vehicle_type_name, note=None):
    with _parking_transaction() as conn:
        if not conn.execute('SELECT id FROM vehicle_types WHERE id=?', (vehicle_type_id,)).fetchone():
            raise ValueError('Loại xe đã bị thay đổi hoặc xóa. Hãy tải lại trang.')
        duplicate = conn.execute(
            "SELECT 1 FROM parking_records WHERE status='IN' AND "
            "REPLACE(REPLACE(REPLACE(UPPER(plate_number),'-',''),'.',''),' ','')=?", (plate_key(plate),)).fetchone()
        if duplicate:
            raise ValueError('Xe này đang gửi trong bãi.')
        sql = ("SELECT s.* FROM parking_slots s JOIN parking_areas a ON a.name=s.area "
               "WHERE s.status='available' AND (a.vehicle_type_id IS NULL OR a.vehicle_type_id=?) "
               "AND NOT EXISTS (SELECT 1 FROM parking_records r WHERE r.slot_name=s.slot_name AND r.status='IN') ")
        params = [vehicle_type_id]
        if slot_name:
            sql += 'AND s.slot_name=? '
            params.append(slot_name)
        slot = conn.execute(sql + 'ORDER BY a.id,s.slot_name LIMIT 1', params).fetchone()
        if slot is None:
            raise ValueError('Không còn ô trống phù hợp với loại xe đã chọn.')
        cur = conn.execute(
            "INSERT INTO parking_records(plate_number,entry_time,entry_image,slot_name,vehicle_type_id,vehicle_type_name,note,status) "
            "VALUES (?,?,?,?,?,?,?,'IN')",
            (plate, datetime.now().isoformat(timespec='seconds'), image, slot['slot_name'], vehicle_type_id, vehicle_type_name, note or None))
        conn.execute("UPDATE parking_slots SET status='occupied',plate_number=?,maintenance_reason=NULL WHERE slot_name=?",
                     (plate, slot['slot_name']))
        return cur.lastrowid, slot['slot_name']


def slot_counts():
    counts = {'available': 0, 'occupied': 0, 'maintenance': 0}
    for row in _fetch('SELECT status,COUNT(*) AS c FROM parking_slots GROUP BY status'):
        counts[row['status']] = row['c']
    counts['total'] = sum(counts.values())
    return counts


def area_stats():
    result = {}
    for row in _fetch('SELECT a.name AS area,s.status,COUNT(s.slot_name) AS c FROM parking_areas a '
                      'LEFT JOIN parking_slots s ON s.area=a.name GROUP BY a.id,s.status ORDER BY a.id'):
        data = result.setdefault(row['area'], dict(total=0, occupied=0, available=0, maintenance=0))
        if row['status']:
            data[row['status']] = row['c']
            data['total'] += row['c']
    for data in result.values():
        data['percent'] = round(data['occupied'] / data['total'] * 100, 1) if data['total'] else 0
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


def add_user(username: str, fullname: str, password: str, role: str) -> int:
    """Thêm tài khoản, trả về id của tài khoản mới."""
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO users (username, fullname, password, role, status) VALUES (?, ?, ?, ?, 'active')",
        (username, fullname, password, role)
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id


def update_user(user_id: int, fullname: str, role: str):
    conn = get_connection()
    conn.execute("UPDATE users SET fullname = ?, role = ? WHERE id = ?", (fullname, role, user_id))
    conn.commit()
    conn.close()


def set_user_password(user_id: int, new_password: str):
    conn = get_connection()
    conn.execute("UPDATE users SET password = ? WHERE id = ?", (new_password, user_id))
    conn.commit()
    conn.close()


def change_own_password(user_id: int, new_password: str):
    """Người dùng tự đổi mật khẩu: lưu mật khẩu mới và tăng bộ đếm số lần đổi."""
    conn = get_connection()
    conn.execute("UPDATE users SET password = ?, password_changes = password_changes + 1 WHERE id = ?",
                 (new_password, user_id))
    conn.commit()
    conn.close()


def change_vehicle_plate(vehicle_id: int, user_id: int, plate_number: str, key: str):
    """Người dùng tự đổi biển số xe đã đăng ký: cập nhật biển số và tăng bộ đếm số lần đổi."""
    conn = get_connection()
    conn.execute("UPDATE user_vehicles SET plate_number = ?, plate_key = ? WHERE id = ? AND user_id = ?",
                 (plate_number, key, vehicle_id, user_id))
    conn.execute("UPDATE users SET plate_changes = plate_changes + 1 WHERE id = ?", (user_id,))
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
    conn.execute("DELETE FROM user_vehicles WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


# ============================================================
# XE & VÉ ĐĂNG KÝ CỦA NGƯỜI DÙNG
# ============================================================

def get_user_vehicles(user_id: int):
    conn = get_connection()
    rows = conn.execute(
        """SELECT v.*, t.name AS vehicle_type_name
           FROM user_vehicles v LEFT JOIN vehicle_types t ON t.id = v.vehicle_type_id
           WHERE v.user_id = ? ORDER BY v.id""", (user_id,)).fetchall()
    conn.close()
    return rows


def get_vehicles_grouped():
    """{user_id: [xe, ...]} cho toàn bộ tài khoản (dùng ở trang danh sách)."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT v.*, t.name AS vehicle_type_name
           FROM user_vehicles v LEFT JOIN vehicle_types t ON t.id = v.vehicle_type_id
           ORDER BY v.id""").fetchall()
    conn.close()
    grouped = {}
    for r in rows:
        grouped.setdefault(r['user_id'], []).append(r)
    return grouped


def find_vehicle_owner(key: str):
    """Tài khoản đang đăng ký biển số này (theo plate_key), hoặc None."""
    conn = get_connection()
    row = conn.execute(
        """SELECT u.id, u.username, u.fullname FROM user_vehicles v
           JOIN users u ON u.id = v.user_id WHERE v.plate_key = ?""", (key,)).fetchone()
    conn.close()
    return row


def add_user_vehicle(user_id: int, plate_number: str, key: str, vehicle_type_id,
                     ticket_type: str, expires_on, start_on=None, months=None, paid_amount=None):
    conn = get_connection()
    now = datetime.now()
    cur = conn.execute(
        """INSERT INTO user_vehicles
           (user_id, plate_number, plate_key, vehicle_type_id, ticket_type, expires_on,
            start_on, months, paid_amount, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, plate_number, key, vehicle_type_id, ticket_type, expires_on,
         start_on, months, paid_amount, now.isoformat(timespec='seconds')))
    if ticket_type == 'month' and paid_amount:
        conn.execute(
            "INSERT INTO ticket_payments (user_vehicle_id, plate_number, amount, months, paid_on, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cur.lastrowid, plate_number, paid_amount, months,
             now.strftime('%Y-%m-%d'), now.isoformat(timespec='seconds')))
    conn.commit()
    conn.close()


def add_ticket_payment(vehicle_id: int, plate_number: str, amount: int, months: int):
    """Ghi nhận 1 lần thu tiền vé tháng (thuê thêm tháng) vào doanh thu."""
    now = datetime.now()
    conn = get_connection()
    conn.execute(
        "INSERT INTO ticket_payments (user_vehicle_id, plate_number, amount, months, paid_on, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (vehicle_id, plate_number, amount, months,
         now.strftime('%Y-%m-%d'), now.isoformat(timespec='seconds')))
    conn.commit()
    conn.close()


def set_vehicle_month_ticket(vehicle_id: int, start_on: str, expires_on: str, months: int, paid_amount: int):
    """Đặt/gia hạn vé tháng cho xe đã đăng ký."""
    conn = get_connection()
    conn.execute(
        """UPDATE user_vehicles SET ticket_type='month', start_on=?, expires_on=?, months=?, paid_amount=?
           WHERE id=?""", (start_on, expires_on, months, paid_amount, vehicle_id))
    conn.commit()
    conn.close()


def get_registered_vehicle(key: str):
    """Xe đã đăng ký theo biển số (plate_key) kèm thông tin chủ tài khoản + loại xe, hoặc None."""
    conn = get_connection()
    row = conn.execute(
        """SELECT v.*, u.username, u.fullname, t.name AS vehicle_type_name
           FROM user_vehicles v
           JOIN users u ON u.id = v.user_id
           LEFT JOIN vehicle_types t ON t.id = v.vehicle_type_id
           WHERE v.plate_key = ?""", (key,)).fetchone()
    conn.close()
    return row


def get_registered_plates():
    """Toàn bộ biển số đã đăng ký (dùng để gợi ý khi OCR đọc lệch 1 ký tự)."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT v.plate_key, v.plate_number, u.username
           FROM user_vehicles v JOIN users u ON u.id = v.user_id""").fetchall()
    conn.close()
    return rows


def get_user_vehicle(vehicle_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM user_vehicles WHERE id = ?", (vehicle_id,)).fetchone()
    conn.close()
    return row


def delete_user_vehicle(vehicle_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM user_vehicles WHERE id = ?", (vehicle_id,))
    conn.commit()
    conn.close()


# ============================================================
# THỐNG KÊ
# ============================================================

def get_records_between(start_date: str, end_date: str):
    """Toàn bộ lượt xe có mặt (vào hoặc ra) trong khoảng ngày [start_date, end_date].
    Cùng công thức với câu đếm period_records trong get_statistics() để số liệu khớp nhau."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT * FROM parking_records
           WHERE substr(entry_time, 1, 10) BETWEEN ?1 AND ?2
              OR (status IN ('OUT','DELETED') AND substr(exit_time, 1, 10) BETWEEN ?1 AND ?2)
           ORDER BY entry_time DESC""",
        (start_date, end_date)
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_statistics(start_date: str = None, end_date: str = None):
    """Thống kê doanh thu & lượt xe.
    - Tổng doanh thu: toàn thời gian = phí gửi xe (xe đã ra) + tiền vé tháng đã thu.
    - Các số theo kỳ: tính cho khoảng ngày [start_date, end_date] (YYYY-MM-DD, gồm cả 2 đầu);
      mặc định là hôm nay."""
    today_str = datetime.now().strftime('%Y-%m-%d')
    start_date = start_date or today_str
    end_date = end_date or start_date

    conn = get_connection()
    cur = conn.cursor()

    def one(sql, params=()):
        cur.execute(sql, params)
        return cur.fetchone()[0]

    # ----- Toàn thời gian -----
    parking_revenue = one("SELECT COALESCE(SUM(fee), 0) FROM parking_records WHERE status = 'OUT'")
    month_revenue = one("SELECT COALESCE(SUM(amount), 0) FROM ticket_payments")

    # ----- Theo kỳ -----
    period_entries = one(
        "SELECT COUNT(*) FROM parking_records WHERE substr(entry_time, 1, 10) BETWEEN ? AND ?",
        (start_date, end_date))
    period_exits = one(
        "SELECT COUNT(*) FROM parking_records WHERE status = 'OUT' "
        "AND substr(exit_time, 1, 10) BETWEEN ? AND ?", (start_date, end_date))
    # Tổng lượt xe: lượt có xe vào HOẶC xe ra trong kỳ (mỗi lượt đếm 1 lần)
    period_records = one(
        "SELECT COUNT(*) FROM parking_records WHERE substr(entry_time, 1, 10) BETWEEN ?1 AND ?2 "
        "OR (status IN ('OUT','DELETED') AND substr(exit_time, 1, 10) BETWEEN ?1 AND ?2)", (start_date, end_date))
    period_parking_revenue = one(
        "SELECT COALESCE(SUM(fee), 0) FROM parking_records WHERE status = 'OUT' "
        "AND substr(exit_time, 1, 10) BETWEEN ? AND ?", (start_date, end_date))
    period_month_revenue = one(
        "SELECT COALESCE(SUM(amount), 0) FROM ticket_payments WHERE paid_on BETWEEN ? AND ?",
        (start_date, end_date))

    conn.close()

    return {
        'total_revenue': parking_revenue + month_revenue,
        'parking_revenue': parking_revenue,
        'month_revenue': month_revenue,
        'period_entries': period_entries,
        'period_exits': period_exits,
        'period_records': period_records,
        'period_revenue': period_parking_revenue + period_month_revenue,
        'period_parking_revenue': period_parking_revenue,
        'period_month_revenue': period_month_revenue,
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


def find_month_price(vehicle_type_id, on_date):
    """Giá vé THÁNG (1 tháng) của loại xe trong Bảng giá.
    Ưu tiên khung 'theo ngày' chứa ngày `on_date.day`; nếu không có thì lấy giá tháng đầu tiên của loại xe.
    Trả về dict {amount, period_name} hoặc None nếu bảng giá chưa có giá tháng cho loại xe."""
    if not vehicle_type_id:
        return None
    rows = _fetch(
        "SELECT p.amount, t.name AS period_name, t.start_value, t.end_value "
        "FROM prices p JOIN price_periods t ON t.id = p.period_id "
        "WHERE p.vehicle_type_id = ? AND p.ticket_type = 'month' ORDER BY t.id", (vehicle_type_id,))
    if not rows:
        return None
    for r in rows:
        try:
            if int(r['start_value']) <= on_date.day <= int(r['end_value']):
                return {'amount': r['amount'], 'period_name': r['period_name']}
        except ValueError:
            pass
    return {'amount': rows[0]['amount'], 'period_name': rows[0]['period_name']}


# ----- Tra giá theo loại xe + khung thời gian -----

def _hhmm_to_minutes(value: str) -> int:
    h, m = value.split(':')
    return int(h) * 60 + int(m)


def _minute_in_range(minute: int, start: int, end: int) -> bool:
    """Khoảng [start, end] tính cả hai đầu; nếu start > end thì là khoảng qua nửa đêm (vd 22:00-03:00)."""
    if start <= end:
        return start <= minute <= end
    return minute >= start or minute <= end


def get_turn_prices(vehicle_type_id):
    """All time-window turn prices in the same priority order used at entry."""
    if not vehicle_type_id:
        return []
    return _fetch(
        "SELECT t.id AS period_id, p.amount, t.name AS period_name, "
        "t.start_value AS start, t.end_value AS end "
        "FROM prices p JOIN price_periods t ON t.id = p.period_id "
        "WHERE p.vehicle_type_id = ? AND p.ticket_type = 'turn' AND t.kind = 'time' "
        "ORDER BY t.id", (vehicle_type_id,))


def find_turn_price(vehicle_type_id: int, when: datetime):
    """Tìm giá vé LƯỢT của loại xe tại thời điểm `when` (so khớp theo phút, bỏ qua giây).
    Trả về dict {amount, period_name, start, end} hoặc None nếu chưa có giá phù hợp.
    Nếu nhiều khung chồng lên nhau thì lấy khung được tạo trước."""
    if not vehicle_type_id:
        return None
    minute = when.hour * 60 + when.minute
    rows = get_turn_prices(vehicle_type_id)
    for r in rows:
        if _minute_in_range(minute, _hhmm_to_minutes(r['start']), _hhmm_to_minutes(r['end'])):
            return {'amount': r['amount'], 'period_name': r['period_name'],
                    'start': r['start'], 'end': r['end']}
    return None
