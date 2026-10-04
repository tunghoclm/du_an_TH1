# 🅿️ Demo: Bãi đỗ xe thông minh (Smart Parking System)

Dự án demo hệ thống bãi đỗ xe thông minh, nhận diện biển số xe tự động bằng
**OpenCV + EasyOCR** (deep learning, chính xác hơn Tesseract), quản lý xe
vào/ra và tính phí bằng **Python (Flask)**, lưu dữ liệu bằng **SQLite (SQL)**,
giao diện web bằng **HTML/CSS**.

> **Vì sao đổi từ Tesseract sang EasyOCR?** Tesseract-OCR được huấn luyện cho
> văn bản in tài liệu, nên đọc biển số xe (font đặc thù, ảnh nghiêng, ánh sáng
> không đều) thường ra kết quả sai/rối. EasyOCR dùng mô hình deep learning
> (CRAFT + CRNN), chịu được ảnh thực tế tốt hơn nhiều — và vẫn hoàn toàn miễn
> phí, mã nguồn mở, cài bằng `pip` mà không cần cài thêm phần mềm hệ thống.

## 1. Cấu trúc dự án

```
smart_parking/
├── app.py                     # Flask server (routes chính)
├── database.py                # Thao tác SQLite
├── plate_recognition.py       # OCR biển số (OpenCV + Tesseract)
├── schema.sql                 # Cấu trúc bảng dữ liệu
├── generate_sample_plate.py   # Tạo ảnh biển số mẫu để test
├── requirements.txt
├── templates/
│   ├── base.html
│   ├── index.html              # Trang chủ - danh sách xe trong bãi
│   ├── entry.html               # Form xe vào
│   ├── exit.html                # Form xe ra
│   └── history.html             # Lịch sử gửi xe
└── static/
    ├── css/style.css
    └── uploads/                # Ảnh upload được lưu tại đây
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
1. Tạo virtual environment (`venv/`)
2. Cài toàn bộ thư viện trong `requirements.txt`
3. **Tải sẵn model EasyOCR** (bước tốn thời gian nhất, cần Internet — chỉ tải 1 lần)
4. Khởi tạo file database `parking.db`

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
| `/entry`       | Xe vào — tải ảnh biển số, OCR nhận diện, **chọn loại xe**, gán vị trí      |
| `/exit`        | Xe ra — tải ảnh biển số, đối chiếu, tính phí, **trả lại vị trí đã gán**      |
| `/history`     | Lịch sử toàn bộ lượt gửi xe, có bộ lọc theo biển số / trạng thái / ngày      |
| `/statistics`  | Thống kê tổng lượt xe, doanh thu, tỉ lệ lấp đầy bãi đỗ                       |
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
ở khung giờ hiện tại thì trang `/entry` không cho nhận xe và báo cần bổ sung giá. Giá vé *Tháng* chỉ để tham khảo, chưa áp dụng tự động.
Với xe cũ chưa có loại xe (hoặc giá đã bị xóa), hệ thống dùng đơn giá dự phòng 5.000 VNĐ / giờ (biến `FEE_PER_HOUR` trong `app.py`).

**Nếu bãi đỗ hết chỗ** (60/60 vị trí đều occupied/maintenance), trang `/entry` sẽ báo lỗi
"Bãi đỗ đã hết chỗ trống" và không ghi nhận xe vào.

## 5. Test nhanh không cần ảnh xe thật

Dùng script có sẵn để tạo ảnh biển số giả lập:

```bash
python generate_sample_plate.py "51F-123.45" test_plate.jpg
```

Sau đó tải file `test_plate.jpg` lên ở trang `/entry`, rồi lại tải lên trang
`/exit` để thử luồng tính phí hoàn chỉnh.

## 6. Ghi chú kỹ thuật

- **Phát hiện vùng biển số**: dùng Canny edge detection + tìm contour 4 cạnh
  lớn nhất trong ảnh (cách làm phổ biến cho bài toán ANPR đơn giản, phù hợp demo).
  Với ảnh thực tế phức tạp (nhiều xe, góc nghiêng, ánh sáng yếu...), nên nâng cấp
  bằng mô hình deep learning (YOLO để detect + CRNN/OCR chuyên dụng) để tăng độ chính xác.
- **Làm sạch text OCR**: loại bỏ ký tự không phải chữ/số, chuyển về chữ hoa.
- **OCR engine**: dùng EasyOCR với `allowlist` giới hạn chỉ chữ cái/số thường
  gặp trên biển số, giúp giảm nhiễu so với để engine đoán tự do. Có cơ chế
  fallback: nếu đọc vùng cắt cho kết quả ngắn/độ tin cậy thấp, sẽ thử lại
  trên toàn ảnh gốc.
- **Nếu vẫn cần chính xác hơn nữa** (dùng cho ảnh biển số Việt Nam thực tế,
  nhiều xe/góc chụp khó), có thể cân nhắc nâng cấp thêm:
  - **PaddleOCR** — độ chính xác rất cao, nhiều dự án ANPR Việt Nam dùng,
    nhưng cài đặt nặng hơn EasyOCR.
  - **YOLOv8 (huấn luyện riêng để detect vùng biển số)** kết hợp EasyOCR/PaddleOCR
    để đọc ký tự — đây là hướng làm chuẩn cho hệ thống ANPR thực tế, thay vì
    dùng contour-detection đơn giản như trong demo này.
  - Bộ dữ liệu biển số Việt Nam có sẵn trên Roboflow/Kaggle nếu muốn tự huấn luyện.
- **Đối chiếu xe ra**: so khớp chính xác chuỗi biển số đã làm sạch. Trong thực
  tế nên thêm thuật toán so khớp gần đúng (fuzzy matching) để xử lý sai số OCR.

## 7. Hướng phát triển thêm (nếu mở rộng)

- Tích hợp camera trực tiếp (OpenCV `VideoCapture`) thay vì upload ảnh thủ công.
- Thêm xác thực người dùng (nhân viên trông xe) và phân quyền.
- Dùng mô hình OCR chuyên biển số (ví dụ EasyOCR, hoặc model huấn luyện riêng)
  để tăng độ chính xác với biển số Việt Nam.
- Thêm thanh toán không tiền mặt (QR code, ví điện tử).
