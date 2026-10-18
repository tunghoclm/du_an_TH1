# 🅿️ Demo: Bãi đỗ xe thông minh (Smart Parking System)

Dự án demo hệ thống bãi đỗ xe thông minh, nhận diện biển số xe tự động bằng
**YOLOv8 (dò vùng biển số) + OpenCV + EasyOCR** (đọc ký tự), quản lý xe
vào/ra và tính phí bằng **Python (Flask)**, lưu dữ liệu bằng **SQLite (SQL)**,
giao diện web bằng **HTML/CSS**.

> **Dò vùng biển số — YOLOv8 hay contour?** Hệ thống dùng **YOLOv8** (model
> `cache/yolo/plate_yolov8n.pt`) để tìm vùng biển số trong ảnh, chính xác hơn
> cách dò cạnh contour với ảnh thực tế (nhiều chi tiết, nhiều xe...). Nếu **chưa
> có model YOLO** (chưa tải được, hoặc máy không cài `ultralytics`), hệ thống
> **tự động quay về** cách dò contour cũ — không báo lỗi. Đặt biến môi trường
> `PLATE_DETECTOR=contour` nếu muốn tắt hẳn YOLO để so sánh kết quả.

> **Vì sao đổi từ Tesseract sang EasyOCR?** Tesseract-OCR được huấn luyện cho
> văn bản in tài liệu, nên đọc biển số xe (font đặc thù, ảnh nghiêng, ánh sáng
> không đều) thường ra kết quả sai/rối. EasyOCR dùng mô hình deep learning
> (CRAFT + CRNN), chịu được ảnh thực tế tốt hơn nhiều — và vẫn hoàn toàn miễn
> phí, mã nguồn mở, cài bằng `pip` mà không cần cài thêm phần mềm hệ thống.
>
> **Luồng nhận diện** (`py/plate_recognition.py`, `py/plate_yolo.py`, `py/plate_preprocess.py`):
> ảnh → **YOLOv8** dò vùng biển số (bounding box) → OpenCV **cắt vùng biển** (nới rộng
> thêm 15% để không cắt cụt ký tự ở mép) → **tăng tương phản (CLAHE khi cần)** →
> chuẩn hoá kích thước → **EasyOCR** đọc chữ/số → ghép/đặt dấu `-`.
>
> **Deskew (xoay thẳng) mặc định TẮT.** Đã thử nghiệm: EasyOCR vốn đọc tốt biển bị
> nghiêng, trong khi xoay/warp phối cảnh lại làm biến dạng biển xe máy 2 dòng và đọc
> **sai** — nên pipeline chỉ **tăng tương phản**. Muốn bật lại deskew (để thử) thì đặt
> biến môi trường `PLATE_DESKEW=1`.

## 1. Cấu trúc dự án

```
smart_parking/
├── app.py                     # Flask server (routes chính)
├── setup.bat / setup.sh       # Cài đặt 1 lần (venv, thư viện, model OCR, database)
├── run.bat / run.sh           # Chạy ứng dụng hằng ngày
├── requirements.txt
├── cache/                     # File sinh ra sau khi chạy setup
│   ├── venv/                  #   môi trường ảo Python
│   ├── easyocr_models/        #   model EasyOCR đã tải
│   ├── yolo/                  #   model YOLOv8 dò biển số (tùy chọn)
│   ├── parking.db             #   database SQLite
│   └── tmp/                   #   ảnh tạm giữa bước Nhận diện và Xác nhận
├── py/                        # Các file Python
│   ├── config.py              #   đường dẫn dùng chung
│   ├── database.py            #   Thao tác SQLite
│   ├── export_stats.py        #   Xuất báo cáo Thống kê ra Excel (.xlsx) / PDF
│   ├── plate_yolo.py          #   Dò vùng biển số bằng YOLOv8 (tùy chọn)
│   ├── plate_preprocess.py    #   Tăng tương phản (+ xoay thẳng tùy chọn) vùng biển số
│   ├── plate_recognition.py   #   OCR biển số (YOLOv8/OpenCV + EasyOCR)
│   ├── plate_api.py
│   ├── plate_utils.py
│   ├── download_yolo_model.py #   Tải model YOLOv8 về cache/yolo/
│   └── generate_sample_plate.py  # Tạo ảnh biển số mẫu để test
├── SQL/
│   └── schema.sql             # Cấu trúc bảng dữ liệu
├── assets/
│   └── fonts/                 # font DejaVu Sans (kèm giấy phép) để xuất báo cáo PDF tiếng Việt
├── templates/
│   ├── html/                  # Các file HTML (Flask templates)
│   └── css/                   # Các file CSS (phục vụ qua route /css/<file>)
└── static/
    ├── in/                    # Ảnh khi xe đi vào
    └── out/                   # Ảnh khi xe đi ra
```

