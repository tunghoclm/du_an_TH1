"""
plate_utils.py
Các hàm THUẦN PYTHON để chuẩn hóa / định dạng biển số xe Việt Nam (không cần OpenCV hay EasyOCR).

Dạng biển số chuẩn khi hiển thị và lưu:
    xe máy (series = 1 chữ + 1 số) :  <2 số tỉnh>-<series><4-5 số>   vd 29-L131332    61-T32222    29-X112345
    ô tô / series chỉ có chữ       :  <2 số tỉnh><series>-<4-5 số>   vd 51F-12345     30A-1234     29AA-12345

Khi so khớp xe vào / xe ra luôn dùng plate_key() (chỉ giữ chữ + số, bỏ dấu '-'), nên dù dấu '-'
nằm lệch chỗ hay có/không có dấu thì 2 biển số vẫn được coi là một.
"""

import re


def plate_key(text) -> str:
    """Khóa so khớp: chữ hoa + số, bỏ mọi ký tự khác. '61T3-2222' -> '61T32222'."""
    return re.sub(r'[^A-Z0-9]', '', (text or '').upper())


def _fmt(province: str, series: str, digits: str) -> str:
    """Ghép biển số theo kiểu in trên biển.
    Series 'chữ + số' (xe máy, vd L1, T3, X1) -> dấu '-' ngay sau mã tỉnh:  29-L131332
    Series chỉ có chữ (ô tô, vd F, A, AA)     -> dấu '-' trước dãy số:      51F-12345"""
    if re.fullmatch(r'[A-Z]\d', series):
        return f'{province}-{series}{digits}'
    return f'{province}{series}-{digits}'


def _format_by_rule(key: str) -> str:
    """Chưa có gợi ý nào về chỗ đặt dấu '-' -> đoán theo dạng biển số.
    Trường hợp 1 chữ + 4-5 số (vd 61T32222) mơ hồ giữa 'T3-2222' (xe máy) và 'T-32222';
    chọn dạng ô tô (series chỉ gồm chữ) — chỉ ảnh hưởng cách hiển thị, không ảnh hưởng việc so khớp."""
    m = re.fullmatch(r'(\d{2})([A-Z]{1,2})(\d{4,5})', key)
    if m:
        return _fmt(*m.groups())
    m = re.fullmatch(r'(\d{2})([A-Z]\d)(\d{4,5})', key)     # series chữ + số (xe máy), vd 29L131332
    if m:
        return _fmt(*m.groups())
    # Không khớp dạng nào (OCR đọc thừa/thiếu/sai ký tự): vẫn LUÔN chèn dấu '-' sau mã tỉnh
    # để người dùng chỉ cần sửa 1-2 ký tự, thay vì nhận về một chuỗi dính liền không dấu.
    if len(key) >= 6:
        return f'{key[:2]}-{key[2:]}'
    return key


def normalize_plate(text) -> str:
    """Chuẩn hóa chuỗi biển số (OCR hoặc người dùng gõ) về dạng có dấu '-'.
    - '29L1-31332' / '29-L1-31332' / '29-L131332' -> '29-L131332'   (xe máy: dấu '-' sau mã tỉnh)
    - '51F-12345' giữ nguyên                                        (ô tô: dấu '-' trước dãy số)
    - Không có dấu '-' -> định dạng theo quy tắc."""
    s = re.sub(r'[^A-Z0-9-]', '', (text or '').upper())
    s = re.sub(r'-+', '-', s).strip('-')
    if not s:
        return ''
    if '-' not in s:
        return _format_by_rule(s)

    parts = s.split('-')
    if len(parts) == 2 and re.fullmatch(r'\d{2}', parts[0]):
        # dấu '-' sau mã tỉnh (biển xe máy 2 dòng: '29-L1' / '31332')
        rest = parts[1]
        m = re.fullmatch(r'([A-Z]{2})(\d{4,5})', rest) or re.fullmatch(r'([A-Z]\d)(\d{4,5})', rest)
        if m:
            return _fmt(parts[0], m.group(1), m.group(2))
        return _format_by_rule(parts[0] + rest)
    # còn lại: lấy dấu '-' CUỐI CÙNG làm dấu ngăn giữa series và số
    series, digits = ''.join(parts[:-1]), parts[-1]
    m = re.fullmatch(r'(\d{2})([A-Z]\d?|[A-Z]{2})', series)
    if m and digits.isdigit():
        return _fmt(m.group(1), m.group(2), digits)
    return f'{series}-{digits}'


# Chữ hay bị OCR nhầm với số (dùng ở vị trí CHẮC CHẮN là số: mã tỉnh và dãy số cuối)
_TO_DIGIT = str.maketrans({'O': '0', 'Q': '0', 'D': '0', 'I': '1', 'L': '1', 'Z': '2', 'S': '5', 'B': '8', 'G': '6'})


def fix_ocr_plate(plate: str) -> str:
    """Sửa chữ bị nhầm thành số ở các vị trí chắc chắn là số.
        'Z9-L131332' -> '29-L131332'   (mã tỉnh luôn là 2 số)
        '29-L1313B2' -> '29-L131382'   (dãy số cuối chỉ có số)
    Không đụng vào phần series (chữ) vì series 2 chữ như 'AB', 'LD' là hợp lệ."""
    m = re.fullmatch(r'(.{2})-([A-Z])(.)(.{4,5})', plate)          # xe máy: 29-L131332
    if m:
        prov, letter, digit, tail = m.groups()
        return f'{prov.translate(_TO_DIGIT)}-{letter}{digit.translate(_TO_DIGIT)}{tail.translate(_TO_DIGIT)}'
    m = re.fullmatch(r'(.{2})([A-Z]{1,2})-(.{4,5})', plate)         # ô tô: 51F-12345
    if m:
        prov, series, tail = m.groups()
        return f'{prov.translate(_TO_DIGIT)}{series}-{tail.translate(_TO_DIGIT)}'
    return plate


def assemble_plate(rows) -> str:
    """Ghép các dòng chữ OCR đọc được trên biển (từ trên xuống dưới) thành biển số có dấu '-'.
    Biển xe máy 2 dòng: dòng trên '29-L1', dòng dưới '313.32' -> '29-L131332'."""
    cleaned = [plate_key(r) for r in rows]
    cleaned = [c for c in cleaned if c]
    if len(cleaned) >= 2:
        top, bottom = cleaned[0], ''.join(cleaned[1:])
        if re.fullmatch(r'\d{2}[A-Z0-9]{1,3}', top) and re.fullmatch(r'\d{3,5}', bottom):
            return fix_ocr_plate(_fmt(top[:2], top[2:], bottom))
        return fix_ocr_plate(normalize_plate(top + bottom))
    if len(cleaned) == 1:
        # 1 dòng: giữ lại dấu '-' mà OCR đã đọc được (nếu có) để định vị chính xác hơn
        return fix_ocr_plate(normalize_plate(rows[[plate_key(r) for r in rows].index(cleaned[0])]))
    return ''
