"""YOLO + EasyOCR, with bounded live/accurate profiles and optional cloud fallback.

Clear plate rows bypass CRAFT. Uncertain uploads try geometric and lighting
alternatives. Coordinates stay in the original image; shared models are locked.
"""
from collections import Counter, namedtuple
import logging
import os
import threading
import time

import cv2
import easyocr
import torch

import plate_api
import plate_preprocess
import plate_yolo
from config import EASYOCR_DIR
from plate_utils import plate_key, assemble_plate, normalize_plate, fix_ocr_plate, is_valid_plate_format

_Cand = namedtuple('_Cand', 'text conf img rect rows engine', defaults=['easyocr'])
_INFERENCE_LOCK = threading.RLock()
_gpu = os.environ.get('PLATE_GPU', 'auto').strip().lower()
_reader = easyocr.Reader(['en'], gpu=torch.cuda.is_available() if _gpu == 'auto' else _gpu in ('1', 'true', 'yes'),
                         model_storage_directory=EASYOCR_DIR, user_network_directory=EASYOCR_DIR)
PLATE_ALLOWLIST = 'ABCDEFGHKLMNPRSTUVXYZ0123456789-.'
PAD_FRAC = 0.15
MAX_OCR_SIDE = 640
LOG = logging.getLogger(__name__)


def clean_plate_text(text):
    return plate_key(text)


