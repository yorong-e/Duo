#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ultralytics 기반 평면도 설비 객체 탐지기.

처리 흐름
1. 전체 도면 원본과 이진화본으로 큰 설비를 탐지한다.
2. 5K처럼 큰 도면은 내용 영역만 겹치는 1280px 타일로 나눠 작은 심볼을
   원본 해상도에 가깝게 탐지한다.
3. 타일 좌표를 원본 이미지 좌표로 복원한다.
4. IoU와 중심 거리로 중복 bbox를 제거한다.
5. 모델별 클래스명을 앱 공통 라벨(toilet, washbasin 등)로 정규화한다.

반환 bbox는 항상 원본 이미지 기준 [x1, y1, x2, y2]이며, 브라우저는 그
중심점을 방 마스크에 대입해 공간을 분류하고 기본 GLB를 배치한다.
"""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np


DEFAULT_MODEL_PATH = "weights/floorplan-fixtures.pt"
DEFAULT_CONFIDENCE = 0.4
DEFAULT_IMAGE_SIZE = 1280
DEFAULT_TILE_SIZE = 1280
DEFAULT_TILE_OVERLAP = 0.2

LABEL_MAP = {
    "range": "stove",
    "gas_range": "stove",
    "stove": "stove",
    "kitchen_sink": "kitchen_sink",
    "bathroom_sink": "washbasin",
    "washbasin": "washbasin",
    "wash_basin": "washbasin",
    "sink": "sink",
    "toilet": "toilet",
    "wc": "toilet",
    "shower": "shower",
    "bathtub": "bathtub",
    "bath_tub": "bathtub",
    "bath": "bathtub",
    "refrigerator": "refrigerator",
    "fridge": "refrigerator",
    "dishwasher": "dishwasher",
}


def normalize_label(label):
    value = str(label or "").lower().strip().replace("-", " ")
    value = "_".join(value.split())
    return LABEL_MAP.get(value)


def resolve_model_path(model_path=None):
    configured = model_path or os.getenv("FLOORPLAN_DETECTOR_MODEL") or DEFAULT_MODEL_PATH
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def make_cad_contrast_image(img):
    """유색 바닥을 흰색으로 정리해 CAD 학습 이미지와 가까운 입력을 만든다."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _threshold, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)


def axis_tile_starts(start, end, tile_size, overlap, limit):
    start = max(0, min(int(start), max(limit - 1, 0)))
    end = max(start + 1, min(int(end), limit))
    if end - start <= tile_size:
        return [max(0, min(start, limit - tile_size))]
    step = max(1, int(round(tile_size * (1.0 - overlap))))
    starts = list(range(start, max(end - tile_size + 1, start + 1), step))
    final_start = max(0, min(end - tile_size, limit - tile_size))
    if not starts or starts[-1] != final_start:
        starts.append(final_start)
    return sorted(set(starts))


