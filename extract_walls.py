#!/usr/bin/env python3
"""
평면도 JSON에서 벽체만 추출하는 스크립트 (v3).

입력 JSON 구조 (SVG image 노드를 JSON으로 변환한 형태):
{
  "@attributes": {"width": ..., "height": ...},
  "image": {"@attributes": {"xlink:href": "data:image/png;base64,...."}}
}

원리 (3단계):
  평면도에서 벽 = 두꺼운 검은 채움, 나머지(치수선/글자/가구/창호) = 얇은 선.

  [1단계: 두꺼운 벽]
    이진화 → 열림(opening)으로 얇은 요소 제거 → 작은 조각 제거.
    ※ 재구성(reconstruction)을 쓰지 않는 이유: 벽에 붙은 치수선을 타고
      번져서 얇은 선까지 되살아나는 부작용이 있음.

  [1b단계: 조인트 조각 구제]
    도면에 따라 벽 안에 흰 조인트 선이 있어 벽이 잘게 쪼개지는데,
    이때 min_area에 걸려 탈락한 두꺼운 조각이라도 이미 채택된 벽에서
    rescue_dist(px) 이내로 붙어 있으면 벽으로 구제 (안정될 때까지 반복).
    가전 심볼처럼 벽에서 떨어진 덩어리는 구제되지 않음.

  [2단계: 얇은 칸막이벽 복원]
    1단계에서 함께 지워진 얇은 벽(욕실 칸막이 등)을 되살리는 단계.
    아주 얇은 선만 제거한 후보 중에서
      ① 길쭉하고(세장비 ≥ thin_elong, 회전 사각형 기준 → 대각 벽 대응)
      ② 채움비가 높고(직선/대각 막대 형태)
      ③ 1단계 벽 네트워크에 인접하며
      ④ 도면의 대표 벽 두께 대비 충분히 두꺼운(비율 ≥ thin_ratio)
    조각만 벽으로 인정. ④가 핵심: 창호(창문) 선은 벽 대비 훨씬 얇아서
    도면마다 벽 두께가 달라도 자동으로 걸러짐.

사용법:
  python3 extract_walls.py input.json [출력디렉토리] [--half-thick 7] ...

출력:
  <이름>_walls.png     : 벽만 남긴 이미지 (흰 배경, 검은 벽)
  <이름>_walls_mask.png: 벽 마스크 (검은 배경, 흰 벽) — 후처리용
  <이름>_overlay.png   : 원본 위에 벽을 빨간색으로 표시한 검증용 이미지
"""
import argparse
import base64
import json
import re
from pathlib import Path

import cv2
import numpy as np