def group_rows(results):
    items = []
    for bbox, text, conf in results:
        xs, ys = [p[0] for p in bbox], [p[1] for p in bbox]
        items.append(dict(text=text, x=min(xs), y=sum(ys) / len(ys), h=max(ys) - min(ys)))
    if not items:
        return []
    items.sort(key=lambda it: it['y'])
    gap = 0.6 * sorted(it['h'] for it in items)[len(items) // 2]
    groups = [[items[0]]]
    for it in items[1:]:
        if abs(it['y'] - sum(c['y'] for c in groups[-1]) / len(groups[-1])) <= gap:
            groups[-1].append(it)
        else:
            groups.append([it])
    return [' '.join(c['text'] for c in sorted(row, key=lambda c: c['x'])) for row in groups]


def _ocr_result(results):
    if not results:
        return '', 0.0, []
    rows = group_rows(results)
    weights = [max(1, len(plate_key(r[1]))) for r in results]
    confidence = sum(float(r[2]) * n for r, n in zip(results, weights)) / sum(weights)
    return assemble_plate(rows), confidence, rows


def ocr_read(image, allowlist=PLATE_ALLOWLIST):
    return _ocr_result(_reader.readtext(image, detail=1, allowlist=allowlist,
                                       canvas_size=1280, workers=0, decoder='greedy'))


def _expand_rect(rect, frac, shape):
    x, y, w, h = rect
    height, width = shape[:2]
    x0, y0 = max(0, int(x - frac * w)), max(0, int(y - frac * h))
    x1, y1 = min(width, int(x + w + frac * w)), min(height, int(y + h + frac * h))
    return x0, y0, max(0, x1 - x0), max(0, y1 - y0)


def crop_plate(img, rect):
    if rect is None:
        return img
    x, y, w, h = _expand_rect(rect, PAD_FRAC, img.shape)
    crop = img[y:y + h, x:x + w]
    return crop if crop.size else img


def _resize(crop, max_side):
    scale = min(3.0, max_side / max(crop.shape[:2]))
    if abs(scale - 1) < 0.02:
        return crop
    return cv2.resize(crop, None, fx=scale, fy=scale,
                      interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)


def _valid(c):
    return is_valid_plate_format(c.text, len(c.rows))


def _score(text, confidence, rows=()):
    return (is_valid_plate_format(text, len(rows)), confidence, min(len(plate_key(text)), 9))


def _best(candidates):
    votes = Counter(plate_key(c.text) for c in candidates if _valid(c) and c.conf >= 0.45)
    return max(candidates, key=lambda c: (_valid(c), votes[plate_key(c.text)] >= 2,
                                         c.conf, min(len(plate_key(c.text)), 9)))


def _read_crop(crop, rect, fast=False, direct=True, engine='easyocr'):
    image = _resize(crop, 480 if fast else MAX_OCR_SIDE)
    if direct and rect is not None:
        boxes = plate_preprocess.text_rows(image)
        if boxes:
            result = _ocr_result(_reader.recognize(image, horizontal_list=boxes, free_list=[],
                                                  allowlist=PLATE_ALLOWLIST, detail=1, workers=0))
            cand = _Cand(*result[:2], image, rect, result[2], 'easyocr-rows')
            if _valid(cand) and cand.conf >= 0.85:
                return cand
    text, conf, rows = ocr_read(image)
    return _Cand(text, conf, image, rect, rows, engine)


def _use_yolo():
    return os.environ.get('PLATE_DETECTOR', 'auto').lower() != 'contour' and plate_yolo.is_available()


def find_plate_contour(edged):
    contours, _ = cv2.findContours(edged, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:30]:
        quad = cv2.approxPolyDP(contour, 0.025 * cv2.arcLength(contour, True), True)
        x, y, w, h = cv2.boundingRect(quad)
        if (len(quad) == 4 and cv2.isContourConvex(quad) and w >= 40 and h >= 15
                and 1.1 <= w / h <= 6.5 and cv2.contourArea(quad) >= 0.45 * w * h):
            return quad
    return None


def _contour_rect(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 40, 160)
    contour = find_plate_contour(edges)
    return cv2.boundingRect(contour) if contour is not None else None


def _recognize_api(img, image_path, fast=False):
    if not plate_api.is_enabled() or (fast and os.environ.get('PLATE_API_CAMERA', '0') != '1'):
        return None
    try:
        raw, rect, score = plate_api.recognize(image_path, min_interval=3 if fast else 0)
    except plate_api.ApiUnavailable:
        return None
    except Exception as error:
        LOG.warning('Plate API unavailable; using local OCR (%s)', type(error).__name__)
        return None
    plate = fix_ocr_plate(normalize_plate(raw))
    if not is_valid_plate_format(plate) or score < plate_api.min_score():
        return None
    if rect:
        rect = _expand_rect(rect, 0, img.shape)
        if rect[2] < 1 or rect[3] < 1:
            rect = None
    return _Cand(plate, float(score), crop_plate(img, rect), rect, [raw], 'plate-recognizer')


def _local(img, fast=False):
    # Detect on a bounded copy; OCR the original crop, preserving 4K detail.
    ratio = min(1.0, (1280 if fast else 1920) / max(img.shape[:2]))
    detection = cv2.resize(img, None, fx=ratio, fy=ratio) if ratio < 1 else img
    yolo = _use_yolo()
    rect = plate_yolo.detect_best(detection) if yolo else None
    if rect is None:
        rect = _contour_rect(detection)
    if rect is not None and ratio < 1:
        rect = tuple(int(round(v / ratio)) for v in rect)
    if fast and rect is None and yolo:
        return _Cand('', 0.0, detection, None, [], 'easyocr')
    if rect is None:
        image = _resize(img, 960 if fast else 1280)
        text, conf, rows = ocr_read(image)
        return _Cand(text, conf, image, None, rows, 'easyocr')

    crop = crop_plate(img, rect)
    original = _read_crop(plate_preprocess.enhance(crop), rect, fast)
    if _valid(original) and original.conf >= (0.75 if fast else 0.85):
        return original
    candidates = [original]
    # Some plate detectors return just the digits of one row. A cheap border
    # fallback recovers the full plate before any expensive lighting retries.
    if yolo and not _valid(original):
        border = _contour_rect(detection)
        if border is not None:
            border = tuple(int(round(v / ratio)) for v in border) if ratio < 1 else border
            if border != rect:
                cand = _read_crop(plate_preprocess.enhance(crop_plate(img, border)), border, fast)
                candidates.append(cand)
                if _valid(cand) and cand.conf >= 0.85:
                    return cand
    corrected = plate_preprocess.rectify_detected(img, rect)
    if corrected is not None:
        recovered, recovered_rect = corrected
        cand = _read_crop(plate_preprocess.enhance(recovered), recovered_rect, fast, engine='easyocr-perspective')
        candidates.append(cand)
        if _valid(cand) and cand.conf >= 0.85:
            return cand
    # Small live retry budget: the next frame often improves focus.
    for index, (name, variant) in enumerate(plate_preprocess.recovery_variants(_resize(crop, MAX_OCR_SIDE))):
        if fast and index >= 1:
            break
        cand = _read_crop(variant, rect, fast, engine='easyocr-' + name)
        candidates.append(cand)
        winner = _best(candidates)
        if _valid(winner) and (winner.conf >= 0.90 or
                              sum(plate_key(c.text) == plate_key(winner.text) and c.conf >= 0.55
                                  for c in candidates) >= 2):
            return winner
    winner = _best(candidates)
    if not fast and not _valid(winner):
        image = _resize(img, 1280)
        text, conf, rows = ocr_read(image)
        candidates.append(_Cand(text, conf, image, rect, rows, 'easyocr-full'))
    return _best(candidates)


def _run(image_path, fast=False):
    started = time.perf_counter()
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError('Cannot read image')
    mode = os.environ.get('PLATE_API_MODE', 'fallback').strip().lower()
    with _INFERENCE_LOCK:
        result = _recognize_api(img, image_path, fast) if mode == 'first' else None
        if result is None:
            result = _local(img, fast)
            if mode not in ('off', 'first') and (not _valid(result) or result.conf < 0.80):
                remote = _recognize_api(img, image_path, fast)
                if remote is not None:
                    result = remote
    return result, img, round((time.perf_counter() - started) * 1000)


def _recognize(image_path):
    result, img, _ = _run(image_path)
    return result.text, result.img, result.rect, img


def recognize_plate(image_path):
    plate, crop, _, _ = _recognize(image_path)
    return plate, crop


def recognize_plate_annotated(image_path, max_width=900):
    plate, _, rect, img = _recognize(image_path)
    return plate, _annotate_plate(img, plate, rect, max_width)


def recognize_plate_live(image_path, max_width=900, *, details=False):
    result, img, elapsed = _run(image_path, fast=True)
    height, width = img.shape[:2]
    values = (result.text, _annotate_plate(img, result.text, result.rect, max_width), result.rect, width, height)
    if details:
        return (*values, dict(confidence=round(result.conf, 3), engine=result.engine, elapsed_ms=elapsed))
    return values


def _annotate_plate(img, plate_text, rect, max_width=900):
    out = img.copy()
    height, width = out.shape[:2]
    scale = max(1.0, width / 600)
    thickness = max(2, round(2 * scale))
    if rect is not None:
        x, y, w, h = rect
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 200, 0), thickness)
        ty = y - int(8 * scale)
        if ty < 20 * scale:
            ty = y + h + int(24 * scale)
        position = (x, min(ty, height - 5))
    else:
        position = (10, int(30 * scale))
    if plate_text:
        cv2.putText(out, plate_text, position, cv2.FONT_HERSHEY_SIMPLEX,
                    0.7 * scale, (0, 255, 255), thickness)
    if width > max_width:
        out = cv2.resize(out, (max_width, int(height * max_width / width)), interpolation=cv2.INTER_AREA)
    return out
