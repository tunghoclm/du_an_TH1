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

Quy trình:
 1. Đọc ảnh -> chuyển xám -> khử nhiễu (bilateral filter)
 2. Dò cạnh (Canny) -> tìm contour hình chữ nhật (khung biển số)
 3. Cắt vùng biển số -> phóng to
 4. Đưa vào EasyOCR để đọc ký tự (giới hạn bảng ký tự = chữ+số biển số)
 5. Làm sạch chuỗi kết quả (chỉ giữ chữ hoa + số)
 6. Nếu đọc vùng cắt thất bại -> fallback đọc lại trên toàn ảnh gốc
"""

import re
import cv2
import easyocr

# Khởi tạo Reader MỘT LẦN DUY NHẤT ở mức module (nạp model rất tốn thời gian,
# nếu khởi tạo lại mỗi lần gọi hàm sẽ rất chậm).
# gpu=False để chạy được trên máy không có GPU/CUDA (demo). Nếu máy có GPU, đổi thành True.
_reader = easyocr.Reader(['en'], gpu=False)

# Chỉ cho phép các ký tự thường xuất hiện trên biển số (chữ cái không dấu + số)
PLATE_ALLOWLIST = 'ABCDEFGHKLMNPRSTUVXYZ0123456789'


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
    text = text.upper()
    text = re.sub(r'[^A-Z0-9]', '', text)
    return text


def ocr_read(image, allowlist=PLATE_ALLOWLIST):
    """Chạy EasyOCR trên 1 ảnh, ghép các dòng text tìm được lại với nhau,
    kèm điểm tin cậy trung bình (0-1) để tiện debug/hiển thị nếu cần."""
    results = _reader.readtext(image, detail=1, allowlist=allowlist)
    if not results:
        return '', 0.0
    texts = [r[1] for r in results]
    confidences = [r[2] for r in results]
    combined_text = ''.join(texts)
    avg_conf = sum(confidences) / len(confidences)
    return combined_text, avg_conf


def recognize_plate(image_path: str):
    """
    Nhận diện biển số từ file ảnh bằng EasyOCR.
    Trả về: (chuoi_bien_so_da_lam_sach, anh_vung_bien_so_da_cat)
    """
    img, gray, edged = preprocess_image(image_path)
    contour = find_plate_contour(edged)
    plate_img = crop_plate(img, contour)

    # Phóng to giúp EasyOCR đọc chính xác hơn với ảnh có độ phân giải thấp
    plate_img_big = cv2.resize(plate_img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    raw_text, confidence = ocr_read(plate_img_big)
    plate_text = clean_plate_text(raw_text)

    # Nếu kết quả quá ngắn hoặc độ tin cậy thấp (khả năng cắt sai vùng),
    # thử đọc lại trên toàn bộ ảnh gốc rồi chọn kết quả tốt hơn.
    if len(plate_text) < 5 or confidence < 0.4:
        raw_text_full, confidence_full = ocr_read(img)
        fallback_text = clean_plate_text(raw_text_full)
        if len(fallback_text) > len(plate_text) or confidence_full > confidence:
            plate_text = fallback_text

    return plate_text, plate_img_big
