"""Local, synthetic OCR benchmark (no database, camera or cloud uploads).

Run: python tests/benchmark_plate.py --output cache/plate-benchmark.json
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'py'))
# Never transmit benchmark images, even if the shell has a cloud token configured.
os.environ.pop('PLATE_API_TOKEN', None)
import plate_recognition as recognition
from plate_utils import plate_key


def samples():
    plate = np.full((170, 520, 3), 240, np.uint8)
    cv2.rectangle(plate, (8, 8), (512, 162), (20, 20, 20), 3)
    cv2.putText(plate, '51F-12345', (26, 115), cv2.FONT_HERSHEY_SIMPLEX,
                2.5, (15, 15, 15), 5, cv2.LINE_AA)
    scene = np.full((720, 1280, 3), 90, np.uint8)
    scene[280:450, 380:900] = plate
    cases = {'clear': scene}
    for name, angle in [('tilt_12', 12), ('tilt_minus_18', -18)]:
        matrix = cv2.getRotationMatrix2D((640, 360), angle, 1)
        cases[name] = cv2.warpAffine(scene, matrix, (1280, 720), borderValue=(90, 90, 90))
    cases['blur'] = cv2.GaussianBlur(scene, (7, 7), 1.5)
    cases['low_contrast'] = cv2.convertScaleAbs(scene, alpha=0.35, beta=135)
    glare = scene.astype(np.float32)
    yy, xx = np.mgrid[:720, :1280]
    light = (115 * np.exp(-((xx - 640) ** 2 / 160**2 + (yy - 350) ** 2 / 100**2)))[:, :, None]
    cases['glare'] = np.clip(glare + light, 0, 255).astype(np.uint8)
    src = np.float32([[380, 280], [900, 280], [900, 450], [380, 450]])
    dst = np.float32([[410, 265], [870, 305], [915, 450], [365, 475]])
    cases['perspective'] = cv2.warpPerspective(scene, cv2.getPerspectiveTransform(src, dst), (1280, 720),
                                               borderValue=(90, 90, 90))
    output = {name: (image, '51F12345') for name, image in cases.items()}
    bike = np.full((280, 420, 3), 240, np.uint8)
    cv2.rectangle(bike, (8, 8), (412, 272), (15, 15, 15), 3)
    cv2.putText(bike, '15-P1', (60, 110), cv2.FONT_HERSHEY_SIMPLEX, 2, (15, 15, 15), 4, cv2.LINE_AA)
    cv2.putText(bike, '037.37', (25, 230), cv2.FONT_HERSHEY_SIMPLEX, 2, (15, 15, 15), 4, cv2.LINE_AA)
    scene = np.full((720, 1280, 3), 90, np.uint8)
    scene[220:500, 430:850] = bike
    output['motorcycle'] = (scene, '15P103737')
    matrix = cv2.getRotationMatrix2D((640, 360), 22, 1)
    output['motorcycle_tilt'] = (cv2.warpAffine(scene, matrix, (1280, 720), borderValue=(90, 90, 90)), '15P103737')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output')
    parser.add_argument('--repeat', type=int, default=2)
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix='parking-ocr-benchmark-') as folder:
        cases = samples()
        warm = str(Path(folder) / 'warm.jpg')
        cv2.imwrite(warm, cases['clear'][0])
        recognition.recognize_plate_live(warm)
        for name, (frame, expected) in cases.items():
            path = str(Path(folder) / (name + '.jpg'))
            cv2.imwrite(path, frame)
            for profile in ('live', 'upload'):
                elapsed, plates = [], []
                for _ in range(max(1, args.repeat)):
                    started = time.perf_counter()
                    fn = recognition.recognize_plate_live if profile == 'live' else recognition.recognize_plate
                    plate = fn(path)[0]
                    elapsed.append((time.perf_counter() - started) * 1000)
                    plates.append(plate)
                row = dict(case=name, profile=profile, ms=round(statistics.median(elapsed)),
                           correct=all(plate_key(p) == expected for p in plates), predictions=plates)
                results.append(row)
                print(json.dumps(row), flush=True)
    if args.output:
        Path(args.output).write_text(json.dumps(results, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
