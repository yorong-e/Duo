#!/usr/bin/env python3
"""
평면도 JSON에서 벽체만 추출하는 스크립트 (v3).

입력 JSON 구조 (SVG image 노드를 JSON으로 변환한 형태):
{
  "@attributes": {"width": ..., "height": ...},
  "image": {"@attributes": {"xlink:href": "data:image/png;base64,...."}}
}

원리 (4단계):
  평면도에서 벽 = 두껍고 "무채색으로 어두운" 채움.
  치수선/글자/가구/창호 = 얇은 선, 욕실 타일/바닥재 = 어두워도 색이 있거나
  벽보다 밝은 회색.

  [0단계: 색 인지 이진화]
    단순 밝기 임계가 아니라, "무채색이면서 어두운" 픽셀만 벽 후보로 채택.
    갈색 계열 어두운 타일(R-B 차이 큼)은 여기서 배제됨.
    아주 어두운(black_thresh 이하) 픽셀은 색과 무관하게 항상 채택.

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
      ③ 1단계 벽 네트워크에 인접한
    조각만 벽으로 인정. 얇은 벽을 최대한 보존하는 방향이 기본이며,
    이로 인해 창호(창문) 선이 드물게 섞일 수 있음 → 그 경우에만
    --thin-ratio 0.3 옵션으로 대표 벽 두께 대비 필터를 켤 수 있음.

  [3단계: 회색 채움 제거]
    벽 심의 대표 밝기 D를 자동 측정한 뒤, D보다 확연히 밝은(D+margin 초과)
    무채색 회색 "덩어리"(샤워부스 바닥, 회색 타일 등)를 제거.
    얇은 벽 가장자리의 안티앨리어싱 픽셀은 침식 테스트(blob_erode)로
    보호되어 벽은 깨지지 않음.

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


def binarize_color_aware(img_bgr: np.ndarray, dark_thresh: int = 128,
                         black_thresh: int = 70, color_tol: int = 8) -> np.ndarray:
    """색 인지 이진화: '무채색이면서 어두운' 픽셀만 255로.

    dark_thresh:  이보다 밝으면 무조건 배제 (기존 밝기 임계).
    black_thresh: 이보다 어두우면 색과 무관하게 항상 채택 (진한 검정).
    color_tol:    RGB 채널 간 최대 편차 허용치. 이를 넘으면 '색이 있는'
                  픽셀(갈색 타일, 목재 바닥 등)로 보고 배제.
    """
    g = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    b, gr, r = cv2.split(img_bgr.astype(np.int16))
    cdiff = np.maximum(np.maximum(abs(r - gr), abs(gr - b)), abs(r - b))
    keep = (g <= dark_thresh) & ((cdiff <= color_tol) | (g <= black_thresh))
    return (keep.astype(np.uint8)) * 255


def remove_gray_fills(mask: np.ndarray, gray: np.ndarray, margin: int = 30,
                      blob_erode: int = 8, min_keep: int = 500) -> np.ndarray:
    """벽보다 확연히 밝은 무채색 회색 '덩어리'를 마스크에서 제거.

    벽 심(능선)의 대표 밝기 D를 자동 측정하고, D+margin보다 밝은 픽셀 중
    blob_erode(px) 침식에서 살아남는 덩어리(회색 타일, 샤워부스 바닥 등)만
    제거. 얇은 벽 가장자리의 안티앨리어싱은 침식에서 사라지므로 보호됨.
    """
    dt = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    dil = cv2.dilate(dt, np.ones((3, 3), np.float32))
    ridge = (dt >= dil - 1e-6) & (dt > 1) & (mask > 0)
    if not ridge.any():
        return mask
    D = float(np.median(gray[ridge]))
    bright = ((gray > D + margin) & (mask > 0)).astype(np.uint8) * 255
    ke = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * blob_erode + 1,) * 2)
    seed = cv2.erode(bright, ke)
    # seed를 bright 범위 안에서 재구성해 덩어리 전체를 복원
    kd = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    prev = np.zeros_like(seed)
    cur = seed
    while not np.array_equal(cur, prev):
        prev = cur
        cur = cv2.bitwise_and(cv2.dilate(cur, kd, iterations=8), bright)
    out = cv2.bitwise_and(mask, cv2.bitwise_not(cur))
    # 제거로 생긴 부스러기 정리
    n, lbl, st, _ = cv2.connectedComponentsWithStats(out)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] < min_keep:
            out[lbl == i] = 0
    return out


def _ridge_half_thickness(mask: np.ndarray) -> float:
    """마스크 획의 대표(중앙값) 반두께. 능선(스켈레톤 근사) 위 거리값의 중앙값."""
    dt = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    dil = cv2.dilate(dt, np.ones((3, 3), np.float32))
    ridge = dt[(dt >= dil - 1e-6) & (dt > 1)]
    return float(np.median(ridge)) if len(ridge) else 0.0


def extract_walls(img_bgr: np.ndarray, half_thick: int = 7, min_area: int = 5000,
                  rescue_dist: int = 4,
                  thin_half: int = 2, thin_min_area: int = 500,
                  thin_elong: float = 3.0, thin_rectfill: float = 0.5,
                  thin_ratio: float = 0.0, attach_dist: int = 20,
                  dark_thresh: int = 128, black_thresh: int = 70, color_tol: int = 8,
                  gray_margin: int = 30, gray_blob_erode: int = 8) -> np.ndarray:
    """벽 마스크(255=벽) 반환.

    half_thick:    [1단계] 이보다 반두께가 얇은 획 제거. 두꺼운 벽 기준.
    min_area:      [1단계] 이보다 작은 조각 제거 (가전 심볼, 굵은 글자 등).
    rescue_dist:   [1b단계] 채택된 벽에서 이 거리(px) 안의 두꺼운 조각은
                   면적과 무관하게 구제 (조인트로 쪼개진 벽 대응).
    thin_half:     [2단계] 얇은 벽 후보의 최소 반두께. 치수선(1~2px)은 탈락.
    thin_min_area: [2단계] 얇은 벽 후보 최소 면적.
    thin_elong:    [2단계] 최소 세장비(길이/폭). 벽은 길쭉한 막대 형태.
    thin_rectfill: [2단계] 회전 최소사각형 채움비 하한.
    thin_ratio:    [2단계] 대표 벽 반두께 대비 최소 비율. 기본 0(비활성).
                   얇은 벽을 최대한 보존하는 것이 기본 동작이며, 창호(창문)
                   선이 벽으로 섞여 들어올 때만 0.3 정도로 올려서 쓰세요.
                   (단, 올리면 창호와 두께가 비슷한 얇은 벽도 함께 빠질 수
                   있는 트레이드오프가 있음)
    attach_dist:   [2단계] 벽 네트워크 인접 판정 거리(px).
    """
    # ---------- 0단계: 색 인지 이진화 ----------
    binimg = binarize_color_aware(img_bgr, dark_thresh, black_thresh, color_tol)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

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

    walls = cv2.bitwise_or(thick_walls, thin_walls)

    # ---------- 3단계: 벽보다 밝은 회색 채움 덩어리 제거 ----------
    walls = remove_gray_fills(walls, gray, margin=gray_margin,
                              blob_erode=gray_blob_erode, min_keep=thin_min_area)
    return walls


def extract_wall_mask(img_bgr: np.ndarray) -> np.ndarray:
    """extract_walls()의 기본 파라미터 호출 별칭 (다른 스크립트와의 하위 호환용)."""
    return extract_walls(img_bgr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path", type=Path)
    ap.add_argument("out_dir", type=Path, nargs="?", default=Path("."))
    ap.add_argument("--half-thick", type=int, default=7)
    ap.add_argument("--min-area", type=int, default=5000)
    ap.add_argument("--rescue-dist", type=int, default=4)
    ap.add_argument("--thin-ratio", type=float, default=0.0,
                    help="대표 벽 두께 대비 얇은 벽 최소 비율. 기본 0(비활성). "
                         "창호선이 벽에 섞이면 0.3 정도로 올려서 사용")
    ap.add_argument("--black-thresh", type=int, default=70,
                    help="이보다 어두우면 색과 무관하게 벽 후보로 채택")
    ap.add_argument("--color-tol", type=int, default=8,
                    help="무채색 판정 허용치. 타일이 벽에 섞이면 낮추세요")
    ap.add_argument("--gray-margin", type=int, default=30,
                    help="벽 심 밝기 대비 이만큼 밝은 회색 덩어리는 제거")
    args = ap.parse_args()

    img = decode_image_from_json(args.json_path)
    walls = extract_walls(img, half_thick=args.half_thick, min_area=args.min_area,
                          rescue_dist=args.rescue_dist, thin_ratio=args.thin_ratio,
                          black_thresh=args.black_thresh, color_tol=args.color_tol,
                          gray_margin=args.gray_margin)

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
