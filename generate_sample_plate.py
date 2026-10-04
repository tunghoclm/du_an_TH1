"""
generate_sample_plate.py
Script tiện ích: tạo ảnh biển số giả lập (nền trắng, chữ đen) để test
nhanh chức năng OCR mà không cần ảnh xe thật.

Cách dùng:
    python generate_sample_plate.py "51F-123.45" output.jpg
"""

import sys
import cv2
import numpy as np


def generate_plate_image(plate_text: str, out_path: str):
    width, height = 400, 200
    img = np.full((height, width, 3), 255, dtype=np.uint8)

    # Khung viền đen giống biển số thật
    cv2.rectangle(img, (10, 10), (width - 10, height - 10), (0, 0, 0), 4)

    font = cv2.FONT_HERSHEY_SIMPLEX
    text_size = cv2.getTextSize(plate_text, font, 1.6, 4)[0]
    text_x = (width - text_size[0]) // 2
    text_y = (height + text_size[1]) // 2

    cv2.putText(img, plate_text, (text_x, text_y), font, 1.6, (0, 0, 0), 4, cv2.LINE_AA)

    cv2.imwrite(out_path, img)
    print(f"Đã tạo ảnh mẫu: {out_path}")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Cách dùng: python generate_sample_plate.py "51F-123.45" output.jpg')
        sys.exit(1)

    generate_plate_image(sys.argv[1], sys.argv[2])