## 2. Cài đặt (CHỈ LÀM 1 LẦN DUY NHẤT)

Không cần cài thêm phần mềm OCR hệ thống nào — EasyOCR thuần Python. Có script
tự động lo hết mọi bước (tạo venv, cài thư viện, tải sẵn model EasyOCR, khởi
tạo database) — bạn chỉ cần chạy:

**macOS / Linux:**
```bash
cd smart_parking
chmod +x setup.sh run.sh   # (nếu cần cấp quyền thực thi)
./setup.sh
```

**Windows:**
```
cd smart_parking
setup.bat
```

Script sẽ:
1. Tạo virtual environment (`cache/venv/`)
2. Cài toàn bộ thư viện trong `requirements.txt` (gồm `ultralytics`/YOLOv8 — khá nặng)
3. **Tải sẵn model EasyOCR** (bước tốn thời gian nhất, cần Internet — chỉ tải 1 lần)
4. **Tải model YOLOv8** dò biển số về `cache/yolo/` (tùy chọn; lỗi mạng thì bỏ qua,
   ứng dụng vẫn chạy bằng cách dò contour)
5. Khởi tạo file database `cache/parking.db` từ các file `.sql` trong `SQL/`

> Sau bước này, máy đã sẵn sàng chạy offline (trừ khi bạn xoá venv hoặc model).

## 3. Chạy ứng dụng (MỌI LẦN SAU CHỈ CẦN LỆNH NÀY)

**macOS / Linux:**
```bash
./run.sh
```

**Windows:**
```
run.bat
```

Script `run.sh` / `run.bat` tự động kích hoạt venv và chạy `python app.py` —
bạn không cần nhớ lệnh `source venv/bin/activate` nữa.

(Nếu muốn chạy thủ công: kích hoạt venv rồi `python app.py` như bình thường.)

Mở trình duyệt tại: **http://localhost:5000**

## 4. Cách sử dụng

Tài khoản demo mặc định (đăng nhập tại `/login`):

| Tên đăng nhập | Mật khẩu | Vai trò          |
|---------------|----------|-------------------|
| `admin`       | `123456` | Quản trị viên (thấy cả trang Người dùng) |
| `nhanvien01`  | `123456` | Nhân viên          |

| Trang          | Chức năng                                                                 |
|----------------|-----------------------------------------------------------------------------|
| `/login`       | Đăng nhập hệ thống                                                          |
| `/`            | Menu chính — số liệu nhanh + lối vào các chức năng                          |
| `/parking`     | Sơ đồ bãi đỗ theo khu A/B/C (60 vị trí) — tự động cập nhật khi xe vào/ra qua OCR; có thể bấm vị trí trống để đưa vào/ra khỏi bảo trì |
| `/gate`        | **Xe vào / ra (1 trang)** — chọn ảnh → *Nhận diện biển số* (xem ảnh có khung đánh dấu) → *Xác nhận*. Biển số chưa có trong bãi = xe **vào** (chọn loại xe, gán vị trí); biển số đang gửi = xe **ra** (tính phí, trả vị trí). Có ô ghi chú và cho sửa biển số nếu nhận diện sai |
| `/entry`, `/exit` | Đường dẫn cũ, tự chuyển sang `/gate` |
| `/history`     | Lịch sử toàn bộ lượt gửi xe, có bộ lọc theo biển số / trạng thái / ngày      |
| `/statistics`  | Thống kê tổng lượt xe, doanh thu, tỉ lệ lấp đầy bãi đỗ; **xuất báo cáo Excel / PDF** |
| `/users`       | Quản lý tài khoản (chỉ admin thấy) — thêm, khóa/mở khóa, xóa người dùng      |
| `/pricing`     | Bảng giá xe — 3 bảng: **khung thời gian** (tự đặt giờ/ngày bắt đầu–kết thúc), **loại xe** (tự tạo tên), **giá theo loại xe + thời gian** (lượt/tháng). Ai cũng xem, admin/nhân viên thêm-sửa-xóa |
| `/settings`    | Cài đặt cá nhân (ai đăng nhập cũng dùng được) — tự chọn chế độ gửi xe: **tự động** hoặc **tự chọn vị trí** |

**Phân quyền bảo trì vị trí đỗ:** tại trang `/parking`, chỉ tài khoản **admin** và
**nhân viên (manager)** mới bấm được vào ô trống để đưa vào/ra khỏi bảo trì.
Tài khoản **user** thường chỉ xem, không chỉnh sửa được.

