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
 2. DÒ VÙNG BIỂN SỐ, ưu tiên theo thứ tự:
      a. YOLOv8 (nếu có model — xem plate_yolo.py): chính xác hơn với ảnh thực tế
      b. Dò cạnh (Canny) -> tìm contour hình chữ nhật: cách dự phòng, không cần model
    Kết quả nào cho biển số rõ hơn (đủ dài, tin cậy cao) sẽ được chọn.
 3. Cắt vùng biển số -> NỚI RỘNG một chút (PAD_FRAC) để không cắt cụt ký tự ở mép -> TĂNG
    TƯƠNG PHẢN (plate_preprocess.py) -> chuẩn hoá kích thước (MAX_OCR_SIDE)
 4. Đưa vào EasyOCR để đọc ký tự (giới hạn bảng ký tự = chữ+số biển số)
 5. Gom các ô chữ thành từng dòng, ghép lại và đặt dấu '-' đúng chỗ (vd 61T3-2222, 51F-12345)
 6. Nếu vùng cắt đọc ra CHƯA đúng cấu trúc biển số (đọc nhầm ký tự / cắt sai vùng)
    -> đọc thêm TOÀN ẢNH gốc rồi chọn ứng viên ĐÚNG cấu trúc biển số VN nhất

Bật/tắt YOLO bằng biến môi trường PLATE_DETECTOR:
     auto (mặc định) / yolo   -> dùng YOLO nếu có model, tự quay về contour khi cần
     contour                  -> tắt YOLO, chỉ dùng cách dò contour cũ

