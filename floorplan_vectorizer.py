#!/usr/bin/env python3
"""
평면도 JSON → 벽체 벡터 라인 추출 자동화 파이프라인 (v2)

v1(Canny+Hough)의 문제를 보완:
  - 두꺼운 벽의 양쪽 테두리가 이중 선으로 검출되던 것 → 벽 마스크에서 중심선 1개만 추출
  - 치수 텍스트/바닥 텍스처 노이즈 → 어두운 픽셀 임계 + 작은 컴포넌트 제거로 벽만 분리
  - 결과 검증 불가 → 마스크 커버리지(%) 자동 리포트 + 원본 위 오버레이 이미지 생성

입력: base64 PNG가 내장된 평면도 JSON (또는 PNG/JPG 직접 입력)
처리:
  1단계: 벽체 추출 (흑백 변환 → 어두운 픽셀 마스크 → 노이즈 제거)
  2단계: 벡터화 (수평/수직 분리 → 컴포넌트별 중심선 → 병합/코너 스냅, 사선은 Hough 보완)
  3단계: JSON 출력 (좌표 + 벽 두께 + 커버리지 리포트)

사용법:
  python floorplan_vectorizer.py input.json [-o output.json] [--debug-dir dir]
"""

import argparse
import base64
import json
import math
import os
import re
import sys

import cv2
import numpy as np


# ──────────────────────────────────────────────
# 0단계: 입력 로드 (JSON에서 base64 이미지 추출)
# ──────────────────────────────────────────────
def find_data_uri(obj):
    if isinstance(obj, str):
        return obj if obj.startswith("data:image") else None
    if isinstance(obj, dict):
        for v in obj.values():
            found = find_data_uri(v)
            if found:
                return found
    if isinstance(obj, list):
        for v in obj:
            found = find_data_uri(v)
            if found:
                return found
    return None


def load_image(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        uri = find_data_uri(data)
        if uri is None:
            sys.exit("[오류] JSON 안에서 data:image base64 문자열을 찾지 못했습니다.")
        b64 = re.sub(r"^data:image/\w+;base64,", "", uri)
        arr = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    else:
        img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        sys.exit(f"[오류] 이미지를 디코딩할 수 없습니다: {path}")
    return img


def load_json_payload(path):
    if os.path.splitext(path)[1].lower() != ".json":
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ──────────────────────────────────────────────
# 1단계: 벽체 마스크 추출
# ──────────────────────────────────────────────
def extract_wall_mask(img, dark_thresh=100, min_area_ratio=5e-5, debug_dir=None):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # 벽체 = 도면에서 가장 어두운 요소. 그리드선/바닥 텍스처(중간톤)는 배제
    mask = (gray < dark_thresh).astype(np.uint8) * 255

    # 치수 텍스트, 눈금 같은 작은 덩어리 제거
    min_area = int(h * w * min_area_ratio)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    clean = np.zeros_like(mask)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            clean[labels == i] = 255

    # 벽 두께 추정 (거리 변환 상위 90퍼센타일 x2)
    dist = cv2.distanceTransform(clean, cv2.DIST_L2, 5)
    nz = dist[dist > 0]
    thickness = float(np.percentile(nz, 90) * 2) if nz.size else 10.0

    if debug_dir:
        cv2.imwrite(os.path.join(debug_dir, "1_gray.png"), gray)
        cv2.imwrite(os.path.join(debug_dir, "2_wall_mask.png"), clean)
    return clean, thickness


# ──────────────────────────────────────────────
# 2단계: 벡터화 (중심선 추출)
# ──────────────────────────────────────────────
def vectorize(mask, thickness, debug_dir=None):
    klen = max(int(thickness * 2), 40)  # 이 길이 이상 이어진 것만 벽으로 인정

    kh = cv2.getStructuringElement(cv2.MORPH_RECT, (klen, 1))
    kv = cv2.getStructuringElement(cv2.MORPH_RECT, (1, klen))
    hmask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kh)
    vmask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kv)

    segs = (_components_to_centerlines(hmask, True, klen)
            + _components_to_centerlines(vmask, False, klen))

    # 수평/수직으로 설명되지 않은 잔여 영역에서 사선 벽 보완 (Hough)
    residual = cv2.subtract(mask, cv2.bitwise_or(hmask, vmask))
    residual = cv2.morphologyEx(
        residual, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=2)
    raw = cv2.HoughLinesP(residual, 1, np.pi / 180, 80,
                          minLineLength=klen * 2, maxLineGap=int(thickness))
    if raw is not None:
        for l in raw:
            x1, y1, x2, y2 = (int(v) for v in l[0])
            ang = abs(math.degrees(math.atan2(y2 - y1, x2 - x1))) % 180
            if 10 < ang < 80 or 100 < ang < 170:  # 진짜 사선만
                segs.append((x1, y1, x2, y2, thickness))

    segs = merge_collinear(segs, gap=int(thickness * 1.5))
    segs = snap_corners(segs, snap_dist=thickness * 1.2)

    if debug_dir:
        cv2.imwrite(os.path.join(debug_dir, "3_hmask.png"), hmask)
        cv2.imwrite(os.path.join(debug_dir, "4_vmask.png"), vmask)
    return segs