**Cài đặt chế độ gán vị trí (`/settings`) — riêng cho từng tài khoản, người dùng tự chọn, không cần admin/nhân viên:**
- *Tự động* — hệ thống tự chọn 1 vị trí trống bất kỳ khi có xe vào, không cần chọn tay.
- *Tự chọn* (mặc định) — người dùng tự chọn vị trí cụ thể theo khu A/B/C khi ghi nhận xe vào.

**Cách tính phí:** khi xe vào bắt buộc chọn **loại xe**; khi xe ra, hệ thống lấy **giá vé Lượt** của loại xe
tương ứng với **khung giờ lúc xe vào** trong trang `/pricing` (1 lượt, không tính theo số giờ). Nếu loại xe chưa có giá
ở khung giờ hiện tại thì trang `/gate` không cho nhận xe vào và báo cần bổ sung giá. Giá vé *Tháng* chỉ để tham khảo, chưa áp dụng tự động.
Với xe cũ chưa có loại xe (hoặc giá đã bị xóa), hệ thống dùng đơn giá dự phòng 5.000 VNĐ / giờ (biến `FEE_PER_HOUR` trong `app.py`).

**Nếu bãi đỗ hết chỗ** (60/60 vị trí đều occupied/maintenance), trang `/gate` sẽ báo lỗi
"Bãi đỗ đã hết chỗ trống" và không ghi nhận xe vào.

**Xuất báo cáo (Excel / PDF):** tại trang `/statistics`, cạnh bộ lọc thời gian có 2 nút **⬇ Excel** và
**⬇ PDF** — xuất đúng kỳ đang xem (hôm nay, hôm qua, 7/30 ngày hoặc khoảng ngày tự chọn).
Mỗi file gồm 3 phần: *Tổng quan* (doanh thu, lượt vào/ra), *Tình trạng theo khu vực* và *Chi tiết lượt xe* trong kỳ.
- **Excel** (`.xlsx`, thư viện `openpyxl`): 3 sheet cùng tên với 3 phần trên, có dòng tiêu đề, bật lọc và cố định dòng đầu.
- **PDF** (`.pdf`, thư viện `reportlab`): khổ A4 ngang, tự ngắt trang khi có nhiều lượt xe.
- Quyền xuất giống quyền xem trang Thống kê: chỉ **admin** và **nhân viên**.
- PDF dùng font **DejaVu Sans đi kèm sẵn trong dự án** (`assets/fonts/`) nên hiển thị đúng tiếng Việt
  trên mọi máy, **không cần cài thêm hay cấu hình gì**. Nếu muốn dùng font khác, đặt biến môi trường
  `REPORT_FONT` (và `REPORT_FONT_BOLD`) trỏ tới file `.ttf`.

## 5. Test nhanh không cần ảnh xe thật

Dùng script có sẵn để tạo ảnh biển số giả lập:

```bash
python py/generate_sample_plate.py "51F-123.45" test_plate.jpg
```

Sau đó tải file `test_plate.jpg` lên ở trang `/gate` (xe vào), rồi tải lại đúng ảnh đó
lần nữa (xe ra) để thử luồng tính phí hoàn chỉnh.

## 6. Ghi chú kỹ thuật

- **Phát hiện vùng biển số**: ưu tiên **YOLOv8** (`py/plate_yolo.py`) — model 1 lớp
  `license_plate` tải sẵn về `cache/yolo/plate_yolov8n.pt`, dò vùng biển số chính xác
  hơn với ảnh thực tế. Nếu có nhiều biển, chọn khung tin cậy cao nhất. Khi YOLO không
  đọc ra kết quả đủ tốt (hoặc chưa có model), hệ thống **quay về** cách cũ: Canny edge
  detection + tìm contour 4 cạnh lớn nhất. Hai cách chạy song song và **chọn kết quả
  tốt hơn**: đúng cấu trúc biển số VN trước (biển 2 dòng bắt buộc đúng dạng xe máy
  `29-L131332`), rồi biển đủ dài, rồi độ tin cậy cao hơn. Tắt YOLO bằng
  `PLATE_DETECTOR=contour`.
  Có thể đổi model khác qua biến môi trường `PLATE_YOLO_MODEL` (đường dẫn file `.pt`),
  chỉnh ngưỡng tin cậy bằng `PLATE_YOLO_CONF` (mặc định 0.25).
