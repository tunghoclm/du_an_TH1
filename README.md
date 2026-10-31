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
> thêm 15% để giữ ký tự ở mép) → **tăng tương phản (CLAHE khi cần)** →
> chuẩn hoá kích thước → **EasyOCR** đọc chữ/số → ghép/đặt dấu `-`.
>
> **Hai chế độ xử lý:** camera ưu tiên độ trễ thấp, đọc trực tiếp các dòng chữ
> khi phân đoạn rõ; ảnh tải lên thử thêm chỉnh phối cảnh, ánh sáng và làm nét khi
> kết quả ban đầu chưa tốt. Luôn giữ ứng viên gốc để tránh warp làm mất ký tự.

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
│   ├── parking_fees.py        #   Cộng phí các khung giờ trong suốt lượt gửi
│   ├── export_stats.py        #   Xuất báo cáo Thống kê ra Excel (.xlsx) / PDF
│   ├── plate_yolo.py          #   Dò vùng biển số bằng YOLOv8 (tùy chọn)
│   ├── plate_preprocess.py    #   Phân dòng, chỉnh phối cảnh, ánh sáng vùng biển số
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

### Tải mã nguồn từ nhánh `tung`

Cài Python (trên Windows chọn **Add Python to PATH**) và Git, sau đó chạy:

```bash
git clone --branch tung --single-branch https://github.com/tunghoclm/du_an_TH1.git
cd du_an_TH1
```

Nếu tải ZIP trên GitHub, chọn nhánh **tung**, bấm **Code → Download ZIP**, rồi giải nén
và mở terminal trong thư mục chứa `app.py`. Các lệnh `cd smart_parking` bên dưới
chỉ là ví dụ; dùng tên thư mục vừa tải về.

Không cần sao chép database, môi trường ảo hay model từ máy người khác: chạy script
cài đặt bên dưới để tạo chúng trên máy của bạn. Lần cài đầu cần Internet.

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
| `/parking`     | Sơ đồ khu và ô đỗ: admin quản lý khu/ô và loại xe được phép; admin/nhân viên chuyển xe, xóa xe có lý do và quản lý bảo trì |
| `/gate`        | **Xe vào / ra** — màn hình chọn **Xe vào** hoặc **Xe ra** |
| `/entry`       | **Xe vào** — tải ảnh hoặc chọn camera → nhận diện → chọn loại xe / vị trí → xác nhận. Chặn xe đang gửi trong bãi |
| `/exit`        | **Xe ra** — tải ảnh hoặc chọn camera → nhận diện → kiểm tra lượt gửi / phí → xác nhận. Chỉ cho xe đang gửi ra bãi |
| `/history`     | Lịch sử lượt gửi, di chuyển và xóa xe; lọc biển số, giao dịch, ngày, khung giờ theo giờ vào hoặc giờ ra/xóa |
| `/statistics`  | Thống kê tổng lượt xe, doanh thu, tỉ lệ lấp đầy bãi đỗ; **xuất báo cáo Excel / PDF** |
| `/customers`   | Quản lý khách hàng: đăng ký thông tin chủ xe, biển số phương tiện và vé tháng |
| `/accounts`    | Quản lý tài khoản nhân viên & quản trị viên: cấp tài khoản, phân quyền, khóa/mở khóa |
| `/pricing`     | Bảng giá xe — 3 bảng: **khung thời gian** (tự đặt giờ/ngày bắt đầu–kết thúc), **loại xe** (tự tạo tên), **giá theo loại xe + thời gian** (lượt/tháng). Ai cũng xem, admin/nhân viên thêm-sửa-xóa |
| `/settings`    | Cài đặt cá nhân (ai đăng nhập cũng dùng được) — tự chọn chế độ gửi xe: **tự động** hoặc **tự chọn vị trí** |

**Nhận diện bằng camera (admin / nhân viên):**
Giao diện gồm hai cột: bên trái hiển thị camera / ảnh cùng nút bật tắt, chọn thiết bị và tải ảnh; bên phải có hai nút **Camera / Tải ảnh**, ghi chú, biển số, loại xe, vị trí và xác nhận. Trên màn hình nhỏ, hai cột xếp dọc.

