# -*- coding: utf-8 -*-
"""
평면도 JSON(base64 PNG 내장)에서 벽 레이어와 바닥 레이어를 분리 추출하는 스크립트

벽 추출 원리 (extract_walls.py와 동일):
  벽 = 두꺼운 검정 영역. opening으로 얇은 선 제거 후 제한된 재구성으로 원형 복원.

바닥 추출 원리:
  1. 구조선(벽·창호·문 등 어두운 선, gray<190)을 경계로 삼는다
  2. 이미지 테두리에서 flood fill → 도면 외부 공간 판별
  3. 내부(방) = 빈 공간 중 외부가 아닌 곳 = 벽으로 둘러싸인 영역
     · 방끼리는 문 개구부로 연결되고, 발코니는 창호선으로 별도 폐합
     · 외부 복도/공용부는 flood fill로 외부 처리되어 자동 배제
  4. closing으로 방 안의 가구선·바닥 무늬선·텍스트를 바닥 영역에 흡수
  5. 벽 마스크 제거 → 바닥 마스크 완성
  6. 바닥 픽셀의 색조로 재질 분류:
     · 마루(목재): R-B ≥ 10 (웜톤)
     · 욕실 타일: G-R ≥ 3 (그린톤)
     · 기타 타일: 나머지 (무채/연한 웜톤 — 현관·발코니·대피공간 등)

사용법:
  python extract_layers.py input.json [출력폴더]

출력:
  walls_only.png / walls_transparent.png / walls_mask.png   벽 레이어
  floor_only.png / floor_transparent.png / floor_mask.png   바닥 레이어
  floor_types.png                                            재질 분류 시각화
  floor_wood.png / floor_tile_bath.png / floor_tile_etc.png  재질별 바닥
  overlay.png                                                검증용 (벽=빨강, 바닥=파랑 반투명)
"""
import sys, os, json, base64
import cv2
import numpy as np

from extract_walls import extract_wall_mask as extract_walls_mask

# ── 벽 파라미터 ──────────────────────────────
BIN_THRESH   = 128
WALL_KERNEL  = 15
RECON_ITERS  = 8
STUB_KERNEL  = 7
WALL_MIN_AREA = 2000
# ── 바닥 파라미터 ────────────────────────────
STRUCT_THRESH   = 190   # 구조선 임계값 (바닥 채움색보다 어두운 선)
FILL_CLOSE      = 41    # 방 안 가구선/치수선/문 스윙 등 흡수용 closing 커널 (벽 마스크로 재클리핑되므로 크게 잡아도 안전)
FLOOR_MIN_AREA  = 5000  # 바닥 성분 최소 면적
WOOD_RB         = 10    # R-B가 이 이상이면 마루(웜톤)
BATH_GR         = 3     # G-R이 이 이상이면 욕실 타일(그린톤)


def find_image_href(obj):
    if isinstance(obj, str) and obj.startswith('data:image'):
        return obj
    if isinstance(obj, dict):
        for key in ('xlink:href', 'href', 'data', 'image_base64', 'base64'):
            value = obj.get(key)
            if isinstance(value, str) and value.startswith('data:image'):
                return value
        for value in obj.values():
            found = find_image_href(value)
            if found:
                return found
    if isinstance(obj, list):
        for value in obj:
            found = find_image_href(value)
            if found:
                return found
    return None


def load_image_from_json(json_path):
    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)
    href = find_image_href(data)
    if not href:
        raise ValueError('JSON 안에서 data:image base64 문자열을 찾지 못했습니다.')
    arr = np.frombuffer(base64.b64decode(href.split(',', 1)[1]), np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR), data


def extract_wall_mask(img):
    """벽 산출 기준은 extract_walls.py의 전용 로직을 사용한다."""
    return extract_walls_mask(img)