def _components_to_centerlines(m, horizontal, klen):
    """오리엔테이션별 마스크의 각 연결 컴포넌트 → 중심선 세그먼트 (x1,y1,x2,y2,thickness)"""
    segs = []
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    for i in range(1, n):
        x, y, w, h, _area = stats[i]
        if horizontal:
            if w < klen:
                continue
            segs.append((x, y + h // 2, x + w, y + h // 2, h))
        else:
            if h < klen:
                continue
            segs.append((x + w // 2, y, x + w // 2, y + h, w))
    return segs


def merge_collinear(segs, gap):
    """같은 축 위에서 겹치거나 gap 이내로 가까운 세그먼트 병합."""
    horiz, vert, diag = {}, {}, []
    for x1, y1, x2, y2, t in segs:
        if y1 == y2:
            horiz.setdefault(round(y1 / gap), []).append([x1, y1, x2, y2, t])
        elif x1 == x2:
            vert.setdefault(round(x1 / gap), []).append([x1, y1, x2, y2, t])
        else:
            diag.append((x1, y1, x2, y2, t))

    def merge_axis(groups, horizontal):
        out = []
        for group in groups.values():
            group.sort(key=(lambda s: s[0]) if horizontal else (lambda s: s[1]))
            cur = group[0]
            for s in group[1:]:
                a, b = (0, 2) if horizontal else (1, 3)
                if s[a] <= cur[b] + gap:
                    cur[b] = max(cur[b], s[b])
                    cur[4] = max(cur[4], s[4])
                else:
                    out.append(tuple(cur))
                    cur = s
            out.append(tuple(cur))
        return out

    return merge_axis(horiz, True) + merge_axis(vert, False) + diag


def snap_corners(segs, snap_dist):
    """수평-수직 벽이 만나는 코너에서 끝점을 서로 맞닿게 연장/정렬."""
    segs = [list(s) for s in segs]
    for i, a in enumerate(segs):
        for b in segs:
            if a is b:
                continue
            a_h = a[1] == a[3]
            b_h = b[1] == b[3]
            if a_h == b_h:
                continue
            h, v = (a, b) if a_h else (b, a)
            # 수직벽 x가 수평벽 끝점 근처 & 수평벽 y가 수직벽 범위 근처면 스냅
            for xi in (0, 2):
                if (abs(h[xi] - v[0]) <= snap_dist
                        and min(v[1], v[3]) - snap_dist <= h[1] <= max(v[1], v[3]) + snap_dist):
                    h[xi] = v[0]
            for yi in (1, 3):
                if (abs(v[yi] - h[1]) <= snap_dist
                        and min(h[0], h[2]) - snap_dist <= v[0] <= max(h[0], h[2]) + snap_dist):
                    v[yi] = h[1]
    return [tuple(s) for s in segs]


# ──────────────────────────────────────────────
# 3단계: JSON 출력 + 검증
# ──────────────────────────────────────────────
def coverage(segs, mask):
    """추출한 세그먼트(두께 반영)가 원본 벽 마스크를 얼마나 설명하는지 %"""
    canvas = np.zeros_like(mask)
    for x1, y1, x2, y2, t in segs:
        cv2.line(canvas, (int(x1), int(y1)), (int(x2), int(y2)), 255, max(int(t), 3))
    wall_px = (mask > 0).sum()
    if wall_px == 0:
        return 0.0
    return ((canvas > 0) & (mask > 0)).sum() / wall_px * 100


def build_output(segs, img, source, cov):
    h, w = img.shape[:2]
    walls = []
    for i, (x1, y1, x2, y2, t) in enumerate(
            sorted(segs, key=lambda s: -math.hypot(s[2] - s[0], s[3] - s[1]))):
        length = math.hypot(x2 - x1, y2 - y1)
        ang = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180
        orientation = ("horizontal" if ang < 5 or ang > 175
                       else "vertical" if abs(ang - 90) < 5 else "diagonal")
        walls.append({
            "id": f"wall_{i:04d}",
            "x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2),
            "thickness_px": round(float(t), 1),
            "length_px": round(length, 1),
            "angle_deg": round(ang, 1),
            "orientation": orientation,
        })
    return {
        "source": os.path.basename(source),
        "image_size": {"width": w, "height": h},
        "unit": "pixel",
        "wall_count": len(walls),
        "mask_coverage_percent": round(cov, 1),
        "walls": walls,
    }


def merge_vectors_into_payload(payload, vector_result):
    merged = dict(payload)
    image_size = vector_result.get("image_size", {})
    attrs = dict(merged.get("@attributes", {}))
    attrs.setdefault("width", image_size.get("width"))
    attrs.setdefault("height", image_size.get("height"))
    merged["@attributes"] = attrs
    merged["unit"] = "pixel"
    merged["walls"] = vector_result["walls"]
    merged["vectorization"] = {
        "source": vector_result["source"],
        "image_size": image_size,
        "wall_count": vector_result["wall_count"],
        "mask_coverage_percent": vector_result["mask_coverage_percent"],
        "generator": "floorplan_vectorizer.py",
    }
    return merged


def save_overlay(img, segs, path):
    vis = img.copy()
    for x1, y1, x2, y2, _t in segs:
        color = (0, 0, 255) if y1 == y2 else (255, 0, 0) if x1 == x2 else (0, 180, 0)
        cv2.line(vis, (int(x1), int(y1)), (int(x2), int(y2)), color, 8)
    cv2.imwrite(path, vis)


def main():
    ap = argparse.ArgumentParser(description="평면도 JSON → 벽체 벡터 추출 v2")
    ap.add_argument("input")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--vectors-only", action="store_true",
                    help="원본 JSON에 병합하지 않고 벽 벡터 결과만 저장합니다.")
    ap.add_argument("--dark-thresh", type=int, default=100,
                    help="벽으로 볼 어두움 임계값 (기본 100)")
    ap.add_argument("--debug-dir", default=None)
    args = ap.parse_args()

    if args.debug_dir:
        os.makedirs(args.debug_dir, exist_ok=True)
    payload = load_json_payload(args.input)
    default_suffix = "_walls.json" if args.vectors_only or payload is None else "_vectorized.json"
    out_path = args.output or os.path.splitext(args.input)[0] + default_suffix

    print("[0/3] 입력 로드 중...")
    img = load_image(args.input)
    print(f"      이미지 크기: {img.shape[1]}x{img.shape[0]}")

    print("[1/3] 벽체 마스크 추출...")
    mask, thickness = extract_wall_mask(img, args.dark_thresh, debug_dir=args.debug_dir)
    print(f"      추정 벽 두께: {thickness:.0f}px")

    print("[2/3] 벡터화 (중심선 추출)...")
    segs = vectorize(mask, thickness, debug_dir=args.debug_dir)
    print(f"      벽체 세그먼트: {len(segs)}개")

    print("[3/3] JSON 출력 + 검증...")
    cov = coverage(segs, mask)
    print(f"      마스크 커버리지: {cov:.1f}% (추출된 벡터가 실제 벽을 설명하는 비율)")
    vector_result = build_output(segs, img, args.input, cov)
    if payload is not None and not args.vectors_only:
        result = merge_vectors_into_payload(payload, vector_result)
    else:
        result = vector_result
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"      저장 완료: {out_path}")

    if args.debug_dir:
        save_overlay(img, segs, os.path.join(args.debug_dir, "5_overlay.png"))
        print(f"      오버레이 저장: {args.debug_dir}/5_overlay.png")


if __name__ == "__main__":
    main()