1. Mở **Xe vào / ra**, chọn **Xe vào** hoặc **Xe ra**, rồi nhấn nút **Camera** ở phần Chọn hình thức nhận diện.
2. Chọn thiết bị và bấm **Bắt đầu**. Cho phép trình duyệt dùng camera; sau khi được cấp quyền, danh sách hiển thị tên webcam tích hợp, USB hoặc camera ảo trên máy đang mở web.
3. Camera tự quét từng khung hình, vẽ khung xanh và hiện biển số ngay trên video. Khi hai lần đọc liên tiếp khớp nhau và đúng cấu trúc biển số, hệ thống giữ ảnh, tự điền biển số và thông tin xe ngay trên trang.
4. Kiểm tra kết quả, chọn loại xe / vị trí nếu là xe vào, rồi bấm **Xác nhận xe vào / xe ra**. Có thể sửa biển số và bấm **Cập nhật biển số**, hoặc bấm **Bắt đầu** để nhận diện lại.

Có nút **Tìm camera**, **Bắt đầu**, **Tắt Camera**; hệ thống nhớ thiết bị riêng cho chiều vào và ra. Bấm **Tắt Camera** để giữ khung hình đã xử lý gần nhất và nhập tay nếu OCR chưa rõ. Camera tự tắt khi nhận được kết quả ổn định, rời trang hoặc chuyển sang Tải ảnh; chỉ ghi nhận xe khi xác nhận.

Tốc độ quét phụ thuộc CPU và model OCR. Mỗi camera chỉ gửi khung tiếp theo sau khi khung trước xử lý xong; ảnh tạm bị thay thế được dọn tự động.

**Nhận diện từ ảnh:** nhấn **Tải ảnh**, chọn file ở cột trái để xem trước, rồi bấm **Nhận diện ảnh**. Kiểm tra kết quả ở cột phải và xác nhận. Với cả hai hình thức, khi xe vào cần chọn loại xe và một vị trí trống (trừ chế độ gán vị trí tự động).

Trên máy chạy ứng dụng, mở **http://localhost:5000** để dùng camera. Nếu mở từ máy khác qua mạng LAN, cần phục vụ trang bằng **HTTPS**; trình duyệt chặn camera trên địa chỉ HTTP LAN thông thường ([quy định của API camera](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)). Khi đổi camera, hãy đóng ứng dụng khác đang giữ thiết bị nếu không mở được.

**Quản lý bãi đỗ** (`/parking`):

- **Admin:** thêm/sửa/xóa khu, chọn loại xe được phép đỗ (hoặc Tất cả loại xe), thêm/sửa/xóa ô đỗ. Khi tạo khu, bắt buộc nhập số lượng ô; khu **D**, **10 ô** sẽ tạo **D01–D10**. Tên khu có dấu được chuyển thành mã không dấu để đặt tên ô. Nếu trùng tên ô đã có, toàn bộ lần tạo sẽ được hủy và báo lỗi.
- Bấm trực tiếp ô để mở các lựa chọn **Sửa ô / Xóa ô / Bảo trì** theo quyền. Với ô đang có xe, có thêm **Chuyển / xóa xe**; xóa ô và bảo trì bị chặn. Đổi tên ô đang có xe sẽ cập nhật lượt gửi và lưu ghi chú. Xóa khu yêu cầu khu không còn xe đang gửi, đồng thời xóa các ô trong khu và giữ lịch sử cũ.
- **Admin và nhân viên:** bấm ô đang có xe để chuyển sang ô trống **trong cùng khu**. Ghi chú lượt gửi tự lưu thời gian, người thao tác, ô nguồn và ô đích; giờ vào và phí không bị đặt lại.
- **Xóa xe khỏi ô:** bắt buộc lý do. Ô được giải phóng, lượt gửi giữ nguyên trong lịch sử với giao dịch **Đã xóa**, kèm người thao tác và lý do; không phát sinh phí gửi xe.
- **Bảo trì:** bấm ô trống, nhập lý do; lý do hiện trên ô bảo trì. Có thể sửa lý do hoặc kết thúc bảo trì. Không bảo trì ô đang có xe.
- **Người dùng:** chỉ xem sơ đồ và lịch sử xe đã đăng ký của mình. Quyền chỉnh sửa được kiểm tra ở máy chủ cho từng thao tác.

Bãi mới khởi tạo 3 khu A/B/C và 18 ô (6 ô mỗi khu). Các lần khởi động sau giữ cấu hình đã sửa, kể cả khi admin xóa hết các ô hoặc các khu.
Quy định loại xe của khu áp dụng cả lúc chọn ô thủ công và lúc gán ô tự động.