def decode_image_from_json(json_path: Path) -> np.ndarray:
    """JSON 안의 base64 data URI를 디코딩해 BGR 이미지로 반환."""
    data = json.loads(json_path.read_text(encoding="utf-8"))

    def find_href(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("xlink:href", "href") and isinstance(v, str) and v.startswith("data:image"):
                    return v
                found = find_href(v)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = find_href(item)
                if found:
                    return found
        return None

    href = find_href(data)
    if not href:
        raise ValueError("JSON 안에서 data:image base64 데이터를 찾지 못했습니다.")

    m = re.match(r"data:image/[\w+.-]+;base64,(.*)", href, re.S)
    raw = base64.b64decode(m.group(1))
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("이미지 디코딩 실패")
    return img


def _ridge_half_thickness(mask: np.ndarray) -> float:
    """마스크 획의 대표(중앙값) 반두께. 능선(스켈레톤 근사) 위 거리값의 중앙값."""
    dt = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    dil = cv2.dilate(dt, np.ones((3, 3), np.float32))
    ridge = dt[(dt >= dil - 1e-6) & (dt > 1)]
    return float(np.median(ridge)) if len(ridge) else 0.0


def extract_walls(gray: np.ndarray, half_thick: int = 7, min_area: int = 5000,
                  rescue_dist: int = 4,
                  thin_half: int = 2, thin_min_area: int = 500,
                  thin_elong: float = 3.0, thin_rectfill: float = 0.5,
                  thin_ratio: float = 0.3, attach_dist: int = 20) -> np.ndarray:
    """벽 마스크(255=벽) 반환.

    half_thick:    [1단계] 이보다 반두께가 얇은 획 제거. 두꺼운 벽 기준.
    min_area:      [1단계] 이보다 작은 조각 제거 (가전 심볼, 굵은 글자 등).
    rescue_dist:   [1b단계] 채택된 벽에서 이 거리(px) 안의 두꺼운 조각은
                   면적과 무관하게 구제 (조인트로 쪼개진 벽 대응).
    thin_half:     [2단계] 얇은 벽 후보의 최소 반두께. 치수선(1~2px)은 탈락.
    thin_min_area: [2단계] 얇은 벽 후보 최소 면적.
    thin_elong:    [2단계] 최소 세장비(길이/폭). 벽은 길쭉한 막대 형태.
    thin_rectfill: [2단계] 회전 최소사각형 채움비 하한.
    thin_ratio:    [2단계] 대표 벽 반두께 대비 최소 비율. 창호선 배제의 핵심.
                   놓치는 얇은 벽이 있으면 낮추고(예: 0.2),
                   창호선이 섞이면 높이세요(예: 0.35).
    attach_dist:   [2단계] 벽 네트워크 인접 판정 거리(px).
    """
    _, binimg = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY_INV)

    # ---------- 1단계: 두꺼운 벽 ----------
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * half_thick + 1,) * 2)
    opened = cv2.morphologyEx(binimg, cv2.MORPH_OPEN, k)
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(opened)
    thick_walls = np.zeros_like(opened)
    small_thick = []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            thick_walls[lbl == i] = 255
        elif stats[i, cv2.CC_STAT_AREA] >= 500:
            small_thick.append(i)

    # ---------- 1b단계: 조인트로 쪼개진 벽 조각 구제 ----------
    kr = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * rescue_dist + 1,) * 2)
    changed = True
    while changed:
        changed = False
        near = cv2.dilate(thick_walls, kr)
        for i in list(small_thick):
            if cv2.bitwise_and(((lbl == i).astype(np.uint8)) * 255, near).any():
                thick_walls[lbl == i] = 255
                small_thick.remove(i)
                changed = True

    # 대표 벽 반두께 추정 (도면마다 벽 두께가 달라도 2단계 기준이 자동 적응)
    dom_half = _ridge_half_thickness(thick_walls) or half_thick * 2

    # ---------- 2단계: 얇은 칸막이벽 복원 ----------
    kt = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * thin_half + 1,) * 2)
    thin_cand = cv2.morphologyEx(binimg, cv2.MORPH_OPEN, kt)
    thin_cand = cv2.bitwise_and(thin_cand, cv2.bitwise_not(thick_walls))

    ka = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * attach_dist + 1,) * 2)
    near = cv2.dilate(thick_walls, ka)

    n2, lbl2, st2, _ = cv2.connectedComponentsWithStats(thin_cand)
    thin_walls = np.zeros_like(opened)
    for i in range(1, n2):
        if st2[i, cv2.CC_STAT_AREA] < thin_min_area:
            continue
        m = (lbl2 == i).astype(np.uint8)
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        pts = np.vstack([c.reshape(-1, 2) for c in cnts])
        (_, _), (rw, rh), _ = cv2.minAreaRect(pts)
        if min(rw, rh) < 1:
            continue
        elong = max(rw, rh) / min(rw, rh)
        rectfill = st2[i, cv2.CC_STAT_AREA] / (rw * rh)
        touches = cv2.bitwise_and(m * 255, near).any()
        rhalf = _ridge_half_thickness(m * 255)
        if (elong >= thin_elong and rectfill >= thin_rectfill and touches
                and rhalf >= thin_ratio * dom_half):
            thin_walls[lbl2 == i] = 255

    return cv2.bitwise_or(thick_walls, thin_walls)


def extract_wall_mask(img: np.ndarray) -> np.ndarray:
    """기존 build_editable_floorplan.py/extract_layers.py 연동용 함수명."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return extract_walls(gray)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path", type=Path)
    ap.add_argument("out_dir", type=Path, nargs="?", default=Path("."))
    ap.add_argument("--half-thick", type=int, default=7)
    ap.add_argument("--min-area", type=int, default=5000)
    ap.add_argument("--rescue-dist", type=int, default=4)
    ap.add_argument("--thin-ratio", type=float, default=0.3,
                    help="대표 벽 두께 대비 얇은 벽 최소 비율 (창호 배제 기준)")
    args = ap.parse_args()

    img = decode_image_from_json(args.json_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    walls = extract_walls(gray, half_thick=args.half_thick, min_area=args.min_area,
                          rescue_dist=args.rescue_dist, thin_ratio=args.thin_ratio)

    stem = args.json_path.stem
    args.out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.out_dir / f"{stem}_walls.png"), 255 - walls)
    cv2.imwrite(str(args.out_dir / f"{stem}_walls_mask.png"), walls)
    overlay = img.copy()
    overlay[walls > 0] = (0, 0, 255)
    blended = cv2.addWeighted(img, 0.5, overlay, 0.5, 0)
    cv2.imwrite(str(args.out_dir / f"{stem}_overlay.png"), blended)

    ratio = (walls > 0).sum() / walls.size * 100
    print(f"완료: 벽 픽셀 비율 {ratio:.2f}% / 출력 → {args.out_dir}")


if __name__ == "__main__":
    main()