Bật xoay thẳng (deskew) bằng PLATE_DESKEW=1 (mặc định tắt): EasyOCR vốn đọc tốt biển nghiêng,
mà xoay/warp lại dễ làm biến dạng biển 2 dòng (xe máy) nên mặc định không dùng.
"""

import os
import re
import cv2
import easyocr
from collections import namedtuple

import plate_api
import plate_yolo
import plate_preprocess
from config import EASYOCR_DIR
from plate_utils import plate_key, assemble_plate, normalize_plate, fix_ocr_plate, is_valid_plate_format

# Một ứng viên kết quả OCR: text (chuỗi biển đã định dạng), conf (điểm tin cậy 0-1),
# img (ảnh vùng biển đã qua xử lý), rect (x,y,w,h vùng biển trên ảnh gốc), rows (các dòng OCR đọc được)
_Cand = namedtuple('_Cand', 'text conf img rect rows')

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

# Cạnh dài tối đa (px) của ảnh đưa vào EasyOCR. EasyOCR rất chậm trên ảnh lớn, mà biển số to
# hơn mức này cũng không giúp đọc chính xác hơn -> chuẩn hoá kích thước cho vừa nhanh vừa đúng.
MAX_OCR_SIDE = 1000

# Nới rộng vùng biển số (theo tỉ lệ cạnh) trước khi đọc: khung YOLO/contour thường khoét SÁT
# biển nên dễ cắt cụt ký tự ở mép (nhất là số 0 đứng đầu dòng dưới của biển xe máy 2 dòng).
# Nới ra một chút giữ được đủ ký tự -> đọc chính xác hơn nhiều.
PAD_FRAC = 0.15

# Xoay thẳng (deskew) mặc định TẮT: EasyOCR vốn đọc tốt biển nghiêng, mà xoay/warp phối cảnh
# lại làm biến dạng biển 2 dòng khiến đọc sai. Bật lại bằng biến môi trường PLATE_DESKEW=1.
DESKEW = os.environ.get('PLATE_DESKEW', '0').strip().lower() in ('1', 'true', 'yes', 'on')


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
    """Chạy EasyOCR trên 1 ảnh.
    Trả về (biển_số_đã_định_dạng, điểm_tin_cậy_trung_bình_0-1, danh_sách_dòng_ocr)."""
    results = _reader.readtext(image, detail=1, allowlist=allowlist)
    if not results:
        return '', 0.0, []
    confidences = [r[2] for r in results]
    avg_conf = sum(confidences) / len(confidences)
    rows = group_rows(results)
    return assemble_plate(rows), avg_conf, rows


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


def _expand_rect(rect, frac, shape):
    """Nới rộng rect=(x,y,w,h) ra mỗi phía `frac` lần cạnh (kẹp trong ảnh), trả về rect mới."""
    x, y, w, h = rect
    H, W = shape[:2]
    x0 = max(0, int(x - frac * w))
    y0 = max(0, int(y - frac * h))
    x1 = min(W, int(x + w + frac * w))
    y1 = min(H, int(y + h + frac * h))
    return x0, y0, x1 - x0, y1 - y0


def _read_region(img, rect):
    """Cắt vùng biển số (rect=(x,y,w,h), hoặc None = đọc cả ảnh) -> NỚI RỘNG một chút để không
    cắt cụt ký tự -> tăng tương phản -> chuẩn hoá kích thước -> EasyOCR.
    Trả về (text, conf, ảnh_vùng_đã_xử_lý, danh_sách_dòng_ocr)."""
    if rect is not None:
        x, y, w, h = _expand_rect(rect, PAD_FRAC, img.shape)
        crop = img[y:y + h, x:x + w]
        if crop.size == 0:
            crop = img
        # Biển đã cắt ra -> tăng tương phản cho dễ đọc. Deskew (xoay thẳng) mặc định tắt vì
        # thử nghiệm cho thấy nó làm biến dạng biển 2 dòng; bật bằng PLATE_DESKEW=1.
        crop = plate_preprocess.prepare(crop) if DESKEW else plate_preprocess.enhance(crop)
    else:
        crop = img   # toàn ảnh gốc: giữ nguyên (không biết đâu là biển để xử lý)
    # Đưa vùng cắt về kích thước thuận lợi cho EasyOCR: biển nhỏ thì phóng to (tối đa x2),
    # biển/ảnh lớn thì thu nhỏ bớt — vừa tăng độ chính xác vừa tránh OCR chậm trên ảnh lớn.
    long_side = max(crop.shape[:2])
    scale = min(2.0, MAX_OCR_SIDE / long_side)
    big = cv2.resize(crop, None, fx=scale, fy=scale,
                     interpolation=cv2.INTER_CUBIC if scale >= 1 else cv2.INTER_AREA)
    text, conf, rows = ocr_read(big)
    return text, conf, big, rows


def _score(text, confidence, rows=()):
    """Điểm xếp hạng kết quả OCR (max là tốt nhất), theo thứ tự ưu tiên:
    1) ĐÚNG cấu trúc biển số VN với số dòng OCR đã đọc (xem plate_utils.is_valid_plate_format)
    2) đủ dài (>=5 ký tự)  3) dài hơn  4) tin cậy cao hơn.
    Cấu trúc phải đứng TRƯỚC độ tin cậy: vùng cắt dễ bị EasyOCR đọc nhầm (vd '29-L1' thành
    '29-LT') nhưng điểm tin cậy vẫn cao, trong khi đọc TOÀN ẢNH lại ra đúng biển với điểm thấp hơn."""
    n = len(plate_key(text))
    return (is_valid_plate_format(text, len(rows)), n >= 5, n, confidence)


def _use_yolo() -> bool:
    """YOLO có được phép dùng không (theo cấu hình) và có model hay không."""
    if os.environ.get('PLATE_DETECTOR', 'auto').strip().lower() == 'contour':
        return False
    return plate_yolo.is_available()


def _detect_and_read(img, edged):
    """Dò vùng biển số (YOLO trước, contour sau) + đọc ký tự, chọn kết quả tốt nhất.
    Nếu cách dò đang cho biển số CHƯA đúng cấu trúc (đọc nhầm ký tự / cắt sai vùng) thì thử tiếp
    cách dò khác, kể cả đọc TOÀN ẢNH gốc, rồi mới chấm điểm so sánh.
    Trả về (text, ảnh_vùng_biển, rect)."""
    cands = []

    def _read(rect):
        text, conf, big, rows = _read_region(img, rect)
        return _Cand(text, conf, big, rect, rows)

    def _enough(c):
        # Đọc được biển đủ dài, tin cậy và ĐÚNG cấu trúc -> không cần thử cách khác (tiết kiệm thời gian)
        return (c.conf >= 0.4 and len(plate_key(c.text)) >= 5
                and is_valid_plate_format(c.text, len(c.rows)))

    # 1) YOLOv8 (nếu có model — chính xác hơn với ảnh thực tế)
    if _use_yolo():
        box = plate_yolo.detect_best(img)
        if box:
            c = _read(box)
            if _enough(c):
                return c.text, c.img, c.rect
            cands.append(c)

    # 2) Dò contour (Canny) — cách cũ, luôn thử để so sánh
    contour = find_plate_contour(edged)
    c = _read(_contour_rect(contour))
    if _enough(c):
        return c.text, c.img, c.rect
    cands.append(c)

    # 3) Vùng cắt vẫn chưa đúng cấu trúc -> đọc thêm TOÀN ẢNH gốc để có thêm ứng viên so sánh
    #    (bỏ qua nếu contour không tìm được vùng riêng thì `_read(None)` bên trên đã đọc cả ảnh rồi)
    if c.rect is not None:
        cands.append(_read(None))

    best = max(cands, key=lambda c: _score(c.text, c.conf, c.rows))
    # Nếu ứng viên thắng là ảnh toàn cảnh (không có rect) thì vẫn giữ khung vùng biển đã dò được
    # để hiển thị cho người dùng thấy biển số nằm ở đâu.
    rect = best.rect if best.rect is not None else next(
        (cc.rect for cc in cands if cc.rect is not None), None)
    return best.text, best.img, rect


def _recognize(image_path: str):
    """Chạy toàn bộ quy trình, trả về (biển số, ảnh vùng biển số, rect (x,y,w,h) hoặc None, ảnh gốc)."""
    img, gray, edged = preprocess_image(image_path)

    via_api = _recognize_api(img, image_path)
    if via_api is not None:
        plate, crop, rect = via_api
        return plate, crop, rect, img

    plate_text, plate_img_big, rect = _detect_and_read(img, edged)
    return plate_text, plate_img_big, rect, img


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