**Lọc khung giờ lịch sử:** chọn ngày, bấm **Chọn khung giờ** để hiện **Từ giờ / Đến giờ**, rồi chọn khung trong bảng giá hoặc nhập giờ tùy chọn. Chọn **Tất cả** để bỏ lọc giờ và thu gọn hai ô nhập. Màn hình mặc định lọc theo thời gian vào.
Khung qua nửa đêm (ví dụ 22:00–04:59) với ngày 19/10 gồm từ 22:00 ngày 19 đến hết phút 04:59 ngày 20.
Có thể kết hợp biển số và giao dịch Đang gửi / Đã lấy xe / Đã xóa. Ghi chú đầy đủ cũng có trong cửa sổ Chi tiết.

**Cài đặt chế độ gán vị trí (`/settings`) — riêng cho từng tài khoản, người dùng tự chọn, không cần admin/nhân viên:**
- *Tự động* — hệ thống tự chọn 1 vị trí trống bất kỳ khi có xe vào, không cần chọn tay.
- *Tự chọn* (mặc định) — chọn một ô trống trong khu phù hợp với loại xe khi ghi nhận xe vào.

**Cách tính phí:** khi xe vào bắt buộc chọn **loại xe**. Khi xe ra, hệ thống **cộng giá vé Lượt của tất cả các khung giờ xe đã gửi** trong `/pricing`.
Ví dụ: ô tô vào **11:37**, ra **16:13** → **Sáng 150.000đ + Chiều 150.000đ = 300.000đ**.
Mỗi khung tính một lần cho mỗi lần xuất hiện theo ngày; khung qua nửa đêm (vd 22:00–04:59) tính một lần cho cả khung.
Khung kết thúc lúc `12:59` bao gồm hết phút `12:59`; từ đúng `13:00:00` đã cộng phí khung bắt đầu lúc `13:00`.
Nếu các khung chồng nhau, ưu tiên khung tạo trước. Phí tạm tính hiển thị phép cộng và được tính lại khi xác nhận xe ra.
Vé tháng còn hạn vẫn miễn phí. Nếu chưa có giá tại giờ vào, trang `/entry` yêu cầu bổ sung giá (trừ vé tháng còn hạn).
Khoảng chưa có giá, hoặc xe cũ chưa có loại xe, dùng đơn giá dự phòng **5.000đ/giờ**, tổng thời gian chưa có giá làm tròn lên giờ, tối thiểu một giờ.
Các lượt đã chốt lưu số tiền thực thu trong lịch sử, không tự động sửa lại theo công thức mới.

**Nếu hết ô trống phù hợp với loại xe**, trang `/entry` báo lỗi và không ghi nhận xe vào.

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

Sau đó tải file `test_plate.jpg` lên ở trang `/entry` (xe vào), rồi tải lại đúng ảnh đó
ở trang `/exit` (xe ra) để thử luồng tính phí hoàn chỉnh. Có thể thay tải ảnh bằng cách bấm Bắt đầu trong chế độ camera.

Kiểm tra tự động luồng vào / ra (SQLite và ảnh tạm riêng, OCR giả lập) và vòng đời camera (MediaDevices giả lập, cần Node.js):

```bash
python -m unittest discover -s tests -v
node --test tests/gate_camera.test.js tests/parking_ui.test.js tests/history_filter.test.js
```

## 6. Nhận diện nhanh và API hỗ trợ

**Camera:** cắt vùng biển bằng YOLO/contour, chuẩn hóa vùng đọc tối đa 480 px, tìm
một hoặc hai dòng ký tự rồi gọi trực tiếp bộ nhận dạng EasyOCR khi có thể. Nếu
phân đoạn không chắc chắn, chuyển sang CRAFT. Mỗi khung có số lần thử giới hạn;
camera chờ 150 ms sau phản hồi rồi mới gửi khung tiếp theo. Chỉ giữ kết quả khi
hai lần đọc liên tiếp khớp nhau, đúng định dạng và có độ tin cậy từ 0,65. Có hiển
thị thời gian xử lý và độ tin cậy; đây là điểm của OCR, không phải bảo đảm đúng.