- **Cắt vùng biển + tiền xử lý** (`py/plate_recognition.py`, `py/plate_preprocess.py`):
  khung biển do YOLO/contour trả về thường khoét sát biển nên dễ **cắt cụt ký tự ở mép**
  (nhất là số `0` đứng đầu dòng dưới của biển xe máy 2 dòng) — vì vậy ảnh được **nới rộng
  thêm 15%** mỗi phía trước khi đọc. Sau đó **khử nhiễu nhẹ** và chỉ **tăng tương phản
  CLAHE** khi ảnh thiếu tương phản (tránh kéo tương phản mạnh làm OCR đọc nhầm 1 ký tự).
  Ảnh còn được **chuẩn hoá kích thước** (cạnh dài ≤ 1000px, phóng to tối đa x2) — vừa tăng
  độ chính xác vừa tránh EasyOCR chạy rất chậm trên ảnh lớn.
  > **Deskew (xoay thẳng) mặc định tắt** (`plate_preprocess.straighten`): thử nghiệm cho
  > thấy xoay/warp phối cảnh làm biến dạng biển 2 dòng và đọc sai, trong khi EasyOCR vốn
  > đọc tốt biển nghiêng. Bật lại bằng `PLATE_DESKEW=1` nếu muốn thử.
- **Làm sạch text OCR**: loại bỏ ký tự không phải chữ/số, chuyển về chữ hoa.
- **OCR engine**: dùng EasyOCR với `allowlist` giới hạn chỉ chữ cái/số thường
  gặp trên biển số, giúp giảm nhiễu so với để engine đoán tự do. Có cơ chế
  fallback: nếu vùng cắt đọc ra **chưa đúng cấu trúc biển số** (đọc nhầm ký tự,
  quá ngắn hoặc độ tin cậy thấp) thì đọc thêm **trên toàn ảnh gốc**, rồi chọn
  ứng viên **đúng cấu trúc** VN nhất — nhờ đó vùng cắt đọc sai
  (vd `29LT-31332`) không còn thắng kết quả đúng đọc được từ toàn ảnh
  (`29-L131332`) chỉ vì điểm tin cậy cao hơn.
- **Nếu vẫn cần chính xác hơn nữa** (dùng cho ảnh biển số Việt Nam thực tế,
  nhiều xe/góc chụp khó):
  - **Huấn luyện lại YOLOv8 trên biển số Việt Nam**: bộ dữ liệu có sẵn trên
    Roboflow/Kaggle; model tự train thay cho `cache/yolo/plate_yolov8n.pt` sẽ
    dò vùng biển số VN chính xác hơn nhiều (model mặc định được train trên biển số
    nước ngoài nên đôi khi bỏ sót biển nhỏ/ảnh cận cảnh).
  - **PaddleOCR** thay EasyOCR để đọc ký tự — độ chính xác rất cao, nhiều dự án
    ANPR Việt Nam dùng, nhưng cài đặt nặng hơn.
- **Đối chiếu xe ra**: so khớp chính xác chuỗi biển số đã làm sạch. Trong thực
  tế nên thêm thuật toán so khớp gần đúng (fuzzy matching) để xử lý sai số OCR.

## 7. Hướng phát triển thêm (nếu mở rộng)

- Tích hợp camera trực tiếp (OpenCV `VideoCapture`) thay vì upload ảnh thủ công.
- Thêm xác thực người dùng (nhân viên trông xe) và phân quyền.
- Dùng mô hình OCR chuyên biển số (ví dụ EasyOCR, hoặc model huấn luyện riêng)
  để tăng độ chính xác với biển số Việt Nam.
- Thêm thanh toán không tiền mặt (QR code, ví điện tử).

## Quản lý tài khoản (trang Người dùng)

| Chức năng | Admin | Nhân viên | Người dùng |
|---|:-:|:-:|:-:|
| Xem trang Người dùng | ✅ (tất cả tài khoản) | ✅ (chỉ tài khoản người dùng) | ❌ |
| Tạo tài khoản người dùng | ✅ | ✅ | ❌ |
| Tạo tài khoản nhân viên | ✅ | ❌ | ❌ |
| Sửa họ tên / đăng ký xe & vé | ✅ | ✅ (chỉ người dùng) | ❌ |
| Đổi vai trò, đổi mật khẩu, khóa, xóa | ✅ | ❌ | ❌ |

- Khi tạo (hoặc sửa) tài khoản người dùng có thể **đăng ký xe**: chọn ảnh để **nhận diện biển số** hoặc **nhập tay**, chọn loại xe và loại vé (**Vé lượt** / **Vé tháng** kèm ngày hết hạn). Có thể đăng ký nhiều xe; mỗi biển số chỉ thuộc một tài khoản.
- Dữ liệu xe lưu ở bảng `user_vehicles` (`SQL/schema.sql`), tự tạo khi chạy ứng dụng.