def extract_floor_mask(img, wall_mask):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape

    # 구조선을 경계로 외부/내부 판별
    structure = cv2.dilate(((gray < STRUCT_THRESH) * 255).astype(np.uint8),
                           np.ones((3, 3), np.uint8))
    free = cv2.bitwise_not(structure)
    ff = free.copy()
    ffmask = np.zeros((H + 2, W + 2), np.uint8)
    for pt in [(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)]:
        if ff[pt[1], pt[0]] == 255:
            cv2.floodFill(ff, ffmask, pt, 128)
    outside = ((ff == 128) * 255).astype(np.uint8)
    inside = cv2.bitwise_and(free, cv2.bitwise_not(outside))
    inside[outside > 0] = 0
    inside[wall_mask > 0] = 0

    # 방 안의 선·텍스트를 바닥에 흡수 (벽/외부 제거로 생긴 실선 틈도 함께 메움)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (FILL_CLOSE, FILL_CLOSE))
    inside = cv2.morphologyEx(inside, cv2.MORPH_CLOSE, k)
    # closing이 벽/외부 쪽으로 번진 부분은 다시 제거
    inside[outside > 0] = 0
    inside[wall_mask > 0] = 0

    # 면적 필터 (치수 텍스트 고리 등 잔여물 제거)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(inside, 8)
    mask = np.zeros_like(inside)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= FLOOR_MIN_AREA:
            mask[labels == i] = 255
    return mask


def classify_floor(img, floor_mask):
    """바닥 픽셀 색조 기반 재질 분류. 반환: 라벨맵 (0=없음 1=마루 2=욕실타일 3=기타타일)"""
    b, g, r = [c.astype(np.int16) for c in cv2.split(img)]
    rb, gr = r - b, g - r
    label = np.zeros(floor_mask.shape, np.uint8)
    fm = floor_mask > 0
    label[fm] = 3                          # 기본: 기타 타일
    label[fm & (gr >= BATH_GR)] = 2        # 욕실 타일(그린톤)
    label[fm & (rb >= WOOD_RB)] = 1        # 마루(웜톤)
    label = cv2.medianBlur(label, 15)      # 무늬선 주변 잡음 평활화
    label[~fm] = 0
    return label


def cut(img, mask, dilate1px=True):
    """마스크 영역의 원본 픽셀을 흰 배경 위에 그대로 복사"""
    m = cv2.dilate(mask, np.ones((3, 3), np.uint8)) if dilate1px else mask
    out = np.full_like(img, 255)
    out[m > 0] = img[m > 0]
    return out, m


def main():
    json_path = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else '.'
    os.makedirs(out_dir, exist_ok=True)

    img, src_json = load_image_from_json(json_path)
    wall_mask = extract_wall_mask(img)
    floor_mask = extract_floor_mask(img, wall_mask)
    types = classify_floor(img, floor_mask)

    # 벽 레이어
    walls_only, wm = cut(img, wall_mask)
    cv2.imwrite(f'{out_dir}/walls_only.png', walls_only)
    cv2.imwrite(f'{out_dir}/walls_mask.png', wall_mask)
    cv2.imwrite(f'{out_dir}/walls_transparent.png',
                cv2.merge([*cv2.split(img), wm]))

    # 바닥 레이어
    floor_only, fm = cut(img, floor_mask)
    cv2.imwrite(f'{out_dir}/floor_only.png', floor_only)
    cv2.imwrite(f'{out_dir}/floor_mask.png', floor_mask)
    cv2.imwrite(f'{out_dir}/floor_transparent.png',
                cv2.merge([*cv2.split(img), fm]))

    # 재질별 바닥
    for val, name in [(1, 'floor_wood'), (2, 'floor_tile_bath'), (3, 'floor_tile_etc')]:
        m = ((types == val) * 255).astype(np.uint8)
        out, _ = cut(img, m, dilate1px=False)
        cv2.imwrite(f'{out_dir}/{name}.png', out)

    # 재질 분류 시각화
    vis = np.full_like(img, 255)
    vis[types == 1] = (60, 130, 220)    # 마루=주황갈색
    vis[types == 2] = (120, 200, 120)   # 욕실타일=초록
    vis[types == 3] = (200, 160, 120)   # 기타타일=하늘색
    vis[wall_mask > 0] = (60, 60, 60)   # 벽=진회색
    cv2.imwrite(f'{out_dir}/floor_types.png', vis)

    # 검증 오버레이 (벽=빨강, 바닥=파랑 반투명)
    ov = img.copy()
    ov[wall_mask > 0] = (0, 0, 255)
    blue = ov.copy(); blue[floor_mask > 0] = (255, 100, 0)
    ov = cv2.addWeighted(ov, 0.55, blue, 0.45, 0)
    cv2.imwrite(f'{out_dir}/overlay.png', ov)

    print('완료:', out_dir)
    for v, n in [(1, '마루'), (2, '욕실타일'), (3, '기타타일')]:
        print(f'  {n}: {(types == v).sum():,} px')


if __name__ == '__main__':
    main()