**Ảnh khó:** giữ ảnh gốc, thử lấy đủ bốn góc trong vùng rộng hơn quanh khung phát
hiện để tránh mất dòng dưới, sau đó thử chỉnh nghiêng/phối cảnh, cân bằng ánh
sáng, CLAHE, làm nét nhẹ và ngưỡng thích nghi. Ứng viên được chọn theo định dạng,
sự đồng thuận và độ tin cậy. Chấp nhận biển một hoặc hai dòng, kể cả series hai
chữ. Không tự thêm các chữ số đã mất. Ảnh cháy sáng hoặc nhòe nặng vẫn có thể cần
chụp lại hoặc sửa biển thủ công.

**API tùy chọn:** đã tích hợp [Plate Recognizer Snapshot](https://api.platerecognizer.com/v1/api-reference/).
Mặc định chạy trên máy. Muốn dùng API, tạo token ở nhà cung cấp và đặt trong môi
trường của máy chạy Flask trước khi khởi động. Ví dụ PowerShell:

```powershell
$env:PLATE_API_TOKEN = 'token-cua-ban'
$env:PLATE_API_MODE = 'fallback'
$env:PLATE_API_CAMERA = '1'
.\run.bat
```

Cấu hình này cho phép gửi ảnh/khung camera lên nhà cung cấp khi OCR trên máy chưa
đủ tốt. Chi phí và hạn mức phụ thuộc tài khoản API. Không đưa token vào mã nguồn
hoặc JavaScript; không cần gửi token trong cuộc trò chuyện.

| Biến môi trường | Mặc định | Ý nghĩa |
|---|---|---|
| `PLATE_API_TOKEN` | Trống | Không có token thì chỉ dùng OCR trên máy |
| `PLATE_API_MODE` | `fallback` | `fallback`: OCR yếu mới gọi API; `first`: ưu tiên API; `off`: tắt API |
| `PLATE_API_CAMERA` | `0` | Đặt `1` để cho phép API với khung camera |
| `PLATE_API_REGIONS` | `vn` | Gợi ý quốc gia cho API |
| `PLATE_API_MIN_SCORE` | `0.8` | Chỉ nhận kết quả API đủ tin cậy và đúng định dạng |
| `PLATE_API_TIMEOUT` | `5` | Số giây chờ dịch vụ (giới hạn 0,5–30 giây) |
| `PLATE_API_URL` | Snapshot Cloud | Có thể trỏ tới máy chủ Snapshot SDK riêng |
| `PLATE_GPU` | `auto` | EasyOCR tự dùng CUDA nếu có; `0` ép chạy CPU |
| `PLATE_DETECTOR` | `auto` | Đặt `contour` để tắt YOLO |
| `PLATE_YOLO_MODEL` | `cache/yolo/plate_yolov8n.pt` | Thay bằng mô hình phát hiện biển số đã huấn luyện riêng |
| `PLATE_YOLO_CONF` | `0.25` | Ngưỡng phát hiện vùng biển số |

Camera gọi API cách nhau ít nhất 3 giây. Khi lỗi mạng, sai token hoặc hết hạn mức,
hệ thống tạm ngừng gọi API (60 giây; 300 giây với lỗi xác thực) và tiếp tục OCR
trên máy. Không gửi chồng yêu cầu OCR vào model dùng chung. Việc ghi nhận xe vẫn
cần người dùng bấm Xác nhận; không dùng so khớp gần đúng để tự cho xe ra.

**Đo lại trên máy của bạn** (model thật, ảnh giả lập, không đụng dữ liệu bãi xe và
không gọi API):

```powershell
python tests/benchmark_plate.py --repeat 2 --output cache/tmp/plate-benchmark.json
```

Bài đo gồm biển một/hai dòng, nghiêng, mờ nhẹ, tương phản thấp, lóa nhẹ và méo
phối cảnh; báo thời gian trung vị và kết quả đúng/sai riêng cho camera và ảnh.
Tốc độ sau khi nạp model khác lần chạy đầu. Bộ ảnh giả lập không đại diện cho
độ chính xác với mọi biển số thực tế. Có thể thay model YOLO bằng model được
huấn luyện trên bộ ảnh tại bãi xe để đánh giá thêm.

Thông số bộ nhận dạng tham khảo từ [tài liệu EasyOCR](https://www.jaided.ai/easyocr/documentation/).

## 7. Hướng phát triển thêm (nếu mở rộng)

- Tối ưu tốc độ nhận diện camera hoặc bổ sung theo dõi nhiều biển số trong cùng khung hình.
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
