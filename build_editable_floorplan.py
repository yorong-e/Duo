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


def build_labeled_residential_mask(room_labels, room_masks, shape):
    """OCR 공간명 주변을 보호하되 큰 혼합 공간 전체는 보호하지 않는다."""
    height, width = shape[:2]
    protected = np.zeros((height, width), np.uint8)
    whole_room_types = {
        "bathroom", "kitchen", "bedroom", "living_room", "balcony",
        "dress_room", "utility", "storage", "study", "alpha_room",
        "explicit_area",
    }
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
            room_area = int(np.count_nonzero(best_room))
            room_type = str(label.get("room_type") or "")
            # 명확한 주거 공간이면서 전체 도면의 10% 이하로 정상 분리된
            # 경우에만 방 전체를 보호한다. 현관·복도 또는 큰 혼합 마스크는
            # 라벨 주변만 보호해 인접 엘리베이터/공용부가 함께 제외되지 않는다.
            if room_type in whole_room_types and room_area <= height * width * 0.10:
                protected[best_room > 0] = 255
            else:
                if room_type == "kitchen":
                    padding_x = max(int((x2 - x1) * 5.0), 80)
                    padding_y = max(int((y2 - y1) * 5.0), 80)
                elif room_type == "bathroom":
                    padding_x = max(int((x2 - x1) * 3.0), 60)
                    padding_y = max(int((y2 - y1) * 3.0), 60)
                elif room_type == "balcony":
                    padding_x = max(int((x2 - x1) * 3.5), 70)
                    padding_y = max(int((y2 - y1) * 3.5), 70)
                else:
                    padding_x = max(int((x2 - x1) * 0.75), 12)
                    padding_y = max(int((y2 - y1) * 0.75), 12)
                local_x1 = max(x1 - padding_x, 0)
                local_y1 = max(y1 - padding_y, 0)
                local_x2 = min(x2 + padding_x, width)
                local_y2 = min(y2 + padding_y, height)
                protected[local_y1:local_y2, local_x1:local_x2] = 255
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


def extract_non_residential_gray_mask(
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
    eligible = plan_pixels & ~dilated_walls & ~protected_pixels

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
    candidate = (
        (chroma <= 24)
        & (brightness >= 105)
        & (brightness <= 215)
        & eligible
    ).astype(np.uint8) * 255
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
    for index in range(1, component_count):
        selected = labels == index
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < RGB_RANGE_OVERLAY_MIN_AREA_PX:
            rejected_small += 1
            continue
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        density = area / max(width * height, 1)
        seed_count = int(np.count_nonzero(selected & (strong_gray | valid_exact)))
        seed_ratio = seed_count / max(area, 1)
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
        solid_surface = area >= 2500 and (
            density >= 0.75
            or (density >= 0.45 and seed_ratio >= 0.85)
        )
        if (
                not solid_surface
                and veto_count >= RGB_RANGE_VETO_MIN_PIXELS
                and veto_ratio >= RGB_RANGE_VETO_MIN_RATIO):
            rejected_neighbor += 1
            continue
        mask[selected] = 255
        accepted_areas.append(area)

    before_cleanup = int(np.count_nonzero(mask))
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)),
        borderType=cv2.BORDER_REPLICATE,
    )
    mask[~plan_pixels | dilated_walls | protected_pixels] = 0
    cleaned_count, cleaned_labels, cleaned_stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    cleaned = np.zeros_like(mask)
    for index in range(1, cleaned_count):
        if int(cleaned_stats[index, cv2.CC_STAT_AREA]) >= RGB_RANGE_OVERLAY_MIN_AREA_PX:
            cleaned[cleaned_labels == index] = 255
    mask = cleaned

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
        "explicit_non_residential_area_px": explicit_area,
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
