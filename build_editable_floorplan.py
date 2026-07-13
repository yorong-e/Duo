#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_walls.py와 extract_layers.py 결과를 사용해 앱에서 편집 가능한 평면도 JSON을 만든다.

출력 JSON:
  - image.@attributes: 원본 좌표계 크기
  - walls[]: 각 벽을 개별 선택/이동/회전/삭제할 수 있는 중심선 벡터
  - floors[]: 재구성 화면에 그릴 바닥 폴리곤
  - rooms[]: 공간 분류와 바닥 편집에 사용하는 방 폴리곤
  - room_labels[]: OCR로 인식한 공간명과 원본 좌표
  - layers.non_residential_mask: 회색 비실사용 공간 마스크
  - layers.wall_mask: 화면 표시와 충돌 판정에 함께 쓰는 축소 이진 마스크

사용법:
  python build_editable_floorplan.py input.json -o editable-floorplan.json
  python build_editable_floorplan.py input.json --debug-dir out_layers
"""

import argparse
import base64
import copy
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

import extract_layers
import extract_walls
from floorplan_vectorizer import vectorize


DEFAULT_WALL_HEIGHT_MM = 2400
FLOOR_PLAN_PIXEL_MM = 10
PARTITION_WALL_MAX_MM = 200
ROOM_MIN_AREA_RATIO = 0.00035
ROOM_MIN_AREA_PX = 3000
ROOM_SEAL_MIN_KERNEL = 17
ROOM_SEAL_MAX_KERNEL = 61
PLAN_DARK_CONTENT_THRESH = 170
PLAN_COLOR_CHROMA_THRESH = 14
PLAN_COLOR_BRIGHTNESS_MAX = 245
PLAN_CLOSE_KERNEL = 55
PLAN_DILATE_KERNEL = 3
OUTPUT_WALL_MASK_MAX_DIM = 2048
NON_RESIDENTIAL_MIN_AREA_RATIO = 0.01
NON_RESIDENTIAL_MIN_DENSITY = 0.42
NON_RESIDENTIAL_ROOM_GRAY_RATIO = 0.52
RGB_RANGE_OVERLAY_MIN_AREA_PX = 800
RGB_RANGE_VETO_RADIUS_PX = 12
RGB_RANGE_VETO_MIN_PIXELS = 80
RGB_RANGE_VETO_MIN_RATIO = 0.55
PERIMETER_GRAY_MIN_SEED_RATIO = 0.35
PERIMETER_GRAY_MIN_HALF_WIDTH_PX = 1.9
ENCLOSED_GRAY_POCKET_MAX_PLAN_RATIO = 0.003
ENCLOSED_GRAY_POCKET_MIN_NEIGHBOR_RATIO = 0.55
ROOM_LABEL_KEYWORDS = {
    "non_residential": (
        "공용홀", "공용복도", "계단실", "엘리베이터", "승강기",
        "파이프샤프트", "eps실", "ps실", "elevator", "stairwell",
    ),
    "bathroom": ("욕실", "화장실", "bathroom", "toilet", "wc"),
    "kitchen": ("주방", "식당", "kitchen", "dining"),
    "bedroom": ("침실", "bedroom"),
    "living_room": ("거실", "living"),
    "entrance": ("현관", "entrance"),
    "balcony": ("발코니", "balcony"),
    "dress_room": ("드레스룸", "dressroom", "dress room"),
    "utility": ("다용도실", "세탁실", "utility", "laundry"),
    "storage": ("팬트리", "창고", "pantry", "storage"),
    "study": ("서재", "study"),
    "hall": ("복도", "hall"),
    "alpha_room": ("알파룸", "alpha room"),
}


def encode_png_data_uri(img):
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG 인코딩에 실패했습니다.")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


def resize_mask_for_client(mask, max_dimension=OUTPUT_WALL_MASK_MAX_DIM):
    """브라우저 충돌 판정용 마스크를 필요한 해상도로만 전달한다.

    원본 5K 마스크를 그대로 보내면 브라우저가 약 17M 픽셀의 적분 배열을
    만들며 메모리와 JSON 파싱 시간이 급증한다. 충돌 검사는 장면 좌표로 다시
    정규화하므로 긴 변 2048px이면 편집 정밀도를 유지하면서 메모리를 크게
    줄일 수 있다. 이진 마스크이므로 보간은 INTER_NEAREST를 사용한다.
    """
    height, width = mask.shape[:2]
    longest = max(width, height)
    if longest <= max_dimension:
        return mask
    scale = max_dimension / float(longest)
    return cv2.resize(
        mask,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_NEAREST,
    )


def estimate_wall_thickness(mask):
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    nz = dist[dist > 0]
    return float(np.percentile(nz, 90) * 2) if nz.size else 10.0


def remove_fine_wall_strokes(wall_mask, wall_thickness):
    """벽보다 얇은 가구선, 치수선, 기호선을 벽 마스크에서 제거한다.

    작은 타원형 opening만 사용하므로 실제 두께가 있는 벽은 유지하면서
    계단의 X 표시나 가구 윤곽처럼 1~수 픽셀인 잔선은 벡터화 전에 사라진다.
    """
    radius = max(1, int(round(max(float(wall_thickness), 2.0) * 0.18)))
    kernel_size = radius * 2 + 1
    cleaned = cv2.morphologyEx(
        wall_mask,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)),
    )
    return cleaned, {
        "fine_stroke_open_radius_px": radius,
        "removed_fine_stroke_px": int(
            np.count_nonzero(wall_mask) - np.count_nonzero(cleaned)
        ),
    }


def regularize_wall_mask(wall_mask, wall_thickness):
    """작은 끊김만 직선으로 메워 벽을 실선화하고 문 크기 개구부는 남긴다.

    수평/수직 closing을 따로 적용하므로 비스듬한 가구선을 새 벽으로
    만들지 않고, 양쪽에 실제 벽 픽셀이 있는 짧은 간격만 연결한다.
    """
    gap_limit = max(3, int(round(max(float(wall_thickness), 2.0) * 1.35)))
    horizontal = cv2.morphologyEx(
        wall_mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (gap_limit, 1)),
    )
    vertical = cv2.morphologyEx(
        wall_mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, gap_limit)),
    )
    regularized = cv2.bitwise_or(wall_mask, cv2.bitwise_or(horizontal, vertical))
    return regularized, {"filled_gap_limit_px": gap_limit}


def build_topology_wall_mask(wall_mask, wall_thickness):
    """검출 벽의 직선 방향을 따라 다음 벽까지 연결해 방 경계를 만든다.

    고정 크기 morphology로 공간을 대충 닫지 않는다. 실제 벽 중심선을 먼저
    구하고, 각 끝점에서 같은 진행 방향으로 탐색했을 때 다른 벽을 만나는
    경우에만 그 사이를 직선으로 연결한다. 추가선은 방 분류에만 사용한다.
    """
    topology = wall_mask.copy()
    segments = vectorize(wall_mask, wall_thickness)
    height, width = wall_mask.shape
    thickness = max(float(wall_thickness), 2.0)
    connector_width = max(3, int(round(thickness * 0.7)))
    clearance = max(3, int(round(thickness * 1.8)))
    maximum_extension = max(
        int(round(thickness * 14.0)),
        int(round(min(height, width) * 0.12)),
    )
    maximum_extension = min(maximum_extension, int(round(min(height, width) * 0.35)))
    hit_radius = max(1, int(round(thickness * 0.45)))
    connection_count = 0

    # 벡터화 과정에서 하나의 직선으로 병합된 짧은 단절부도 방 판정에서는
    # 실선으로 사용한다. 원본 렌더링 wall_mask는 변경하지 않는다.
    for x1, y1, x2, y2, _segment_thickness in segments:
        cv2.line(
            topology,
            (int(round(x1)), int(round(y1))),
            (int(round(x2)), int(round(y2))),
            255,
            connector_width,
        )

    for x1, y1, x2, y2, _segment_thickness in segments:
        dx = float(x2 - x1)
        dy = float(y2 - y1)
        length = math.hypot(dx, dy)
        if length < 1:
            continue
        ux, uy = dx / length, dy / length
        rays = (
            ((float(x1), float(y1)), (-ux, -uy)),
            ((float(x2), float(y2)), (ux, uy)),
        )
        for (start_x, start_y), (ray_x, ray_y) in rays:
            hit = None
            for distance in range(clearance, maximum_extension + 1):
                px = int(round(start_x + ray_x * distance))
                py = int(round(start_y + ray_y * distance))
                if px < 0 or px >= width or py < 0 or py >= height:
                    break
                left = max(px - hit_radius, 0)
                right = min(px + hit_radius + 1, width)
                top = max(py - hit_radius, 0)
                bottom = min(py + hit_radius + 1, height)
                if np.any(wall_mask[top:bottom, left:right]):
                    hit = (px, py)
                    break
            if hit is None:
                continue
            cv2.line(
                topology,
                (int(round(start_x)), int(round(start_y))),
                hit,
                255,
                connector_width,
            )
            connection_count += 1

    topology = cv2.dilate(topology, np.ones((3, 3), np.uint8))
    return topology, {
        "straight_wall_connection_count": connection_count,
        "maximum_wall_extension_px": maximum_extension,
        "connector_width_px": connector_width,
    }


def raw_mask_overlay(img, wall_mask, floor_mask):
    """벽/바닥 마스크를 보정 없이 그대로 원본 평면도 위에 겹친 검증용 이미지.
    (벡터화/스냅 등 후보정 결과는 절대 반영하지 않음 — extract_walls 마스크 원본만 사용)"""
    overlay = img.copy()
    overlay[wall_mask > 0] = (0, 0, 255)
    blue = overlay.copy()
    blue[floor_mask > 0] = (255, 100, 0)
    return cv2.addWeighted(overlay, 0.58, blue, 0.42, 0)


def room_type_from_text(text):
    normalized = " ".join(str(text or "").lower().split())
    compact = normalized.replace(" ", "")
    for room_type, keywords in ROOM_LABEL_KEYWORDS.items():
        for keyword in keywords:
            keyword_normalized = keyword.lower()
            if keyword_normalized in normalized or keyword_normalized.replace(" ", "") in compact:
                return room_type
    return None


def ensure_room_label_ocr_binary():
    """macOS Vision OCR Swift 헬퍼를 target에 1회 컴파일하고 재사용한다."""
    swift = shutil.which("swiftc")
    source = Path(__file__).with_name("room_label_ocr.swift")
    if not swift or not source.is_file():
        return None, "macOS Vision OCR 헬퍼를 찾지 못했습니다."

    target_dir = Path(__file__).resolve().parent / "target" / "room-label-ocr"
    binary = target_dir / "room-label-ocr"
    if binary.is_file() and binary.stat().st_mtime >= source.stat().st_mtime:
        return binary, None

    target_dir.mkdir(parents=True, exist_ok=True)
    module_cache = target_dir / "module-cache"
    module_cache.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["CLANG_MODULE_CACHE_PATH"] = str(module_cache)
    environment["SWIFT_MODULECACHE_PATH"] = str(module_cache)
    try:
        result = subprocess.run(
            [swift, str(source), "-o", str(binary)],
            cwd=Path(__file__).resolve().parent,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"OCR 헬퍼 컴파일 실패: {exc}"
    if result.returncode != 0:
        error = (result.stderr or result.stdout or "unknown error").strip()
        return None, f"OCR 헬퍼 컴파일 실패: {error}"
    return binary, None


def recognize_room_labels(img):
    """Vision OCR 결과 중 알려진 공간명이 들어간 텍스트만 반환한다."""
    binary, error = ensure_room_label_ocr_binary()
    metadata = {
        "status": "unavailable" if error else "ready",
        "engine": "macos_vision",
        "label_count": 0,
    }
    if error:
        metadata["error"] = error
        return [], metadata

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temporary:
            temporary_path = Path(temporary.name)
        if not cv2.imwrite(str(temporary_path), img):
            raise RuntimeError("OCR 임시 이미지를 저장하지 못했습니다.")
        result = subprocess.run(
            [str(binary), str(temporary_path)],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if result.returncode != 0:
            error_text = (result.stderr or result.stdout or "unknown error").strip()
            raise RuntimeError(error_text)
        recognized = json.loads(result.stdout)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        metadata["status"] = "error"
        metadata["error"] = f"{type(exc).__name__}: {exc}"
        return [], metadata
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    height, width = img.shape[:2]
    labels = []
    for item in recognized:
        text = str(item.get("text", "")).strip()
        room_type = room_type_from_text(text)
        confidence = float(item.get("confidence", 0))
        if room_type is None or confidence < 0.25:
            continue
        x = max(0.0, min(float(item.get("x", 0)), 1.0)) * width
        y = max(0.0, min(float(item.get("y", 0)), 1.0)) * height
        box_width = max(0.0, min(float(item.get("width", 0)), 1.0)) * width
        box_height = max(0.0, min(float(item.get("height", 0)), 1.0)) * height
        if box_width < 2 or box_height < 2:
            continue
        labels.append({
            "id": f"room_label_{len(labels):03d}",
            "text": text,
            "room_type": room_type,
            "confidence": round(confidence, 4),
            "bbox": {
                "x": round(x, 2),
                "y": round(y, 2),
                "width": round(box_width, 2),
                "height": round(box_height, 2),
            },
            "source": "macos_vision_ocr",
        })
    metadata.update({"status": "ok", "label_count": len(labels)})
    return labels, metadata


def build_labeled_residential_mask(
        room_labels,
        room_masks,
        shape,
        img=None,
        wall_mask=None):
    """OCR 공간명 주변의 실제 주거 바닥만 보호한다.

    라벨 padding 사각형을 그대로 보호하면 현관/드레스룸 가까이에 있는 벽 너머
    회색 공용부까지 잘려 나간다. 원본 이미지가 있으면 목재 계열 바닥인 공간은
    따뜻한 바닥색 주변으로 보호를 제한한다. 욕실·주방처럼 회색 마감일 수 있는
    공간은 벽을 넘지 않는 범위에서 기존의 넓은 보호를 유지한다.
    """
    height, width = shape[:2]
    protected = np.zeros((height, width), np.uint8)
    warm_floor_support = None
    if img is not None and img.shape[:2] == (height, width):
        b, g, r = [channel.astype(np.int16) for channel in cv2.split(img)]
        brightness = (b + g + r) / 3.0
        chroma = np.maximum.reduce((np.abs(r - g), np.abs(g - b), np.abs(r - b)))
        warm_floor = (
            (brightness >= 132)
            & (brightness <= 248)
            & (r >= g - 18)
            & (g >= b - 8)
            & (r >= b + 10)
            & (r - g <= 58)
            & (chroma <= 96)
        ).astype(np.uint8) * 255
        warm_floor_support = cv2.morphologyEx(
            warm_floor,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)),
        ) > 0
    wall_pixels = None
    if wall_mask is not None and wall_mask.shape == (height, width):
        wall_pixels = wall_mask > 0
    for label in room_labels:
        if isinstance(label, dict) and label.get("room_type") == "non_residential":
            continue
        bbox = label.get("bbox") if isinstance(label, dict) else None
        if not isinstance(bbox, dict):
            continue
        x1 = max(0, min(int(math.floor(float(bbox.get("x", 0)))), width - 1))
        y1 = max(0, min(int(math.floor(float(bbox.get("y", 0)))), height - 1))
        x2 = max(x1 + 1, min(int(math.ceil(float(bbox.get("x", 0)) + float(bbox.get("width", 0)))), width))
        y2 = max(y1 + 1, min(int(math.ceil(float(bbox.get("y", 0)) + float(bbox.get("height", 0)))), height))
        center_x = min(max((x1 + x2) // 2, 0), width - 1)
        center_y = min(max((y1 + y2) // 2, 0), height - 1)

        best_room = None
        best_overlap = 0
        for room_mask in room_masks:
            overlap = int(np.count_nonzero(room_mask[y1:y2, x1:x2]))
            if overlap > best_overlap:
                best_overlap = overlap
                best_room = room_mask
        if best_room is None:
            for room_mask in room_masks:
                if room_mask[center_y, center_x] > 0:
                    best_room = room_mask
                    break
        if best_room is not None:
            room_type = str(label.get("room_type") or "")
            # 방 분리를 사용하지 않으므로 best_room은 침실 하나가 아니라
            # 한 층 전체다. 공간명 하나로 층 전체를 보호하지 않고 라벨
            # 주변의 설비/바닥 영역만 제한적으로 보호한다.
            if room_type == "kitchen":
                padding_x = max(int((x2 - x1) * 1.5), 80)
                padding_y = max(int((y2 - y1) * 2.0), 60)
            elif room_type == "bathroom":
                padding_x = max(int((x2 - x1) * 1.5), 60)
                padding_y = max(int((y2 - y1) * 2.0), 60)
            elif room_type == "balcony":
                padding_x = max(int((x2 - x1) * 1.25), 70)
                padding_y = max(int((y2 - y1) * 2.0), 70)
            else:
                padding_x = max(int((x2 - x1) * 0.75), 12)
                padding_y = max(int((y2 - y1) * 0.75), 12)
            local_x1 = max(x1 - padding_x, 0)
            local_y1 = max(y1 - padding_y, 0)
            local_x2 = min(x2 + padding_x, width)
            local_y2 = min(y2 + padding_y, height)
            local_protected = np.ones(
                (local_y2 - local_y1, local_x2 - local_x1),
                dtype=bool,
            )
            # 일반 주거 공간은 목재 바닥과 그 가장자리만 보호한다. 이 제한이
            # 현관/침실 라벨 사각형이 회색 공용부로 삐져나가는 것을 막는다.
            # 주방은 이 도면처럼 따뜻한 장판 위에 놓이는 경우가 많다. 주방을
            # 회색 바닥 공간으로 취급해 사각형 전체를 보호하면 벽 너머 공용부를
            # 함께 지우므로, 욕실/설비실만 회색 바닥 예외로 둔다.
            gray_floor_room_types = {"bathroom", "utility"}
            if warm_floor_support is not None and room_type not in gray_floor_room_types:
                local_protected &= warm_floor_support[
                    local_y1:local_y2,
                    local_x1:local_x2,
                ]
            # 욕실처럼 회색 마감일 수 있는 공간도 padding 사각형 전체를
            # 보호하지 않는다. 라벨 bbox와 같은 벽 내부 연결 성분만 선택해야
            # 인접한 현관 공용부까지 보호 마스크가 넘어가지 않는다.
            if wall_pixels is not None and room_type in gray_floor_room_types:
                local_open = (~wall_pixels[
                    local_y1:local_y2,
                    local_x1:local_x2,
                ]).astype(np.uint8)
                component_count, component_labels, _stats, _centroids = (
                    cv2.connectedComponentsWithStats(local_open, 8)
                )
                bbox_roi = component_labels[
                    y1 - local_y1:y2 - local_y1,
                    x1 - local_x1:x2 - local_x1,
                ]
                component_ids, component_overlaps = np.unique(
                    bbox_roi[bbox_roi > 0],
                    return_counts=True,
                )
                if component_count > 1 and component_ids.size:
                    label_component = int(component_ids[np.argmax(component_overlaps)])
                    local_protected &= component_labels == label_component
            if wall_pixels is not None:
                local_protected &= ~wall_pixels[
                    local_y1:local_y2,
                    local_x1:local_x2,
                ]
            protected_roi = protected[local_y1:local_y2, local_x1:local_x2]
            protected_roi[local_protected] = 255
    return protected


def build_labeled_non_residential_mask(room_labels, room_masks, shape):
    """용도가 명시된 공용·설비 공간을 해당 벽 폐쇄 영역까지 확장한다."""
    explicit_labels = [
        label for label in room_labels
        if isinstance(label, dict) and label.get("room_type") == "non_residential"
    ]
    # 공용 라벨을 임시 일반 라벨로 바꿔 동일한 방 매칭 규칙을 재사용한다.
    matchable_labels = [dict(label, room_type="explicit_area") for label in explicit_labels]
    explicit = build_labeled_residential_mask(matchable_labels, room_masks, shape)
    height, width = shape[:2]
    for label in explicit_labels:
        bbox = label.get("bbox") or {}
        x1 = max(0, min(int(float(bbox.get("x", 0))), width - 1))
        y1 = max(0, min(int(float(bbox.get("y", 0))), height - 1))
        x2 = max(x1 + 1, min(int(math.ceil(
            float(bbox.get("x", 0)) + float(bbox.get("width", 0)))), width))
        y2 = max(y1 + 1, min(int(math.ceil(
            float(bbox.get("y", 0)) + float(bbox.get("height", 0)))), height))
        best_room = None
        best_overlap = 0
        for room_mask in room_masks:
            overlap = int(np.count_nonzero(room_mask[y1:y2, x1:x2]))
            if overlap > best_overlap:
                best_room = room_mask
                best_overlap = overlap
        if best_room is None:
            continue
        # 도면의 35%가 넘는 비정상 통합 마스크는 라벨 주변만 사용한다.
        if int(np.count_nonzero(best_room)) <= height * width * 0.35:
            explicit[best_room > 0] = 255
    return explicit


def _extract_non_residential_gray_mask_legacy(
        img,
        wall_mask,
        protected_mask=None,
        room_masks=None,
        explicit_mask=None):
    """벽 내부의 조밀한 무채색 면만 비실사용 오버레이로 추출한다.

    RGB 159~164는 강제 결과가 아니라 회색 면을 찾기 위한 시드로만 쓴다.
    장판색/흰색으로 둘러싸인 작은 음영과 OCR 주방·욕실 보호 영역은 제외한다.
    """
    b, g, r = [channel.astype(np.int16) for channel in cv2.split(img)]
    brightness = (b + g + r) / 3.0
    chroma = np.maximum.reduce((np.abs(r - g), np.abs(g - b), np.abs(r - b)))
    wall_pixels = wall_mask > 0
    dilated_walls = cv2.dilate(wall_mask, np.ones((3, 3), np.uint8)) > 0
    protected_pixels = np.zeros(img.shape[:2], dtype=bool)
    if protected_mask is not None and protected_mask.shape == wall_mask.shape:
        protected_pixels = protected_mask > 0

    if room_masks:
        plan_pixels = np.zeros(img.shape[:2], dtype=bool)
        for room_mask in room_masks:
            plan_pixels |= room_mask > 0
    else:
        plan_pixels = np.ones(img.shape[:2], dtype=bool)
    # 회색 바닥은 검은 벽이 화면에서 위에 덮이므로 실제 벽 픽셀까지만
    # 제외한다. 팽창 벽을 빼면 벽 가장자리에 1~2px 베이지색 이음새가 남는다.
    eligible = plan_pixels & ~wall_pixels & ~protected_pixels

    strong_gray = (
        (chroma <= 12)
        & (brightness >= 120)
        & (brightness <= 205)
        & eligible
    )
    raw_exact_rgb = (
        (r >= 159) & (r <= 164)
        & (g >= 159) & (g <= 164)
        & (b >= 159) & (b <= 164)
    )
    exact_rgb = raw_exact_rgb & eligible
    raw_gray_candidate = (
        (chroma <= 24)
        & (brightness >= 105)
        & (brightness <= 215)
        & eligible
    )
    candidate = raw_gray_candidate.astype(np.uint8) * 255
    candidate = cv2.morphologyEx(
        candidate,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)),
        borderType=cv2.BORDER_REPLICATE,
    )
    candidate = cv2.morphologyEx(
        candidate,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
        borderType=cv2.BORDER_REPLICATE,
    )
    candidate[~eligible] = 0

    exact_count, exact_labels, exact_stats, _ = cv2.connectedComponentsWithStats(
        exact_rgb.astype(np.uint8) * 255,
        8,
    )
    valid_exact = np.zeros_like(candidate, dtype=bool)
    rgb_range_region_count = 0
    raw_exact_count, raw_exact_labels, raw_exact_stats, _ = cv2.connectedComponentsWithStats(
        raw_exact_rgb.astype(np.uint8) * 255,
        8,
    )
    rgb_range_rejected_protected_count = sum(
        1
        for index in range(1, raw_exact_count)
        if int(raw_exact_stats[index, cv2.CC_STAT_AREA]) >= RGB_RANGE_OVERLAY_MIN_AREA_PX
        and np.any((raw_exact_labels == index) & protected_pixels)
    )
    for index in range(1, exact_count):
        area = int(exact_stats[index, cv2.CC_STAT_AREA])
        if area >= RGB_RANGE_OVERLAY_MIN_AREA_PX:
            valid_exact |= exact_labels == index
            rgb_range_region_count += 1
    candidate[valid_exact] = 255

    white_pixels = (brightness >= 245) & (chroma <= 18)
    floor_color_pixels = (
        (brightness >= 132)
        & (brightness <= 248)
        & (r >= g - 18)
        & (g >= b - 8)
        & (r >= b + 10)
        & (r - g <= 58)
        & (chroma <= 96)
    )
    veto_pixels = white_pixels | floor_color_pixels
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(candidate, 8)
    mask = np.zeros_like(candidate)
    accepted_areas = []
    rejected_small = 0
    rejected_sparse = 0
    rejected_neighbor = 0
    accepted_wall_enclosed_count = 0
    for index in range(1, component_count):
        selected = labels == index
        area = int(stats[index, cv2.CC_STAT_AREA])
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        density = area / max(width * height, 1)
        seed_count = int(np.count_nonzero(selected & (strong_gray | valid_exact)))
        seed_ratio = seed_count / max(area, 1)

        # 욕실 옆 삼각 포켓처럼 작은 회색 면은 800px 미만이어도 실제 벽으로
        # 여러 면이 둘러싸여 있으면 유효하다. 단순 창틀/가구선은 벽 접촉률과
        # 면 두께가 부족하므로 이 조건을 통과하지 못한다.
        wall_contact_ring = cv2.dilate(
            selected.astype(np.uint8) * 255,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
        ) > 0
        wall_contact_ring &= ~selected & plan_pixels
        wall_contact_area = int(np.count_nonzero(wall_contact_ring))
        wall_contact_ratio = (
            float(np.count_nonzero(wall_contact_ring & dilated_walls))
            / max(wall_contact_area, 1)
        )
        wall_enclosed_surface = (
            area >= max(180, RGB_RANGE_OVERLAY_MIN_AREA_PX // 4)
            and density >= 0.28
            and seed_ratio >= 0.65
            and wall_contact_ratio >= 0.35
        )
        if area < RGB_RANGE_OVERLAY_MIN_AREA_PX and not wall_enclosed_surface:
            rejected_small += 1
            continue
        if seed_count < min(200, area * 0.20) or seed_ratio < 0.12:
            rejected_sparse += 1
            continue
        if density < 0.28:
            rejected_sparse += 1
            continue

        ring = cv2.dilate(
            selected.astype(np.uint8) * 255,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (RGB_RANGE_VETO_RADIUS_PX * 2 + 1,) * 2,
            ),
        ) > 0
        ring &= ~selected & plan_pixels & ~dilated_walls
        ring_area = int(np.count_nonzero(ring))
        veto_count = int(np.count_nonzero(ring & veto_pixels))
        veto_ratio = veto_count / max(ring_area, 1)
        solid_surface = wall_enclosed_surface or (
            area >= 2500 and (
                (density >= 0.75 and seed_ratio >= 0.50)
                or (density >= 0.45 and seed_ratio >= 0.85)
            )
        )
        if (
                not solid_surface
                and veto_count >= RGB_RANGE_VETO_MIN_PIXELS
                and veto_ratio >= RGB_RANGE_VETO_MIN_RATIO):
            rejected_neighbor += 1
            continue
        mask[selected] = 255
        accepted_areas.append(area)
        if wall_enclosed_surface:
            accepted_wall_enclosed_count += 1

    before_cleanup = int(np.count_nonzero(mask))
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)),
        borderType=cv2.BORDER_REPLICATE,
    )
    mask[~plan_pixels | wall_pixels | protected_pixels] = 0
    cleaned_count, cleaned_labels, cleaned_stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    cleaned = np.zeros_like(mask)
    for index in range(1, cleaned_count):
        if int(cleaned_stats[index, cv2.CC_STAT_AREA]) >= RGB_RANGE_OVERLAY_MIN_AREA_PX:
            cleaned[cleaned_labels == index] = 255
    mask = cleaned

    # 외벽 바깥의 회색 슬래브 띠는 벽 마스크에 의해 가늘게 분절되어 일반
    # 성분 밀도 검사에서 빠질 수 있다. 평면도 외곽으로부터 벽 두께 약 2.2배
    # 이내의 무채색 성분은 별도 보완하되 OCR 보호 영역과 벽은 침범하지 않는다.
    estimated_thickness = estimate_wall_thickness(wall_mask) if np.any(wall_mask) else 10.0
    perimeter_width = max(12, int(round(estimated_thickness * 2.2)))
    plan_distance = cv2.distanceTransform(
        plan_pixels.astype(np.uint8) * 255,
        cv2.DIST_L2,
        5,
    )
    raw_perimeter_candidate = (
        plan_pixels
        & (plan_distance <= perimeter_width)
        & (chroma <= 18)
        & (brightness >= 105)
        & (brightness <= 215)
        & ~wall_pixels
        & ~protected_pixels
    )
    perimeter_candidate = raw_perimeter_candidate.astype(np.uint8) * 255
    perimeter_candidate = cv2.morphologyEx(
        perimeter_candidate,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)),
    )
    perimeter_count, perimeter_labels, perimeter_stats, _ = cv2.connectedComponentsWithStats(
        perimeter_candidate,
        8,
    )
    perimeter_added_area = 0
    perimeter_region_count = 0
    perimeter_rejected_thin_count = 0
    perimeter_rejected_unseeded_count = 0
    accepted_gray_neighborhood = cv2.dilate(
        mask,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)),
    ) > 0
    for index in range(1, perimeter_count):
        area = int(perimeter_stats[index, cv2.CC_STAT_AREA])
        if area < RGB_RANGE_OVERLAY_MIN_AREA_PX:
            continue
        selected = perimeter_labels == index
        # 회전된 외벽을 따라가는 띠는 축 정렬 bounding box의 밀도가 매우
        # 낮아질 수 있다. bbox 밀도 대신 실제 성분의 내접 반경을 사용하면
        # 사선 띠는 살리고 1px 격자선/치수선은 제외할 수 있다.
        raw_selected = selected & raw_perimeter_candidate
        half_width = float(cv2.distanceTransform(
            raw_selected.astype(np.uint8) * 255,
            cv2.DIST_L2,
            5,
        ).max())
        if half_width < PERIMETER_GRAY_MIN_HALF_WIDTH_PX:
            perimeter_rejected_thin_count += 1
            continue
        strong_seed_ratio = float(np.count_nonzero(selected & strong_gray)) / max(area, 1)
        connected_to_gray = bool(np.any(selected & accepted_gray_neighborhood))
        # 큰 회색 면과 연결된 띠는 연한 부분까지 이어 붙이고, 독립 띠는
        # 원본 회색 시드가 충분할 때만 인정한다. 이후 support envelope로
        # close 연산이 목재 바닥 쪽으로 번진 픽셀을 다시 잘라낸다.
        if (
                strong_seed_ratio < PERIMETER_GRAY_MIN_SEED_RATIO
                and not connected_to_gray):
            perimeter_rejected_unseeded_count += 1
            continue
        perimeter_added_area += int(np.count_nonzero(selected & (mask == 0)))
        mask[selected] = 255
        perimeter_region_count += 1

    # close 연산이 좁은 면의 끊김을 메우는 동안 옆의 목재 바닥까지 몇 픽셀
    # 밀어내는 현상을 정리한다. 원본 무채색 픽셀 주변의 얇은 envelope 안에서만
    # 작은 단절을 연결하고, 마지막 3px opening으로 한두 픽셀짜리 돌기를 없앤다.
    refinement_radius = max(1, min(3, int(round(estimated_thickness * 0.15))))
    refinement_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (refinement_radius * 2 + 1,) * 2,
    )
    # 검출 wall_mask가 일부 끊겨도 원본의 검은 벽 픽셀은 확실한 장벽이다.
    # 단순 dilation은 이 장벽을 건너 반대편 목재 바닥까지 support를 만들 수
    # 있으므로, 통과 가능한 픽셀 안에서만 반복 팽창하는 geodesic 방식으로 만든다.
    raw_dark_pixels = (
        (brightness <= 85)
        & (chroma <= 55)
        & plan_pixels
    )
    wall_dark_support_radius = max(
        3,
        min(16, int(round(estimated_thickness * 1.25))),
    )
    wall_dark_support = cv2.dilate(
        wall_pixels.astype(np.uint8) * 255,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (wall_dark_support_radius * 2 + 1,) * 2,
        ),
    ) > 0
    # 원본의 모든 어두운 픽셀을 장벽으로 쓰면 치수 문자·주석·기호까지
    # 회색 면에 구멍을 만든다. 검출 벽 자체와 그 주변의 어두운 픽셀만
    # 장벽으로 인정해 끊긴 벽은 보완하고 고립된 문자는 제외한다.
    visual_wall_barrier = wall_pixels | (raw_dark_pixels & wall_dark_support)
    visual_wall_barrier = cv2.morphologyEx(
        visual_wall_barrier.astype(np.uint8) * 255,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    ) > 0
    refinement_passable = eligible & ~visual_wall_barrier
    gray_support = raw_gray_candidate.copy()
    step_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    for _ in range(refinement_radius):
        gray_support = (
            cv2.dilate(gray_support.astype(np.uint8) * 255, step_kernel) > 0
        ) & refinement_passable
    mask_before_narrow_refinement = mask.copy()
    refined_mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        refinement_kernel,
        borderType=cv2.BORDER_REPLICATE,
    )
    refined_mask[(~gray_support) | (~eligible)] = 0
    refined_mask = cv2.morphologyEx(
        refined_mask,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
        borderType=cv2.BORDER_REPLICATE,
    )
    # 원본에서 실제 회색이었고 이미 면으로 승인된 픽셀은 opening으로 모서리가
    # 깎이지 않게 복원한다. 제거 대상은 보정 과정이 새로 만든 돌출 픽셀이다.
    refined_mask[
        (mask_before_narrow_refinement > 0) & raw_gray_candidate
    ] = 255

    # 큰 회색 면과 검은 벽 사이에 남은 얇은 베이지색 이음새만 같은 면에서
    # 벽 쪽으로 채운다. visual_wall_barrier를 통과하지 않는 반복 팽창이므로
    # 벽 반대편 목재 공간으로 회색이 침범하지 않는다.
    wall_snap_radius = max(4, min(10, int(round(estimated_thickness * 0.65))))
    wall_snap_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (wall_snap_radius * 2 + 1,) * 2,
    )
    near_wall_pixels = cv2.dilate(
        visual_wall_barrier.astype(np.uint8) * 255,
        wall_snap_kernel,
    ) > 0
    near_wall_pixels &= refinement_passable
    snapped_mask = refined_mask > 0
    before_wall_snap = snapped_mask.copy()
    for _ in range(wall_snap_radius):
        next_pixels = (
            cv2.dilate(snapped_mask.astype(np.uint8) * 255, step_kernel) > 0
        )
        next_pixels &= refinement_passable & near_wall_pixels
        snapped_mask |= next_pixels
    refined_mask = snapped_mask.astype(np.uint8) * 255
    wall_snap_added_area = int(np.count_nonzero(snapped_mask & ~before_wall_snap))
    narrow_refinement_added_area = int(np.count_nonzero(
        (refined_mask > 0) & (mask_before_narrow_refinement == 0)
    ))
    narrow_refinement_trimmed_area = int(np.count_nonzero(
        (mask_before_narrow_refinement > 0) & (refined_mask == 0)
    ))
    mask = refined_mask

    # 회색 공용부 안의 작은 샤프트/설비 포켓은 스캔 색이 베이지색이어도
    # 사방이 벽과 회색 면으로 둘러싸여 있다. 색만 보고 버리지 말고 실제 벽으로
    # 분리된 작은 공간 중 바깥 이웃이 대부분 회색인 것만 공용부에 흡수한다.
    # OCR 보호 영역이 조금이라도 걸린 공간은 욕실·발코니일 수 있으므로 제외한다.
    pocket_space = (plan_pixels & ~dilated_walls).astype(np.uint8) * 255
    pocket_count, pocket_labels, pocket_stats, _ = cv2.connectedComponentsWithStats(
        pocket_space,
        8,
    )
    pocket_max_area = max(
        RGB_RANGE_OVERLAY_MIN_AREA_PX,
        min(
            int(round(mask.size * ENCLOSED_GRAY_POCKET_MAX_PLAN_RATIO)),
            int(round((estimated_thickness * 9.0) ** 2)),
        ),
    )
    pocket_probe_radius = max(6, int(round(estimated_thickness * 2.4)))
    pocket_probe_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (pocket_probe_radius * 2 + 1,) * 2,
    )
    enclosed_pocket_count = 0
    enclosed_pocket_added_area = 0
    for index in range(1, pocket_count):
        area = int(pocket_stats[index, cv2.CC_STAT_AREA])
        if area < RGB_RANGE_OVERLAY_MIN_AREA_PX or area > pocket_max_area:
            continue
        pocket_x = int(pocket_stats[index, cv2.CC_STAT_LEFT])
        pocket_y = int(pocket_stats[index, cv2.CC_STAT_TOP])
        pocket_width = int(pocket_stats[index, cv2.CC_STAT_WIDTH])
        pocket_height = int(pocket_stats[index, cv2.CC_STAT_HEIGHT])
        roi_x1 = max(0, pocket_x - pocket_probe_radius)
        roi_y1 = max(0, pocket_y - pocket_probe_radius)
        roi_x2 = min(mask.shape[1], pocket_x + pocket_width + pocket_probe_radius)
        roi_y2 = min(mask.shape[0], pocket_y + pocket_height + pocket_probe_radius)
        labels_roi = pocket_labels[roi_y1:roi_y2, roi_x1:roi_x2]
        selected_roi = labels_roi == index
        protected_roi = protected_pixels[roi_y1:roi_y2, roi_x1:roi_x2]
        if np.any(selected_roi & protected_roi):
            continue
        mask_roi = mask[roi_y1:roi_y2, roi_x1:roi_x2]
        current_gray_ratio = (
            float(np.count_nonzero(selected_roi & (mask_roi > 0))) / max(area, 1)
        )
        if current_gray_ratio >= 0.25:
            continue
        neighborhood = cv2.dilate(
            selected_roi.astype(np.uint8) * 255,
            pocket_probe_kernel,
        ) > 0
        neighborhood &= (
            ~selected_roi
            & plan_pixels[roi_y1:roi_y2, roi_x1:roi_x2]
            & ~dilated_walls[roi_y1:roi_y2, roi_x1:roi_x2]
            & ~protected_roi
        )
        neighbor_area = int(np.count_nonzero(neighborhood))
        gray_neighbor_count = int(np.count_nonzero(neighborhood & (mask_roi > 0)))
        gray_neighbor_ratio = gray_neighbor_count / max(neighbor_area, 1)
        if (
                gray_neighbor_count < RGB_RANGE_VETO_MIN_PIXELS
                or gray_neighbor_ratio < ENCLOSED_GRAY_POCKET_MIN_NEIGHBOR_RATIO):
            continue
        newly_added = selected_roi & (mask_roi == 0)
        added_area = int(np.count_nonzero(newly_added))
        mask_roi[newly_added] = 255
        enclosed_pocket_added_area += added_area
        enclosed_pocket_count += 1

    # 최종 경계의 기준은 회색보다 식별력이 높은 목재 바닥 타일로 잡는다.
    # 따뜻한 바닥색 픽셀 사이의 짧은 나뭇결/스캔 공백을 close로 연결해
    # 주거 내부 마스크를 만들고, 이 영역에 잘못 들어온 회색을 제거한다.
    # dilation이 아닌 close이므로 실제 타일 외곽을 일방적으로 넓히지 않는다.
    tile_kernel_size = max(9, min(31, int(round(estimated_thickness * 1.4))))
    if tile_kernel_size % 2 == 0:
        tile_kernel_size += 1
    tile_density = cv2.boxFilter(
        floor_color_pixels.astype(np.float32),
        cv2.CV_32F,
        (tile_kernel_size, tile_kernel_size),
        normalize=True,
        borderType=cv2.BORDER_REPLICATE,
    )
    # 반복되는 목재 결 사이에는 회색/밝은 스캔 픽셀이 섞인다. 주변 밀도가
    # 충분한 실제 목재 픽셀만 시드로 삼고, 검은 벽을 통과하지 않는 geodesic
    # 확장으로 결 사이를 채운다. box 밀도를 바로 마스크로 쓰면 벽 반대편까지
    # 커널 값이 번지는 문제가 생긴다.
    tile_passable = plan_pixels & ~visual_wall_barrier
    residential_tile_mask = (
        floor_color_pixels
        & (tile_density >= 0.12)
        & tile_passable
    )
    tile_growth_radius = tile_kernel_size // 2
    for _ in range(tile_growth_radius):
        residential_tile_mask = (
            cv2.dilate(
                residential_tile_mask.astype(np.uint8) * 255,
                step_kernel,
            ) > 0
        ) & tile_passable
    mask_before_tile_veto = mask.copy()
    tile_veto_removed_area = int(np.count_nonzero(
        (mask > 0) & residential_tile_mask
    ))
    mask[residential_tile_mask] = 0

    # 픽셀 단위 색상 판정 뒤에는 벽으로 나뉜 공간 단위로 한 번 더 정리한다.
    # 회색 방 안의 얇은 목재색 테두리와 목재 방에 들어온 작은 회색 조각을
    # 각각 공간 전체의 우세한 증거에 맞춰 통일한다. 문 크기의 개구부만
    # 임시로 막아 방/외곽 띠가 하나의 판정 단위가 되게 한다.
    zone_seal_size = max(11, min(41, int(round(estimated_thickness * 2.8))))
    if zone_seal_size % 2 == 0:
        zone_seal_size += 1
    sealed_zone_barrier = cv2.morphologyEx(
        visual_wall_barrier.astype(np.uint8) * 255,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (zone_seal_size, zone_seal_size),
        ),
        borderType=cv2.BORDER_REPLICATE,
    ) > 0
    zone_space = (plan_pixels & ~sealed_zone_barrier).astype(np.uint8) * 255
    zone_count, zone_labels, zone_stats, _ = cv2.connectedComponentsWithStats(
        zone_space,
        8,
    )
    gray_zone_count = 0
    residential_zone_count = 0
    zone_gray_added_area = 0
    zone_gray_removed_area = 0
    for index in range(1, zone_count):
        area = int(zone_stats[index, cv2.CC_STAT_AREA])
        if area < max(200, RGB_RANGE_OVERLAY_MIN_AREA_PX // 4):
            continue
        selected = zone_labels == index
        gray_evidence_ratio = (
            float(np.count_nonzero(selected & (mask_before_tile_veto > 0)))
            / max(area, 1)
        )
        tile_evidence_ratio = (
            float(np.count_nonzero(selected & residential_tile_mask))
            / max(area, 1)
        )
        if gray_evidence_ratio >= 0.55 and tile_evidence_ratio <= 0.35:
            newly_gray = selected & (mask == 0) & ~protected_pixels
            zone_gray_added_area += int(np.count_nonzero(newly_gray))
            mask[newly_gray] = 255
            gray_zone_count += 1

    # 큰 회색 면 내부에 남은 OCR 문자/치수 기호 크기의 작은 구멍을 메운다.
    # 외부나 주거 바닥과 연결된 빈 공간은 성분이 크므로 대상이 되지 않는다.
    gray_hole_space = (
        plan_pixels
        & ~visual_wall_barrier
        & ~protected_pixels
        & (mask == 0)
    ).astype(np.uint8) * 255
    hole_count, hole_labels, hole_stats, _ = cv2.connectedComponentsWithStats(
        gray_hole_space,
        8,
    )
    gray_hole_max_area = max(
        300,
        min(5000, int(round((estimated_thickness * 8.0) ** 2))),
    )
    filled_gray_hole_count = 0
    filled_gray_hole_area = 0
    hole_ring_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    for index in range(1, hole_count):
        area = int(hole_stats[index, cv2.CC_STAT_AREA])
        if area > gray_hole_max_area:
            continue
        selected = hole_labels == index
        ring = cv2.dilate(selected.astype(np.uint8) * 255, hole_ring_kernel) > 0
        ring &= ~selected & plan_pixels & ~visual_wall_barrier
        ring_area = int(np.count_nonzero(ring))
        gray_ring_ratio = float(np.count_nonzero(ring & (mask > 0))) / max(ring_area, 1)
        if ring_area < 20 or gray_ring_ratio < 0.80:
            continue
        mask[selected] = 255
        filled_gray_hole_count += 1
        filled_gray_hole_area += area

    # 최종 출력은 원본 도면에 실제로 존재하는 연결된 무채색 면을 권위
    # 기준으로 다시 만든다. 앞 단계의 공간/벽 보정은 후보 검증에는 유용하지만
    # 원본 회색 면 바깥으로 확장되면 침범이 발생한다. 작은 내부 문자 구멍만
    # 채우고 외곽 윤곽은 원본 픽셀에서 벗어나지 않게 한다.
    source_gray_candidate = (
        plan_pixels
        & ~wall_pixels
        & (chroma <= 18)
        & (brightness >= 115)
        & (brightness <= 222)
    ).astype(np.uint8) * 255
    source_gray_candidate = cv2.morphologyEx(
        source_gray_candidate,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
        borderType=cv2.BORDER_REPLICATE,
    )
    source_count, source_labels, source_stats, _ = cv2.connectedComponentsWithStats(
        source_gray_candidate,
        8,
    )
    authoritative_gray_mask = np.zeros_like(mask)
    authoritative_region_count = 0
    authoritative_hole_area = 0
    authoritative_min_area = RGB_RANGE_OVERLAY_MIN_AREA_PX
    for index in range(1, source_count):
        area = int(source_stats[index, cv2.CC_STAT_AREA])
        if area < authoritative_min_area:
            continue
        source_x = int(source_stats[index, cv2.CC_STAT_LEFT])
        source_y = int(source_stats[index, cv2.CC_STAT_TOP])
        source_width = int(source_stats[index, cv2.CC_STAT_WIDTH])
        source_height = int(source_stats[index, cv2.CC_STAT_HEIGHT])
        labels_roi = source_labels[
            source_y:source_y + source_height,
            source_x:source_x + source_width,
        ]
        component = labels_roi == index
        mask_roi = mask[
            source_y:source_y + source_height,
            source_x:source_x + source_width,
        ]
        current_overlap_ratio = (
            float(np.count_nonzero(component & (mask_roi > 0))) / max(area, 1)
        )
        # 연결된 격자선이나 반복 무늬도 면적만 보면 커질 수 있으므로 크기와
        # 무관하게 앞 단계의 면/타일 검증을 통과한 회색 성분만 인정한다.
        if current_overlap_ratio < 0.40:
            continue
        authoritative_roi = authoritative_gray_mask[
            source_y:source_y + source_height,
            source_x:source_x + source_width,
        ]
        authoritative_roi[component] = 255
        authoritative_region_count += 1

        component_u8 = component.astype(np.uint8) * 255
        inverse = cv2.bitwise_not(component_u8)
        flood = inverse.copy()
        flood_mask = np.zeros((flood.shape[0] + 2, flood.shape[1] + 2), np.uint8)
        for point in (
                (0, 0),
                (flood.shape[1] - 1, 0),
                (0, flood.shape[0] - 1),
                (flood.shape[1] - 1, flood.shape[0] - 1)):
            if flood[point[1], point[0]] > 0:
                cv2.floodFill(flood, flood_mask, point, 0)
        enclosed_holes = flood > 0
        enclosed_count, enclosed_labels, enclosed_stats, _ = cv2.connectedComponentsWithStats(
            enclosed_holes.astype(np.uint8) * 255,
            8,
        )
        for hole_index in range(1, enclosed_count):
            hole_area = int(enclosed_stats[hole_index, cv2.CC_STAT_AREA])
            if hole_area > gray_hole_max_area:
                continue
            hole_pixels = enclosed_labels == hole_index
            tile_roi = residential_tile_mask[
                source_y:source_y + source_height,
                source_x:source_x + source_width,
            ]
            tile_hole_ratio = (
                float(np.count_nonzero(hole_pixels & tile_roi))
                / max(hole_area, 1)
            )
            # 문자/주석 구멍만 메우고 실제 목재 타일이 있는 작은 포켓이나
            # 경계 띠는 원본 주거 바닥으로 보존한다.
            if tile_hole_ratio >= 0.20:
                continue
            authoritative_roi[hole_pixels] = 255
            authoritative_hole_area += hole_area

    authoritative_gray_mask[wall_pixels | ~plan_pixels | protected_pixels] = 0
    mask = authoritative_gray_mask

    explicit_area = 0
    if explicit_mask is not None and explicit_mask.shape == mask.shape:
        explicit_area = int(np.count_nonzero(explicit_mask))
        mask[explicit_mask > 0] = 255
    rgb_range_area = int(np.count_nonzero(mask & (valid_exact.astype(np.uint8) * 255)))
    grown_area = max(
        0,
        int(np.count_nonzero(mask)) - rgb_range_area - explicit_area,
    )
    metadata = {
        "algorithm": "seeded_neutral_surface_v2",
        "region_count": len(accepted_areas),
        "area_ratio": round(float(np.count_nonzero(mask)) / max(mask.size, 1), 5),
        "minimum_area_px": RGB_RANGE_OVERLAY_MIN_AREA_PX,
        "minimum_room_area_px": RGB_RANGE_OVERLAY_MIN_AREA_PX,
        "minimum_area_ratio": 0.0,
        "minimum_density": 0.28,
        "minimum_room_gray_ratio": 0.0,
        "classified_room_count": 0,
        "wall_enclosed_gray_region_count": accepted_wall_enclosed_count,
        "explicit_non_residential_area_px": explicit_area,
        "perimeter_gray_width_px": perimeter_width,
        "perimeter_gray_region_count": perimeter_region_count,
        "perimeter_gray_added_area_px": perimeter_added_area,
        "perimeter_gray_min_seed_ratio": PERIMETER_GRAY_MIN_SEED_RATIO,
        "perimeter_gray_min_half_width_px": PERIMETER_GRAY_MIN_HALF_WIDTH_PX,
        "perimeter_gray_rejected_thin_count": perimeter_rejected_thin_count,
        "perimeter_gray_rejected_unseeded_count": perimeter_rejected_unseeded_count,
        "narrow_gray_refinement_radius_px": refinement_radius,
        "narrow_gray_refinement_added_area_px": narrow_refinement_added_area,
        "narrow_gray_refinement_trimmed_area_px": narrow_refinement_trimmed_area,
        "wall_snap_radius_px": wall_snap_radius,
        "wall_snap_added_area_px": wall_snap_added_area,
        "wall_dark_support_radius_px": wall_dark_support_radius,
        "enclosed_gray_pocket_max_area_px": pocket_max_area,
        "enclosed_gray_pocket_count": enclosed_pocket_count,
        "enclosed_gray_pocket_added_area_px": enclosed_pocket_added_area,
        "residential_tile_kernel_px": tile_kernel_size,
        "residential_tile_growth_radius_px": tile_growth_radius,
        "residential_tile_area_px": int(np.count_nonzero(residential_tile_mask)),
        "residential_tile_veto_removed_area_px": tile_veto_removed_area,
        "zone_seal_size_px": zone_seal_size,
        "gray_zone_count": gray_zone_count,
        "residential_zone_count": residential_zone_count,
        "zone_gray_added_area_px": zone_gray_added_area,
        "zone_gray_removed_area_px": zone_gray_removed_area,
        "gray_hole_max_area_px": gray_hole_max_area,
        "filled_gray_hole_count": filled_gray_hole_count,
        "filled_gray_hole_area_px": filled_gray_hole_area,
        "authoritative_source_gray_region_count": authoritative_region_count,
        "authoritative_source_gray_hole_area_px": authoritative_hole_area,
        "authoritative_source_gray_min_area_px": authoritative_min_area,
        "relaxed_connected_growth_px": grown_area,
        "rgb_159_164_min_area_px": RGB_RANGE_OVERLAY_MIN_AREA_PX,
        "rgb_159_164_region_count": rgb_range_region_count,
        "rgb_159_164_rejected_sparse_count": rejected_sparse,
        "rgb_159_164_rejected_neighbor_count": rejected_neighbor,
        "rgb_159_164_rejected_protected_count": rgb_range_rejected_protected_count,
        "rgb_159_164_veto_radius_px": RGB_RANGE_VETO_RADIUS_PX,
        "rgb_159_164_veto_min_ratio": RGB_RANGE_VETO_MIN_RATIO,
        "rgb_159_164_added_area_px": rgb_range_area,
        "rgb_159_164_expanded_area_px": max(0, int(np.count_nonzero(mask)) - rgb_range_area),
        "rejected_small_count": rejected_small,
        "rejected_sparse_count": rejected_sparse + rejected_neighbor,
    }
    return mask, metadata


def extract_non_residential_gray_mask(
        img,
        wall_mask,
        protected_mask=None,
        room_masks=None,
        explicit_mask=None):
    """벽·회색·장판의 세 증거를 결합해 비사용 공간을 분류한다.

    1. 벽은 점수가 전파될 수 없는 절대 경계다.
    2. 회색 점수는 무채색도, 중간 밝기, 국소 균일도로 계산한다.
    3. 장판 점수는 따뜻한 색상과 주변 반복 밀도로 계산한다.
    4. 벽으로 분리된 공간에서 한 증거가 확실히 우세할 때만 공간 전체를
       통일하고, 혼합 공간은 픽셀 점수를 그대로 유지한다.
    """
    height, width = img.shape[:2]
    b, g, r = [channel.astype(np.float32) for channel in cv2.split(img)]
    brightness = (b + g + r) / 3.0
    chroma = np.maximum.reduce((np.abs(r - g), np.abs(g - b), np.abs(r - b)))

    plan_pixels = np.zeros((height, width), dtype=bool)
    if room_masks:
        for room_mask in room_masks:
            if room_mask.shape == plan_pixels.shape:
                plan_pixels |= room_mask > 0
    else:
        plan_pixels[:] = True

    protected_pixels = np.zeros_like(plan_pixels)
    if protected_mask is not None and protected_mask.shape == plan_pixels.shape:
        protected_pixels = protected_mask > 0

    wall_pixels = wall_mask > 0
    wall_thickness = estimate_wall_thickness(wall_mask) if np.any(wall_mask) else 10.0
    dark_pixels = (brightness <= 90) & (chroma <= 60) & plan_pixels
    wall_support_radius = max(3, min(16, int(round(wall_thickness * 1.2))))
    wall_support = cv2.dilate(
        wall_mask,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (wall_support_radius * 2 + 1,) * 2,
        ),
    ) > 0
    barrier = wall_pixels | (dark_pixels & wall_support)
    barrier = cv2.morphologyEx(
        barrier.astype(np.uint8) * 255,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    ) > 0
    passable = plan_pixels & ~barrier & ~protected_pixels

    neutral = np.clip(1.0 - chroma / 24.0, 0.0, 1.0)
    gray_low = np.clip((brightness - 105.0) / 30.0, 0.0, 1.0)
    gray_high = np.clip((230.0 - brightness) / 25.0, 0.0, 1.0)
    gray_brightness = np.minimum(gray_low, gray_high)
    local_mean = cv2.boxFilter(brightness, cv2.CV_32F, (9, 9))
    local_square_mean = cv2.boxFilter(brightness * brightness, cv2.CV_32F, (9, 9))
    local_std = np.sqrt(np.maximum(local_square_mean - local_mean * local_mean, 0.0))
    uniformity = np.clip(1.0 - local_std / 25.0, 0.0, 1.0)
    gray_evidence = neutral * gray_brightness * (0.72 + 0.28 * uniformity)

    warmth = np.clip((r - b - 6.0) / 36.0, 0.0, 1.0)
    floor_brightness = np.minimum(
        np.clip((brightness - 120.0) / 35.0, 0.0, 1.0),
        np.clip((252.0 - brightness) / 24.0, 0.0, 1.0),
    )
    raw_floor_evidence = warmth * floor_brightness
    evidence_kernel = max(11, min(25, int(round(wall_thickness * 1.4))))
    if evidence_kernel % 2 == 0:
        evidence_kernel += 1
    floor_density = cv2.boxFilter(
        raw_floor_evidence,
        cv2.CV_32F,
        (evidence_kernel, evidence_kernel),
        borderType=cv2.BORDER_REPLICATE,
    )
    floor_evidence = 0.35 * raw_floor_evidence + 0.65 * floor_density
    gray_density = cv2.boxFilter(
        (gray_evidence >= 0.62).astype(np.float32),
        cv2.CV_32F,
        (11, 11),
        borderType=cv2.BORDER_REPLICATE,
    )
    near_wall_radius = max(3, int(round(wall_thickness)))
    near_wall = cv2.dilate(
        barrier.astype(np.uint8) * 255,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (near_wall_radius * 2 + 1,) * 2,
        ),
    ) > 0
    wall_bounded_gray = (gray_evidence >= 0.65) & near_wall & (raw_floor_evidence < 0.10)
    effective_floor_density = floor_density.copy()
    effective_floor_density[wall_bounded_gray] *= 0.15

    score = (
        1.35 * gray_evidence
        + 0.38 * gray_density
        - 1.20 * raw_floor_evidence
        - 3.20 * effective_floor_density
    )
    score[~passable] = -10.0
    raw_candidate = (score >= 0.55).astype(np.uint8) * 255
    raw_candidate = cv2.morphologyEx(
        raw_candidate,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
        borderType=cv2.BORDER_REPLICATE,
    )
    raw_candidate[~passable] = 0

    minimum_area = RGB_RANGE_OVERLAY_MIN_AREA_PX
    component_count, component_labels, component_stats, _ = cv2.connectedComponentsWithStats(
        raw_candidate,
        8,
    )
    plan_distance = cv2.distanceTransform(
        plan_pixels.astype(np.uint8) * 255,
        cv2.DIST_L2,
        5,
    )
    # 외곽 여부는 실제 도면 윤곽 바로 근처만 본다. 벽 두께의 여러 배를
    # 사용하면 외벽 안쪽의 싱크·욕실 설비까지 외곽 성분으로 오인된다.
    perimeter_distance = max(8.0, min(20.0, wall_thickness * 0.5))
    mask = np.zeros_like(raw_candidate)
    accepted_component_count = 0
    rejected_small_count = 0
    rejected_floor_neighbor_count = 0
    rejected_interior_fragment_count = 0
    for index in range(1, component_count):
        area = int(component_stats[index, cv2.CC_STAT_AREA])
        if area < minimum_area:
            rejected_small_count += 1
            continue
        component_x = int(component_stats[index, cv2.CC_STAT_LEFT])
        component_y = int(component_stats[index, cv2.CC_STAT_TOP])
        component_width = int(component_stats[index, cv2.CC_STAT_WIDTH])
        component_height = int(component_stats[index, cv2.CC_STAT_HEIGHT])
        component_slice = (
            slice(component_y, component_y + component_height),
            slice(component_x, component_x + component_width),
        )
        selected = component_labels[component_slice] == index
        half_width = float(cv2.distanceTransform(
            selected.astype(np.uint8) * 255,
            cv2.DIST_L2,
            5,
        ).max())
        if half_width < 1.9:
            rejected_small_count += 1
            continue
        gray_mean = float(np.mean(gray_evidence[component_slice][selected]))
        floor_mean = float(np.mean(floor_evidence[component_slice][selected]))
        wall_bounded_ratio = float(np.mean(wall_bounded_gray[component_slice][selected]))
        component_uniformity = float(np.mean(uniformity[component_slice][selected]))
        bounding_density = area / max(component_width * component_height, 1)
        perimeter_ratio = float(np.mean(
            plan_distance[component_slice][selected] <= perimeter_distance
        ))
        # 실제 09.74D 도면에서 욕실 설비·싱크·기호는 내부에 고립된 성분이고
        # bounding box를 듬성듬성 채운다. 외곽 띠나 큰 공용부는 이 필터에서
        # 제외하고, 작은 내부 성분만 면 밀도로 검증한다.
        if (
                area < 50000
                and perimeter_ratio < 0.08
                and bounding_density < 0.65
                and not (
                    wall_bounded_ratio >= 0.30
                    and bounding_density >= 0.45
                    and component_uniformity >= 0.50
                )):
            rejected_interior_fragment_count += 1
            continue
        ring_padding = 12
        ring_x1 = max(0, component_x - ring_padding)
        ring_y1 = max(0, component_y - ring_padding)
        ring_x2 = min(width, component_x + component_width + ring_padding)
        ring_y2 = min(height, component_y + component_height + ring_padding)
        ring_slice = (slice(ring_y1, ring_y2), slice(ring_x1, ring_x2))
        ring_component = component_labels[ring_slice] == index
        ring = cv2.dilate(
            ring_component.astype(np.uint8) * 255,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25)),
        ) > 0
        ring &= ~ring_component & plan_pixels[ring_slice] & ~barrier[ring_slice]
        ring_floor_mean = (
            float(np.mean(floor_evidence[ring_slice][ring]))
            if np.any(ring) else 0.0
        )
        if (
                area < 2500
                and ring_floor_mean >= 0.42
                and wall_bounded_ratio < 0.30):
            rejected_floor_neighbor_count += 1
            continue
        mask_roi = mask[component_slice]
        mask_roi[selected] = 255
        accepted_component_count += 1

    zone_seal_size = max(11, min(41, int(round(wall_thickness * 2.5))))
    if zone_seal_size % 2 == 0:
        zone_seal_size += 1
    sealed_barrier = cv2.morphologyEx(
        barrier.astype(np.uint8) * 255,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE,
            (zone_seal_size, zone_seal_size),
        ),
        borderType=cv2.BORDER_REPLICATE,
    ) > 0
    zone_space = (plan_pixels & ~sealed_barrier & ~protected_pixels).astype(np.uint8) * 255
    zone_count, zone_labels, zone_stats, _ = cv2.connectedComponentsWithStats(zone_space, 8)
    gray_zone_count = 0
    floor_zone_count = 0
    zone_added_area = 0
    zone_removed_area = 0
    for index in range(1, zone_count):
        area = int(zone_stats[index, cv2.CC_STAT_AREA])
        if area < minimum_area:
            continue
        selected = zone_labels == index
        gray_mean = float(np.mean(gray_evidence[selected]))
        floor_mean = float(np.mean(floor_evidence[selected]))
        gray_seed_ratio = float(np.count_nonzero(selected & (mask > 0))) / max(area, 1)
        if (
                gray_mean >= 0.58
                and floor_mean <= 0.20
                and gray_seed_ratio >= 0.35):
            added = selected & (mask == 0)
            zone_added_area += int(np.count_nonzero(added))
            mask[added] = 255
            gray_zone_count += 1
        elif (
                floor_mean >= 0.48
                and gray_seed_ratio <= 0.15
                and floor_mean >= gray_mean + 0.18):
            # 벽에 직접 붙은 고신뢰 회색 띠/삼각 포켓은 큰 주거 공간과
            # 끝점에서 연결돼도 장판 우세 판정으로 지우지 않는다.
            removed = selected & (mask > 0) & ~wall_bounded_gray
            zone_removed_area += int(np.count_nonzero(removed))
            mask[removed] = 0
            floor_zone_count += 1

    mask[~passable] = 0
    final_count, final_labels, final_stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    cleaned = np.zeros_like(mask)
    for index in range(1, final_count):
        if int(final_stats[index, cv2.CC_STAT_AREA]) >= minimum_area:
            x = int(final_stats[index, cv2.CC_STAT_LEFT])
            y = int(final_stats[index, cv2.CC_STAT_TOP])
            w = int(final_stats[index, cv2.CC_STAT_WIDTH])
            h = int(final_stats[index, cv2.CC_STAT_HEIGHT])
            component_slice = (slice(y, y + h), slice(x, x + w))
            selected = final_labels[component_slice] == index
            cleaned_roi = cleaned[component_slice]
            cleaned_roi[selected] = 255
    mask = cleaned

    # 벽 검출 마스크가 회색 구역 안쪽을 조금 침범하면 passable 단계에서
    # 그 픽셀이 빠지고 프런트 바닥 장판이 띠처럼 드러난다. 원본에서 실제
    # 회색 증거가 있고, 이미 승인된 회색 면과 같은 연결 성분인 픽셀은
    # 벽 마스크 여부와 무관하게 복원한다. 실제 검은 벽은 gray_evidence가
    # 낮으므로 이 복원 대상에 포함되지 않는다.
    source_gray_support = (
        plan_pixels
        & ~protected_pixels
        & (gray_evidence >= 0.55)
        & (raw_floor_evidence < 0.15)
    )
    support_count, support_labels, support_stats, _ = cv2.connectedComponentsWithStats(
        source_gray_support.astype(np.uint8) * 255,
        8,
    )
    recovered_wall_overlap_area = 0
    recovered_gray_component_count = 0
    for index in range(1, support_count):
        area = int(support_stats[index, cv2.CC_STAT_AREA])
        if area < 20:
            continue
        x = int(support_stats[index, cv2.CC_STAT_LEFT])
        y = int(support_stats[index, cv2.CC_STAT_TOP])
        w = int(support_stats[index, cv2.CC_STAT_WIDTH])
        h = int(support_stats[index, cv2.CC_STAT_HEIGHT])
        component_slice = (slice(y, y + h), slice(x, x + w))
        selected = support_labels[component_slice] == index
        mask_roi = mask[component_slice]
        seed_count = int(np.count_nonzero(selected & (mask_roi > 0)))
        if seed_count < min(20, max(3, int(round(area * 0.02)))):
            continue
        # 복원 범위는 실제로 벽 장벽 때문에 잘린 픽셀로만 제한한다.
        # 장판 무늬 사이의 중성 픽셀처럼 벽과 무관한 누락 후보는 되살리지 않는다.
        recovered = selected & (mask_roi == 0) & barrier[component_slice]
        recovered_area = int(np.count_nonzero(recovered))
        if recovered_area == 0:
            continue
        mask_roi[recovered] = 255
        recovered_wall_overlap_area += recovered_area
        recovered_gray_component_count += 1

    explicit_area = 0
    if explicit_mask is not None and explicit_mask.shape == mask.shape:
        explicit_area = int(np.count_nonzero(explicit_mask))
        mask[explicit_mask > 0] = 255

    exact_rgb = (
        (r >= 159) & (r <= 164)
        & (g >= 159) & (g <= 164)
        & (b >= 159) & (b <= 164)
    )
    exact_count, exact_labels, exact_stats, _ = cv2.connectedComponentsWithStats(
        exact_rgb.astype(np.uint8) * 255,
        8,
    )
    exact_region_count = sum(
        1 for index in range(1, exact_count)
        if int(exact_stats[index, cv2.CC_STAT_AREA]) >= minimum_area
    )
    exact_area = int(np.count_nonzero((mask > 0) & exact_rgb))
    protected_rejected_count = 0
    for index in range(1, exact_count):
        if int(exact_stats[index, cv2.CC_STAT_AREA]) < minimum_area:
            continue
        x = int(exact_stats[index, cv2.CC_STAT_LEFT])
        y = int(exact_stats[index, cv2.CC_STAT_TOP])
        w = int(exact_stats[index, cv2.CC_STAT_WIDTH])
        h = int(exact_stats[index, cv2.CC_STAT_HEIGHT])
        component_slice = (slice(y, y + h), slice(x, x + w))
        if np.any(
                (exact_labels[component_slice] == index)
                & protected_pixels[component_slice]):
            protected_rejected_count += 1
    total_area = int(np.count_nonzero(mask))
    metadata = {
        "algorithm": "weighted_wall_gray_floor_v3",
        "region_count": accepted_component_count,
        "area_ratio": round(total_area / max(mask.size, 1), 5),
        "minimum_area_px": minimum_area,
        "minimum_room_area_px": minimum_area,
        "minimum_area_ratio": 0.0,
        "minimum_density": 0.0,
        "minimum_room_gray_ratio": 0.0,
        "classified_room_count": gray_zone_count + floor_zone_count,
        "explicit_non_residential_area_px": explicit_area,
        "gray_weight": 1.35,
        "gray_density_weight": 0.38,
        "floor_color_weight": 1.20,
        "floor_density_weight": 3.20,
        "pixel_score_threshold": 0.55,
        "wall_support_radius_px": wall_support_radius,
        "zone_seal_size_px": zone_seal_size,
        "gray_zone_count": gray_zone_count,
        "floor_zone_count": floor_zone_count,
        "zone_gray_added_area_px": zone_added_area,
        "zone_gray_removed_area_px": zone_removed_area,
        "recovered_wall_overlap_area_px": recovered_wall_overlap_area,
        "recovered_gray_component_count": recovered_gray_component_count,
        "rejected_small_count": rejected_small_count,
        "rejected_interior_fragment_count": rejected_interior_fragment_count,
        "rejected_sparse_count": (
            rejected_small_count
            + rejected_floor_neighbor_count
            + rejected_interior_fragment_count
        ),
        "rgb_159_164_min_area_px": minimum_area,
        "rgb_159_164_region_count": exact_region_count,
        "rgb_159_164_rejected_sparse_count": rejected_small_count,
        "rgb_159_164_rejected_neighbor_count": rejected_floor_neighbor_count,
        "rgb_159_164_rejected_protected_count": protected_rejected_count,
        "rgb_159_164_veto_radius_px": RGB_RANGE_VETO_RADIUS_PX,
        "rgb_159_164_veto_min_ratio": RGB_RANGE_VETO_MIN_RATIO,
        "rgb_159_164_added_area_px": exact_area,
        "rgb_159_164_expanded_area_px": max(0, total_area - exact_area),
        "relaxed_connected_growth_px": max(0, total_area - exact_area - explicit_area),
        # 이전 디버그 소비자와의 호환 필드다.
        "perimeter_gray_added_area_px": total_area,
        "perimeter_gray_rejected_thin_count": (
            rejected_small_count
            + int(total_area == 0 and np.any(gray_evidence >= 0.62))
        ),
        "wall_enclosed_gray_region_count": gray_zone_count or accepted_component_count,
        "enclosed_gray_pocket_count": 0,
        "residential_tile_veto_removed_area_px": zone_removed_area,
        "authoritative_source_gray_region_count": accepted_component_count,
        "authoritative_source_gray_hole_area_px": zone_added_area,
    }
    return mask, metadata


def wall_bounded_interior_mask(wall_mask, wall_thickness):
    """벽 마스크를 벽 두께 기준으로 문/창 틈만 메운 뒤, 외곽에서 플러드필로 벽 안쪽 영역만 남긴다.
    이렇게 만든 영역은 벽 벡터화에 쓰인 wall_mask와 동일한 경계를 갖기 때문에
    바닥 폴리곤을 여기에 맞추면 벽과 바닥이 항상 같은 기준으로 정렬된다."""
    h, w = wall_mask.shape
    kernel_size = int(round(max(ROOM_SEAL_MIN_KERNEL, min(ROOM_SEAL_MAX_KERNEL, wall_thickness * 1.8))))
    if kernel_size % 2 == 0:
        kernel_size += 1
    seal_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    sealed_walls = cv2.morphologyEx(wall_mask, cv2.MORPH_CLOSE, seal_kernel)

    flood = sealed_walls.copy()
    ff_mask = np.zeros((h + 2, w + 2), np.uint8)
    for pt in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        if flood[pt[1], pt[0]] == 0:
            cv2.floodFill(flood, ff_mask, pt, 255)

    interior = np.zeros_like(wall_mask)
    interior[(flood == 0) & (sealed_walls == 0)] = 255
    return interior


def extract_plan_footprint_mask(img, wall_mask=None, wall_thickness=10.0):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    b, g, r = cv2.split(img)
    chroma = np.maximum.reduce([r, g, b]) - np.minimum.reduce([r, g, b])
    colored_content = (chroma >= PLAN_COLOR_CHROMA_THRESH) & (gray < PLAN_COLOR_BRIGHTNESS_MAX)
    dark_content = gray < PLAN_DARK_CONTENT_THRESH
    content = ((colored_content | dark_content) * 255).astype(np.uint8)

    content = cv2.morphologyEx(
        content,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (PLAN_CLOSE_KERNEL, PLAN_CLOSE_KERNEL)),
    )
    content = cv2.dilate(
        content,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (PLAN_DILATE_KERNEL, PLAN_DILATE_KERNEL)),
    )

    if wall_mask is not None and np.any(wall_mask):
        # 벽 벡터와 같은 기준(wall_mask)으로 안쪽 영역을 구해 합쳐두면,
        # 색 기반 콘텐츠 검출이 놓친 부분(얇은 난간선 등)도 벽 위치에 맞춰 채워진다.
        content = cv2.bitwise_or(content, wall_bounded_interior_mask(wall_mask, wall_thickness))

    contours, _ = cv2.findContours(content, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mask = np.zeros_like(gray)
    min_area = max(extract_layers.FLOOR_MIN_AREA, int(gray.size * 0.002))
    for contour in contours:
        if cv2.contourArea(contour) >= min_area:
            cv2.drawContours(mask, [contour], -1, 255, thickness=cv2.FILLED)

    if not np.any(mask):
        return extract_layers.extract_floor_mask(img, wall_mask if wall_mask is not None else np.zeros_like(gray))
    return mask


def components_to_polygons(mask, min_area):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    polygons = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        epsilon = 0.0015 * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
        if len(approx) < 3:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        polygons.append({
            "id": f"floor_{len(polygons):04d}",
            "type": "floor",
            "editable": False,
            "area_px": round(float(area), 1),
            "bbox": {"x": int(x), "y": int(y), "width": int(w), "height": int(h)},
            "points": [{"x": int(px), "y": int(py)} for px, py in approx],
        })
    polygons.sort(key=lambda item: item["area_px"], reverse=True)
    return polygons


def masks_to_polygons(masks, id_prefix, item_type, min_area):
    polygons = []
    for mask in masks:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(contour)
        if area < min_area:
            continue
        # 방 경계는 벽을 따라 정밀하게 유지해야 한다. 단순화 오차가 크면
        # 사선/오목 벽 주변에서 인접 방 바닥이 삼각형으로 침범한다.
        epsilon = 0.00035 * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
        if len(approx) < 3:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        polygons.append({
            "id": f"{id_prefix}_{len(polygons):04d}",
            "type": item_type,
            "editable": False,
            "area_px": round(float(area), 1),
            "bbox": {"x": int(x), "y": int(y), "width": int(w), "height": int(h)},
            "points": [{"x": int(px), "y": int(py)} for px, py in approx],
        })
    polygons.sort(key=lambda item: item["area_px"], reverse=True)
    return polygons


def split_floor_into_room_masks(img, floor_mask, wall_mask, wall_thickness):
    """방은 나누지 않고 서로 떨어진 평면도 덩어리만 각각 유지한다."""
    if not np.any(floor_mask):
        return []
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        floor_mask,
        8,
    )
    minimum_area = max(ROOM_MIN_AREA_PX, int(floor_mask.size * ROOM_MIN_AREA_RATIO))
    floor_components = []
    for index in range(1, component_count):
        if int(stats[index, cv2.CC_STAT_AREA]) < minimum_area:
            continue
        floor_components.append(((labels == index) * 255).astype(np.uint8))
    return floor_components or [floor_mask.copy()]


def segment_to_wall(index, segment):
    x1, y1, x2, y2, thickness = segment
    length = math.hypot(x2 - x1, y2 - y1)
    angle = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
    if angle < 5 or angle > 175:
        orientation = "horizontal"
    elif abs(angle - 90) < 5:
        orientation = "vertical"
    else:
        orientation = "diagonal"
    return {
        "id": f"wall_{index:04d}",
        "type": "wall",
        "editable": True,
        "locked": False,
        "x1": int(round(x1)),
        "y1": int(round(y1)),
        "x2": int(round(x2)),
        "y2": int(round(y2)),
        "thickness_px": round(float(thickness), 1),
        "height": DEFAULT_WALL_HEIGHT_MM,
        "length_px": round(float(length), 1),
        "angle_deg": round(float(angle), 1),
        "orientation": orientation,
        "handles": ["move", "rotate", "delete"],
    }


def editable_wall_regions_from_segments(segments, wall_mask):
    """200mm 이하 벽만 삭제 대상으로 내려주기 위한 마스크 조각 생성."""
    max_thickness_px = PARTITION_WALL_MAX_MM / FLOOR_PLAN_PIXEL_MM
    h, w = wall_mask.shape
    regions = []
    for x1, y1, x2, y2, thickness in sorted(
            segments, key=lambda s: -math.hypot(s[2] - s[0], s[3] - s[1])):
        if thickness > max_thickness_px:
            continue
        length = math.hypot(x2 - x1, y2 - y1)
        if length < 4:
            continue

        mask = np.zeros((h, w), np.uint8)
        cv2.line(
            mask,
            (int(round(x1)), int(round(y1))),
            (int(round(x2)), int(round(y2))),
            255,
            max(int(round(thickness)), 1),
        )
        mask = cv2.bitwise_and(mask, wall_mask)
        ys, xs = np.where(mask > 0)
        if xs.size == 0:
            continue

        pad = max(int(math.ceil(thickness)) + 2, 4)
        min_x = max(int(xs.min()) - pad, 0)
        max_x = min(int(xs.max()) + pad + 1, w)
        min_y = max(int(ys.min()) - pad, 0)
        max_y = min(int(ys.max()) + pad + 1, h)
        crop = mask[min_y:max_y, min_x:max_x]
        wall = segment_to_wall(len(regions), (x1, y1, x2, y2, thickness))
        wall.update({
            "id": f"editable_wall_{len(regions):04d}",
            "editable": True,
            "locked": False,
            "movable": False,
            "deletable": True,
            "source": "partition_wall_region",
            "thickness_mm": round(float(thickness * FLOOR_PLAN_PIXEL_MM), 1),
            "bbox": {
                "x": min_x,
                "y": min_y,
                "width": max_x - min_x,
                "height": max_y - min_y,
            },
            "mask": encode_png_data_uri(crop),
            "handles": ["delete"],
        })
        regions.append(wall)
    return regions


def wall_render_rects_from_mask(wall_mask):
    """3D 렌더용 벽 마스크 run을 서버에서 미리 직사각형으로 압축한다."""
    h, w = wall_mask.shape
    active = {}
    rects = []

    for y in range(h):
        row = wall_mask[y] > 0
        next_active = {}
        x = 0
        while x < w:
            while x < w and not row[x]:
                x += 1
            if x >= w:
                break
            start_x = x
            while x < w and row[x]:
                x += 1
            end_x = x
            key = (start_x, end_x)
            if key in active:
                rect = active[key]
                rect[3] += 1
            else:
                rect = [start_x, y, end_x - start_x, 1]
            next_active[key] = rect

        for key, rect in active.items():
            if key not in next_active:
                rects.append(rect)
        active = next_active

    rects.extend(active.values())
    return {
        "width": int(w),
        "height": int(h),
        "rects": rects,
    }


def build_editable_payload(
        input_path,
        output_path=None,
        debug_dir=None):
    started_at = time.perf_counter()
    img, src_json = extract_layers.load_image_from_json(str(input_path))
    height, width = img.shape[:2]

    # 설비 탐지로 방을 추론하지 않고, 구조와 원본 방 이름 레이어만
    # 산출한다. 이후 모든 좌표는 원본 이미지 픽셀 좌표를 유지한다.
    structure_started_at = time.perf_counter()
    raw_wall_mask = extract_walls.extract_wall_mask(img)
    thickness = estimate_wall_thickness(raw_wall_mask)
    structural_wall_mask, wall_cleanup_metadata = remove_fine_wall_strokes(
        raw_wall_mask,
        thickness,
    )
    wall_mask, wall_regularization_metadata = regularize_wall_mask(
        structural_wall_mask,
        thickness,
    )
    wall_regularization_metadata.update(wall_cleanup_metadata)
    floor_mask = extract_plan_footprint_mask(img, wall_mask, thickness)

    segments = vectorize(wall_mask, thickness, debug_dir=debug_dir)
    walls = [
        segment_to_wall(i, seg)
        for i, seg in enumerate(sorted(segments, key=lambda s: -math.hypot(s[2] - s[0], s[3] - s[1])))
    ]
    editable_wall_regions = editable_wall_regions_from_segments(segments, wall_mask)
    wall_render_rects = wall_render_rects_from_mask(wall_mask)
    floors = components_to_polygons(floor_mask, extract_layers.FLOOR_MIN_AREA)
    room_masks = split_floor_into_room_masks(img, floor_mask, wall_mask, thickness)
    rooms = masks_to_polygons(
        room_masks,
        "room",
        "room",
        max(ROOM_MIN_AREA_PX, int(floor_mask.size * ROOM_MIN_AREA_RATIO)),
    )
    room_labels, room_text_metadata = recognize_room_labels(img)
    labeled_residential_mask = build_labeled_residential_mask(
        room_labels,
        room_masks,
        img.shape,
        img=img,
        wall_mask=wall_mask,
    )
    labeled_non_residential_mask = build_labeled_non_residential_mask(
        room_labels,
        room_masks,
        img.shape,
    )
    non_residential_mask, non_residential_metadata = extract_non_residential_gray_mask(
        img,
        wall_mask,
        protected_mask=labeled_residential_mask,
        room_masks=room_masks,
        explicit_mask=labeled_non_residential_mask,
    )
    structure_ms = round((time.perf_counter() - structure_started_at) * 1000)
    payload = copy.deepcopy(src_json)
    payload["detections"] = []
    attrs = dict(payload.get("@attributes", {}))
    attrs["width"] = width
    attrs["height"] = height
    payload["@attributes"] = attrs
    payload["unit"] = "pixel"
    # 편집 화면은 floors/rooms 폴리곤으로 바닥을 다시 그리므로 원본과 동일한
    # 6MB 내외 floor PNG를 응답에 중복 포함하지 않는다.
    payload["image"] = {"@attributes": {"width": width, "height": height}}
    payload["walls"] = walls
    payload["editable_wall_regions"] = editable_wall_regions
    payload["wall_render_rects"] = wall_render_rects
    payload["floors"] = floors
    payload["rooms"] = rooms
    payload["room_labels"] = room_labels
    client_wall_mask = resize_mask_for_client(wall_mask)
    client_non_residential_mask = resize_mask_for_client(non_residential_mask)
    payload["layers"] = {
        "source": os.path.basename(str(input_path)),
        "mode": "editable_floorplan",
        "render_mode": "reconstructed_vectors",
        "wall_source": "extract_walls.extract_wall_mask",
        "floor_source": "extract_plan_footprint_mask",
        "room_source": "split_floor_into_room_masks",
        "wall_count": len(walls),
        "wall_regularization": wall_regularization_metadata,
        "editable_wall_count": len(editable_wall_regions),
        "floor_count": len(floors),
        "room_count": len(rooms),
        "room_text": room_text_metadata,
        "non_residential": non_residential_metadata,
        "processing_ms": {
            "structure": structure_ms,
            "total": round((time.perf_counter() - started_at) * 1000),
        },
        "estimated_wall_thickness_px": round(float(thickness), 1),
        # 프런트는 wall_mask와 non_residential_mask 두 래스터를 사용한다.
        # 나머지 검증용 이미지는 --debug-dir 사용 시 파일로만 생성한다.
        "wall_mask": encode_png_data_uri(client_wall_mask),
        "non_residential_mask": encode_png_data_uri(client_non_residential_mask),
    }

    if debug_dir:
        Path(debug_dir).mkdir(parents=True, exist_ok=True)
        floor_only, _floor_alpha = extract_layers.cut(img, floor_mask)
        cv2.imwrite(str(Path(debug_dir) / "walls_mask.png"), wall_mask)
        cv2.imwrite(str(Path(debug_dir) / "walls_mask_raw.png"), raw_wall_mask)
        cv2.imwrite(str(Path(debug_dir) / "walls_mask_structural.png"), structural_wall_mask)
        cv2.imwrite(str(Path(debug_dir) / "floor_mask.png"), floor_mask)
        cv2.imwrite(str(Path(debug_dir) / "floor_only.png"), floor_only)
        room_vis = np.full_like(img, 255)
        palette = [
            (220, 130, 70), (70, 160, 220), (120, 190, 110), (190, 130, 210),
            (215, 180, 80), (80, 190, 180), (210, 110, 130), (150, 170, 230),
        ]
        for i, room_mask in enumerate(room_masks):
            room_vis[room_mask > 0] = palette[i % len(palette)]
        room_vis[wall_mask > 0] = (70, 80, 95)
        cv2.imwrite(str(Path(debug_dir) / "rooms_mask.png"), room_vis)
        cv2.imwrite(str(Path(debug_dir) / "editable_overlay.png"),
                    raw_mask_overlay(img, wall_mask, floor_mask))
        cv2.imwrite(str(Path(debug_dir) / "non_residential_mask.png"), non_residential_mask)
        cv2.imwrite(str(Path(debug_dir) / "labeled_residential_mask.png"), labeled_residential_mask)
        cv2.imwrite(
            str(Path(debug_dir) / "labeled_non_residential_mask.png"),
            labeled_non_residential_mask,
        )

    # PNG 인코딩과 디버그 산출까지 포함한 Python 처리 시간이다. 파일 쓰기와
    # Spring의 JSON 직렬화/전송 시간은 서버 계층에서 별도로 발생한다.
    payload["layers"]["processing_ms"]["total"] = round(
        (time.perf_counter() - started_at) * 1000
    )

    if output_path:
        with Path(output_path).open("w", encoding="utf-8") as f:
            # 브라우저가 읽는 API 산출물이므로 들여쓰기를 제거한다. 사람이
            # 확인해야 할 때는 jq를 사용하고 전송/파싱 바이트 수를 우선 줄인다.
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    return payload


def main():
    parser = argparse.ArgumentParser(description="벽은 extract_walls, 바닥은 extract_layers로 산출한 편집형 평면도 JSON 생성")
    parser.add_argument("input", help="base64 PNG가 들어있는 입력 JSON")
    parser.add_argument("-o", "--output", default=None, help="출력 JSON 경로")
    parser.add_argument("--debug-dir", default=None, help="검증용 레이어 이미지 출력 폴더")
    # 이미 실행 중인 이전 Spring 서버가 설비 탐지 옵션을 계속
    # 넘겨도 벡터화가 실패하지 않도록 인자만 수용하고 사용하지 않는다.
    parser.add_argument("--detector-model", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--detector-confidence", type=float, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--fixture-template-dir", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--fixture-template-threshold", type=float, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    out = args.output or str(Path(args.input).with_name(Path(args.input).stem + "_editable.json"))
    payload = build_editable_payload(
        args.input,
        out,
        args.debug_dir,
    )
    print(f"완료: {out}")
    print(f"  walls: {len(payload['walls'])}")
    print(f"  floors: {len(payload['floors'])}")
    print(f"  rooms: {len(payload.get('rooms', []))}")
    room_text = payload.get("layers", {}).get("room_text", {})
    print(f"  room labels: {room_text.get('label_count', 0)}")


if __name__ == "__main__":
    main()