def build_inference_inputs(img, tile_size, overlap):
    """탐지 입력을 만든다.

    전체 도면은 작은 설비가 축소되어 사라질 수 있으므로 원본/이진화 2장을
    유지한다. 반면 고해상도 타일은 원본만 사용한다. 이전에는 타일까지 모두
    이진화해 입력 수가 두 배였지만, 실제 도면 프로파일에서 추가 검출 효과는
    거의 없고 추론 시간만 크게 늘어 원본 타일 하나로 제한했다.
    """
    height, width = img.shape[:2]
    inputs = [(img, 0, 0, "full"), (make_cad_contrast_image(img), 0, 0, "full_binary")]
    if width <= tile_size and height <= tile_size:
        return inputs, 0

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    content_y, content_x = np.where(gray < 248)
    if content_x.size == 0:
        return inputs, 0

    padding = max(24, tile_size // 24)
    min_x = max(int(content_x.min()) - padding, 0)
    max_x = min(int(content_x.max()) + padding + 1, width)
    min_y = max(int(content_y.min()) - padding, 0)
    max_y = min(int(content_y.max()) + padding + 1, height)
    x_starts = axis_tile_starts(min_x, max_x, tile_size, overlap, width)
    y_starts = axis_tile_starts(min_y, max_y, tile_size, overlap, height)

    tile_count = 0
    for y in y_starts:
        for x in x_starts:
            tile = img[y:min(y + tile_size, height), x:min(x + tile_size, width)]
            tile_gray = gray[y:y + tile.shape[0], x:x + tile.shape[1]]
            content_ratio = float(np.count_nonzero(tile_gray < 245)) / max(tile_gray.size, 1)
            if content_ratio < 0.002:
                continue
            inputs.append((tile, x, y, "tile"))
            tile_count += 1
    return inputs, tile_count


def box_iou(a, b):
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[2], b[2])
    bottom = min(a[3], b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    if intersection <= 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return intersection / max(area_a + area_b - intersection, 1e-9)


def deduplicate_detections(detections, iou_threshold=0.5):
    kept = []
    for detection in sorted(detections, key=lambda item: item["confidence"], reverse=True):
        duplicate = False
        for current in kept:
            if box_iou(current["bbox"], detection["bbox"]) >= iou_threshold:
                duplicate = True
                break
            if current["label"] != detection["label"]:
                continue
            current_box = current["bbox"]
            candidate_box = detection["bbox"]
            current_center = (
                (current_box[0] + current_box[2]) / 2,
                (current_box[1] + current_box[3]) / 2,
            )
            candidate_center = (
                (candidate_box[0] + candidate_box[2]) / 2,
                (candidate_box[1] + candidate_box[3]) / 2,
            )
            center_distance = float(np.hypot(
                current_center[0] - candidate_center[0],
                current_center[1] - candidate_center[1],
            ))
            current_diagonal = float(np.hypot(
                current_box[2] - current_box[0],
                current_box[3] - current_box[1],
            ))
            candidate_diagonal = float(np.hypot(
                candidate_box[2] - candidate_box[0],
                candidate_box[3] - candidate_box[1],
            ))
            if center_distance <= max(32.0, current_diagonal, candidate_diagonal) * 1.1:
                duplicate = True
                break
        if not duplicate:
            kept.append(detection)
    return kept


def detect_floorplan_objects(img, model_path=None, confidence=None):
    model_file = resolve_model_path(model_path)
    threshold = float(
        confidence
        if confidence is not None
        else os.getenv("FLOORPLAN_DETECTOR_CONFIDENCE", DEFAULT_CONFIDENCE)
    )
    threshold = max(0.01, min(threshold, 1.0))
    image_size = int(os.getenv("FLOORPLAN_DETECTOR_IMAGE_SIZE", DEFAULT_IMAGE_SIZE))
    tile_size = int(os.getenv("FLOORPLAN_DETECTOR_TILE_SIZE", DEFAULT_TILE_SIZE))
    tile_overlap = float(os.getenv("FLOORPLAN_DETECTOR_TILE_OVERLAP", DEFAULT_TILE_OVERLAP))
    tile_size = max(640, tile_size)
    tile_overlap = max(0.0, min(tile_overlap, 0.5))
    device = os.getenv("FLOORPLAN_DETECTOR_DEVICE", "cpu")

    metadata = {
        "status": "unavailable",
        "model": str(model_file),
        "confidence": threshold,
        "image_size": image_size,
        "tile_size": tile_size,
        "tile_overlap": tile_overlap,
        "device": device,
        "detection_count": 0,
    }
    if img is None or not isinstance(img, np.ndarray) or img.size == 0:
        metadata["error"] = "탐지할 평면도 이미지가 없습니다."
        return [], metadata
    if not model_file.is_file():
        metadata["error"] = f"객체 탐지 가중치를 찾지 못했습니다: {model_file}"
        return [], metadata

    try:
        from ultralytics import YOLO

        model = YOLO(str(model_file))
        inference_inputs, tile_count = build_inference_inputs(img, tile_size, tile_overlap)
        images = [entry[0] for entry in inference_inputs]
        results = model.predict(
            images,
            imgsz=image_size,
            conf=threshold,
            iou=0.5,
            max_det=300,
            device=device,
            verbose=False,
        )

        raw = []
        ignored_labels = set()
        for result, input_entry in zip(results, inference_inputs):
            _input_image, offset_x, offset_y, input_variant = input_entry
            if result.boxes is None:
                continue
            boxes = result.boxes.xyxy.cpu().tolist()
            scores = result.boxes.conf.cpu().tolist()
            class_ids = result.boxes.cls.cpu().tolist()
            for bbox, score, class_id in zip(boxes, scores, class_ids):
                detector_label = model.names[int(class_id)]
                label = normalize_label(detector_label)
                if not label:
                    ignored_labels.add(str(detector_label))
                    continue
                raw.append({
                    "label": label,
                    "bbox": [
                        round(float(bbox[0]) + offset_x, 2),
                        round(float(bbox[1]) + offset_y, 2),
                        round(float(bbox[2]) + offset_x, 2),
                        round(float(bbox[3]) + offset_y, 2),
                    ],
                    "confidence": round(float(score), 4),
                    "detector_label": str(detector_label),
                    "source": "floorplan_fixture_yolo",
                    "input_variant": input_variant,
                })

        detections = deduplicate_detections(raw)
        metadata.update({
            "status": "ok",
            "input_count": len(inference_inputs),
            "tile_count": tile_count,
            "raw_detection_count": len(raw),
            "detection_count": len(detections),
            "detected_labels": sorted({item["label"] for item in detections}),
            "ignored_labels": sorted(ignored_labels),
        })
        return detections, metadata
    except Exception as exc:  # 벡터화 자체는 탐지 실패와 무관하게 계속 제공한다.
        metadata["status"] = "error"
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        return [], metadata
