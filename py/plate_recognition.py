"""
plate_recognition.py
Module nhận diện biển số xe bằng OpenCV (xử lý ảnh, tìm vùng biển số)
kết hợp với EasyOCR (deep learning) để đọc ký tự.

Vì sao dùng EasyOCR thay vì Tesseract-OCR?
 - Tesseract được huấn luyện chủ yếu cho văn bản in tài liệu (sách, giấy tờ),
   nên với biển số xe (font đặc thù, ảnh nghiêng, ánh sáng không đều,
   nền/khung viền) độ chính xác thường rất thấp nếu không tinh chỉnh nhiều.
 - EasyOCR dùng mô hình deep learning (CRAFT để detect text + CRNN để đọc),
   chịu được xoay/nghiêng, ánh sáng khác nhau tốt hơn nhiều, mà vẫn miễn phí,
   mã nguồn mở, cài đặt thuần Python (không cần cài thêm phần mềm hệ thống
   như Tesseract).

Nếu đặt biến môi trường PLATE_API_TOKEN thì thử nhận diện bằng API đám mây trước (xem plate_api.py);
API lỗi / không đọc được thì tự quay về quy trình EasyOCR bên dưới.

Quy trình:
 1. Đọc ảnh -> chuyển xám -> khử nhiễu (bilateral filter)
 2. Dò cạnh (Canny) -> tìm contour hình chữ nhật (khung biển số)
 3. Cắt vùng biển số -> phóng to
 4. Đưa vào EasyOCR để đọc ký tự (giới hạn bảng ký tự = chữ+số biển số)
 5. Gom các ô chữ thành từng dòng, ghép lại và đặt dấu '-' đúng chỗ (vd 61T3-2222, 51F-12345)
 6. Nếu đọc vùng cắt thất bại -> fallback đọc lại trên toàn ảnh gốc
"""

import re
import cv2
import easyocr

import plate_api
from config import EASYOCR_DIR
from plate_utils import plate_key, assemble_plate, normalize_plate, fix_ocr_plate

# Khởi tạo Reader MỘT LẦN DUY NHẤT ở mức module (nạp model rất tốn thời gian,
# nếu khởi tạo lại mỗi lần gọi hàm sẽ rất chậm).
# gpu=False để chạy được trên máy không có GPU/CUDA (demo). Nếu máy có GPU, đổi thành True.
_reader = easyocr.Reader(['en'], gpu=False, model_storage_directory=EASYOCR_DIR,
                         user_network_directory=EASYOCR_DIR)

# Chỉ cho phép các ký tự thường xuất hiện trên biển số (chữ cái không dấu + số).
# Có thêm '-' và '.' (dấu gạch, dấu chấm in trên biển): nếu không cho phép, OCR sẽ ép các dấu này
# thành một chữ/số khác (thường là '1', 'I', 'T') làm sai biển số. Sau khi đọc, các dấu sẽ được
# chuẩn hóa lại bằng plate_utils (đặt dấu '-' đúng chỗ giữa series và số).
PLATE_ALLOWLIST = 'ABCDEFGHKLMNPRSTUVXYZ0123456789-.'


def preprocess_image(image_path: str):
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Không đọc được ảnh: {image_path}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 11, 17, 17)
    edged = cv2.Canny(gray, 30, 200)
    return img, gray, edged


def find_plate_contour(edged):
    """Tìm contour 4 cạnh lớn nhất - giả định đó là khung biển số."""
    contours, _ = cv2.findContours(edged.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:10]

    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            return approx
    return None


def crop_plate(img, contour):
    if contour is None:
        return img  # fallback: dùng cả ảnh gốc nếu không tìm được khung
    x, y, w, h = cv2.boundingRect(contour)
    # Bỏ qua vùng quá nhỏ (khả năng không phải biển số)
    if w < 40 or h < 15:
        return img
    return img[y:y + h, x:x + w]


def clean_plate_text(text: str) -> str:
    """Chỉ giữ chữ hoa + số (không dấu '-'), dùng để đo độ dài / so khớp."""
    return plate_key(text)


