#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_walls.py와 extract_layers.py 결과를 사용해 앱에서 편집 가능한 평면도 JSON을 만든다.

출력 JSON:
  - image.href: 미리보기용 바닥 레이어 PNG
  - walls[]: 각 벽을 개별 선택/이동/회전/삭제할 수 있는 중심선 벡터
  - floors[]: 재구성 화면에 그릴 바닥 폴리곤
  - layers: 원본/바닥/벽/마스크 레이어 메타데이터

사용법:
  python build_editable_floorplan.py input.json -o src/main/resources/static/static/floorplan.json
  python build_editable_floorplan.py input.json --debug-dir out_layers
"""

import argparse
import base64
import copy
import json
import math
import os
from pathlib import Path

import cv2
import numpy as np

import extract_layers
import extract_walls
from floorplan_vectorizer import vectorize


DEFAULT_WALL_HEIGHT_MM = 2400
ROOM_MIN_AREA_RATIO = 0.0012
ROOM_STRUCT_THRESH = 130
ROOM_SEAL_MIN_KERNEL = 17
ROOM_SEAL_MAX_KERNEL = 61
PLAN_DARK_CONTENT_THRESH = 170
PLAN_COLOR_CHROMA_THRESH = 14
PLAN_COLOR_BRIGHTNESS_MAX = 245
PLAN_CLOSE_KERNEL = 55
PLAN_DILATE_KERNEL = 3


def encode_png_data_uri(img):
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG 인코딩에 실패했습니다.")
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


def estimate_wall_thickness(mask):
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    nz = dist[dist > 0]
    return float(np.percentile(nz, 90) * 2) if nz.size else 10.0


def rgba_from_mask(img, mask):
    dilated = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    b, g, r = cv2.split(img)
    return cv2.merge([b, g, r, dilated])


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
        epsilon = 0.0015 * cv2.arcLength(contour, True)
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
    floor = floor_mask > 0
    if not np.any(floor):
        return []

    kernel_size = int(round(max(ROOM_SEAL_MIN_KERNEL, min(ROOM_SEAL_MAX_KERNEL, wall_thickness * 1.8))))
    if kernel_size % 2 == 0:
        kernel_size += 1
    seal_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    structure = ((gray < ROOM_STRUCT_THRESH) * 255).astype(np.uint8)
    structure[floor_mask == 0] = 0
    obstacles = cv2.bitwise_or(wall_mask, structure)
    sealed_walls = cv2.morphologyEx(obstacles, cv2.MORPH_CLOSE, seal_kernel)
    sealed_walls = cv2.dilate(sealed_walls, np.ones((3, 3), np.uint8))

    seeds = floor_mask.copy()
    seeds[sealed_walls > 0] = 0
    min_area = max(extract_layers.FLOOR_MIN_AREA, int(floor_mask.size * ROOM_MIN_AREA_RATIO))
    n, seed_labels, stats, _ = cv2.connectedComponentsWithStats(seeds, 8)

    valid_seeds = np.full_like(seeds, 255)
    valid_count = 0
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            valid_seeds[seed_labels == i] = 0
            valid_count += 1

    if valid_count == 0:
        return [floor_mask]

    _, labels = cv2.distanceTransformWithLabels(
        valid_seeds,
        cv2.DIST_L2,
        cv2.DIST_MASK_5,
        labelType=cv2.DIST_LABEL_CCOMP,
    )
    labels[floor_mask == 0] = 0

    room_masks = []
    for label in range(1, int(labels.max()) + 1):
        mask = ((labels == label) * 255).astype(np.uint8)
        if int((mask > 0).sum()) >= min_area:
            room_masks.append(mask)
    return room_masks


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


def build_editable_payload(input_path, output_path=None, debug_dir=None):
    img, src_json = extract_layers.load_image_from_json(str(input_path))
    height, width = img.shape[:2]

    wall_mask = extract_walls.extract_wall_mask(img)
    thickness = estimate_wall_thickness(wall_mask)
    floor_mask = extract_plan_footprint_mask(img, wall_mask, thickness)
    floor_only, floor_alpha = extract_layers.cut(img, floor_mask)

    segments = vectorize(wall_mask, thickness, debug_dir=debug_dir)
    walls = [
        segment_to_wall(i, seg)
        for i, seg in enumerate(sorted(segments, key=lambda s: -math.hypot(s[2] - s[0], s[3] - s[1])))
    ]
    floors = components_to_polygons(floor_mask, extract_layers.FLOOR_MIN_AREA)
    room_masks = []
    rooms = []

    payload = copy.deepcopy(src_json)
    attrs = dict(payload.get("@attributes", {}))
    attrs["width"] = width
    attrs["height"] = height
    payload["@attributes"] = attrs
    payload["unit"] = "pixel"
    payload["image"] = {
        "@attributes": {"width": width, "height": height},
        "href": encode_png_data_uri(floor_only),
    }
    payload["walls"] = walls
    payload["floors"] = floors
    payload["rooms"] = rooms
    payload["layers"] = {
        "source": os.path.basename(str(input_path)),
        "mode": "editable_floorplan",
        "render_mode": "reconstructed_vectors",
        "wall_source": "extract_walls.extract_wall_mask",
        "floor_source": "extract_plan_footprint_mask",
        "room_source": None,
        "wall_count": len(walls),
        "floor_count": len(floors),
        "room_count": len(rooms),
        "estimated_wall_thickness_px": round(float(thickness), 1),
        "wall_mask": encode_png_data_uri(wall_mask),
        "floor_mask": encode_png_data_uri(floor_mask),
        "wall_transparent": encode_png_data_uri(rgba_from_mask(img, wall_mask)),
        "floor_transparent": encode_png_data_uri(cv2.merge([*cv2.split(img), floor_alpha])),
    }

    if debug_dir:
        Path(debug_dir).mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(Path(debug_dir) / "walls_mask.png"), wall_mask)
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
        overlay = img.copy()
        overlay[wall_mask > 0] = (0, 0, 255)
        blue = overlay.copy()
        blue[floor_mask > 0] = (255, 100, 0)
        overlay = cv2.addWeighted(overlay, 0.58, blue, 0.42, 0)
        for wall in walls:
            cv2.line(
                overlay,
                (wall["x1"], wall["y1"]),
                (wall["x2"], wall["y2"]),
                (0, 255, 255),
                max(int(wall["thickness_px"] // 2), 3),
            )
        cv2.imwrite(str(Path(debug_dir) / "editable_overlay.png"), overlay)

    if output_path:
        with Path(output_path).open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    return payload


def main():
    parser = argparse.ArgumentParser(description="벽은 extract_walls, 바닥은 extract_layers로 산출한 편집형 평면도 JSON 생성")
    parser.add_argument("input", help="base64 PNG가 들어있는 입력 JSON")
    parser.add_argument("-o", "--output", default=None, help="출력 JSON 경로")
    parser.add_argument("--debug-dir", default=None, help="검증용 레이어 이미지 출력 폴더")
    args = parser.parse_args()

    out = args.output or str(Path(args.input).with_name(Path(args.input).stem + "_editable.json"))
    payload = build_editable_payload(args.input, out, args.debug_dir)
    print(f"완료: {out}")
    print(f"  walls: {len(payload['walls'])}")
    print(f"  floors: {len(payload['floors'])}")
    print(f"  rooms: {len(payload.get('rooms', []))}")


if __name__ == "__main__":
    main()
