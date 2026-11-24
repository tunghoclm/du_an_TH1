-- Chatbot nội bộ: dữ liệu biên soạn và các phiên bản mô hình đã huấn luyện.
CREATE TABLE IF NOT EXISTS support_ai_knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    questions TEXT NOT NULL,
    answer TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    updated_at TEXT NOT NULL,
    updated_by INTEGER
);
CREATE TABLE IF NOT EXISTS support_ai_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trained_at TEXT NOT NULL,
    trained_by INTEGER,
    revision INTEGER NOT NULL,
    document_count INTEGER NOT NULL,
    sample_count INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS support_ai_state (
    id INTEGER PRIMARY KEY CHECK(id=1),
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    threshold REAL NOT NULL,
    fallback TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    active_model INTEGER
);