def group_rows(results):
    """Gom các ô chữ EasyOCR tìm được thành từng DÒNG (trên -> dưới, trái -> phải).
    Biển xe máy có 2 dòng: dòng trên '61-T3', dòng dưới '2222'."""
    items = []
    for bbox, text, conf in results:
        ys = [p[1] for p in bbox]
        xs = [p[0] for p in bbox]
        items.append({'text': text, 'y': sum(ys) / len(ys), 'h': max(ys) - min(ys), 'x': min(xs)})
    if not items:
        return []

    items.sort(key=lambda it: it['y'])
    heights = sorted(it['h'] for it in items)
    row_gap = 0.6 * heights[len(heights) // 2]          # lệch tâm theo chiều dọc quá 60% chiều cao chữ -> dòng mới

    rows, current = [], [items[0]]
    for it in items[1:]:
        mean_y = sum(c['y'] for c in current) / len(current)
        if abs(it['y'] - mean_y) <= row_gap:
            current.append(it)
        else:
            rows.append(current)
            current = [it]
    rows.append(current)
    return [' '.join(c['text'] for c in sorted(r, key=lambda c: c['x'])) for r in rows]


def ocr_read(image, allowlist=PLATE_ALLOWLIST):
    """Chạy EasyOCR trên 1 ảnh. Trả về (biển số đã định dạng có dấu '-', điểm tin cậy trung bình 0-1)."""
    results = _reader.readtext(image, detail=1, allowlist=allowlist)
    if not results:
        return '', 0.0
    confidences = [r[2] for r in results]
    avg_conf = sum(confidences) / len(confidences)
    return assemble_plate(group_rows(results)), avg_conf


def _contour_rect(contour):
    """Contour -> (x, y, w, h), hoặc None nếu không có / quá nhỏ."""
    if contour is None:
        return None
    x, y, w, h = cv2.boundingRect(contour)
    return (x, y, w, h) if (w >= 40 and h >= 15) else None


def _recognize_api(img, image_path: str):
    """Thử nhận diện bằng API. Trả về (biển số, ảnh vùng biển, rect) hoặc None nếu không dùng được."""
    if not plate_api.is_enabled():
        return None
    try:
        raw, rect, _score = plate_api.recognize(image_path)
    except Exception as e:                       # mạng lỗi, sai token, hết hạn mức... -> dùng EasyOCR
        print(f'[plate_api] Lỗi gọi API, chuyển sang EasyOCR: {e}')
        return None
    plate = fix_ocr_plate(normalize_plate(raw))
    if len(plate_key(plate)) < 5:
        return None
    if rect and rect[2] > 0 and rect[3] > 0:
        x, y, w, h = rect
        crop = img[max(0, y):y + h, max(0, x):x + w]
        if crop.size == 0:
            crop = img
    else:
        crop = img
    return plate, crop, rect


def _recognize(image_path: str):
    """Chạy toàn bộ quy trình, trả về (biển số, ảnh vùng biển số, rect (x,y,w,h) hoặc None, ảnh gốc)."""
    img, gray, edged = preprocess_image(image_path)

    via_api = _recognize_api(img, image_path)
    if via_api is not None:
        plate, crop, rect = via_api
        return plate, crop, rect, img

    contour = find_plate_contour(edged)
    plate_img = crop_plate(img, contour)

    # Phóng to giúp EasyOCR đọc chính xác hơn với ảnh có độ phân giải thấp
    plate_img_big = cv2.resize(plate_img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    plate_text, confidence = ocr_read(plate_img_big)

    # Nếu kết quả quá ngắn hoặc độ tin cậy thấp (khả năng cắt sai vùng),
    # thử đọc lại trên toàn bộ ảnh gốc rồi chọn kết quả tốt hơn.
    if len(plate_key(plate_text)) < 5 or confidence < 0.4:
        fallback_text, confidence_full = ocr_read(img)
        if len(plate_key(fallback_text)) > len(plate_key(plate_text)) or confidence_full > confidence:
            plate_text = fallback_text

    return plate_text, plate_img_big, _contour_rect(contour), img


def recognize_plate(image_path: str):
    """
    Nhận diện biển số từ file ảnh bằng EasyOCR.
    Trả về: (chuoi_bien_so_da_lam_sach, anh_vung_bien_so_da_cat)
    """
    plate_text, plate_img_big, _, _ = _recognize(image_path)
    return plate_text, plate_img_big


def recognize_plate_annotated(image_path: str, max_width: int = 900):
    """
    Giống recognize_plate nhưng trả về ảnh GỐC có vẽ khung xanh quanh biển số và chữ biển số
    (để hiển thị xem trước trên web). Trả về: (chuoi_bien_so, anh_da_danh_dau)
    """
    plate_text, _, rect, img = _recognize(image_path)
    out = img.copy()
    h_img, w_img = out.shape[:2]
    scale = max(1.0, w_img / 600.0)          # nét vẽ dày hơn với ảnh lớn
    thickness = max(2, int(round(2 * scale)))

    if rect is not None:
        x, y, w, h = rect
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 200, 0), thickness)
        if plate_text:
            ty = y - int(8 * scale)
            if ty < int(20 * scale):          # sát mép trên -> đặt chữ bên dưới khung
                ty = y + h + int(24 * scale)
            cv2.putText(out, plate_text, (x, min(ty, h_img - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7 * scale, (0, 255, 255), thickness)
    elif plate_text:
        cv2.putText(out, plate_text, (10, int(30 * scale)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7 * scale, (0, 255, 255), thickness)

    if w_img > max_width:                     # thu nhỏ ảnh xem trước cho nhẹ
        ratio = max_width / float(w_img)
        out = cv2.resize(out, (max_width, int(h_img * ratio)), interpolation=cv2.INTER_AREA)
    return plate_text, out
