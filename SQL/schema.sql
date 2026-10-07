-- schema.sql
-- Cơ sở dữ liệu cho hệ thống Bãi đỗ xe thông minh (bản ghép đầy đủ chức năng)

-- Bảng lịch sử xe vào/ra
CREATE TABLE IF NOT EXISTS parking_records (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_number  TEXT NOT NULL,              -- Biển số xe (đã làm sạch, viết hoa)
    slot_name     TEXT,                       -- Vị trí đỗ được gán (vd: A01)
    vehicle_type_id   INTEGER,                -- Loại xe lúc gửi (tham chiếu vehicle_types)
    vehicle_type_name TEXT,                   -- Tên loại xe lúc gửi (lưu lại để không mất khi đổi/xóa loại)
    note              TEXT,                   -- Ghi chú của người nhận xe (vào/ra)
    entry_time    DATETIME NOT NULL,          -- Thời điểm xe vào
    exit_time     DATETIME,                   -- Thời điểm xe ra (NULL nếu còn trong bãi)
    entry_image   TEXT,                       -- Tên file ảnh chụp lúc vào
    exit_image    TEXT,                       -- Tên file ảnh chụp lúc ra
    fee           INTEGER,                    -- Phí gửi xe (VNĐ)
    status        TEXT NOT NULL DEFAULT 'IN'  -- 'IN' = đang gửi, 'OUT' = đã lấy xe
);

CREATE INDEX IF NOT EXISTS idx_plate_status ON parking_records (plate_number, status);

-- Bảng vị trí đỗ xe (sơ đồ bãi đỗ theo khu A/B/C)
CREATE TABLE IF NOT EXISTS parking_slots (
    slot_name     TEXT PRIMARY KEY,           -- vd: A01, B12, C05
    area          TEXT NOT NULL,              -- A, B, C
    status        TEXT NOT NULL DEFAULT 'available', -- available | occupied | maintenance
    plate_number  TEXT                        -- biển số đang đỗ tại vị trí này (nếu occupied)
);

-- Bảng cài đặt hệ thống (key-value)
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
-- Bảng người dùng hệ thống (đăng nhập, phân quyền)
CREATE TABLE IF NOT EXISTS users (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username  TEXT UNIQUE NOT NULL,
    fullname  TEXT NOT NULL,
    password  TEXT NOT NULL,                  -- demo: lưu dạng plain text, thực tế nên hash
    role      TEXT NOT NULL DEFAULT 'user',   -- admin | manager | user
    status    TEXT NOT NULL DEFAULT 'active', -- active | locked
    password_changes INTEGER NOT NULL DEFAULT 0, -- số lần người dùng tự đổi mật khẩu (tối đa 3)
    plate_changes    INTEGER NOT NULL DEFAULT 0  -- số lần người dùng tự đổi biển số (tối đa 3)
);

-- Bảng cấu hình hệ thống (key-value), dùng cho trang Cài đặt
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ===== Bảng giá xe =====

-- Khung thời gian (vd: Sáng 05:00-12:59, hoặc Tháng: ngày 01-30)
CREATE TABLE IF NOT EXISTS price_periods (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'time',   -- time = theo giờ (HH:MM) | day = theo ngày trong tháng (1-31)
    start_value TEXT NOT NULL,                  -- '05:00' hoặc '01'
    end_value   TEXT NOT NULL                   -- '12:59' hoặc '30'
);

-- Loại xe (người dùng tự tạo: Xe máy, Ô tô, Xe đạp điện, ...)
CREATE TABLE IF NOT EXISTS vehicle_types (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT UNIQUE NOT NULL
);

-- Giá theo (loại xe + khung thời gian)
CREATE TABLE IF NOT EXISTS prices (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_type_id  INTEGER NOT NULL,
    period_id        INTEGER NOT NULL,
    amount           INTEGER NOT NULL,          -- VNĐ
    ticket_type      TEXT NOT NULL DEFAULT 'turn',  -- turn = Lượt | month = Tháng
    UNIQUE (vehicle_type_id, period_id)
);


-- ===== Xe & vé đăng ký theo tài khoản người dùng =====
CREATE TABLE IF NOT EXISTS user_vehicles (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL,
    plate_number     TEXT NOT NULL,                 -- biển số hiển thị, vd 51F-123.45
    plate_key        TEXT UNIQUE NOT NULL,          -- biển số chỉ chữ + số (so khớp), mỗi biển số chỉ đăng ký 1 tài khoản
    vehicle_type_id  INTEGER,
    ticket_type      TEXT NOT NULL DEFAULT 'turn',  -- turn = Vé lượt | month = Vé tháng
    expires_on       TEXT,                          -- YYYY-MM-DD (chỉ dùng cho vé tháng)
    start_on         TEXT,                          -- ngày bắt đầu vé tháng (ngày tạo/đăng ký)
    months           INTEGER,                       -- số tháng đã thuê
    paid_amount      INTEGER,                       -- tổng tiền vé tháng (giá tháng x số tháng)
    created_at       TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

-- Nhật ký thu tiền vé tháng (mỗi lần tạo tài khoản có vé tháng / thuê thêm tháng = 1 dòng).
-- Giữ nguyên khi hủy xe hoặc xóa tài khoản để doanh thu không bị mất.
CREATE TABLE IF NOT EXISTS ticket_payments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_vehicle_id  INTEGER,
    plate_number     TEXT,
    amount           INTEGER NOT NULL,
    months           INTEGER,
    paid_on          TEXT NOT NULL,                 -- YYYY-MM-DD (ngày thu tiền)
    created_at       TEXT NOT NULL
);
