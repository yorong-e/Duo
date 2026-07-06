# -*- coding: utf-8 -*-
"""
평면도 JSON(base64 PNG 내장)에서 벽면만 추출하는 스크립트

원리:
  도면에서 벽은 '두꺼운' 검정 영역이고, 치수선/문/가구/텍스트는 얇은 선이다.
  1. JSON에서 base64 PNG 디코딩
  2. 이진화(어두운 픽셀 = 도면 요소)
  3. 모폴로지 opening(15x15) → 벽 두께보다 얇은 요소 전부 제거 (벽 시드)
  4. 제한된 지오데식 재구성(8회) → opening으로 둥글어진 모서리를 원형 그대로 복원
  5. 재구성 중 벽에 붙어 새어나온 얇은 가지 제거(7x7 opening)
  6. 면적 필터로 잔여 잡음 성분 제거
  7. 마스크를 1px 팽창해 안티앨리어싱 경계까지 포함한 뒤 원본 픽셀 그대로 복사

사용법:
  python extract_walls.py input.json [출력폴더]

출력:
  walls_only.png        흰 배경 + 원본 벽 픽셀 그대로
  walls_transparent.png 투명 배경 RGBA
  walls_mask.png        벽 마스크 (흰색=벽)
  overlay.png           검증용 오버레이 (빨강=추출된 벽)
  walls.json            입력과 동일한 포맷의 JSON (벽만 남은 이미지 내장)
"""
import sys, os, json, base64
import cv2
import numpy as np

# ── 튜닝 파라미터 ─────────────────────────────────────────
BIN_THRESH   = 128   # 이진화 임계값 (이보다 어두우면 도면 요소)
WALL_KERNEL  = 15    # 벽 최소 두께(px). 이보다 얇은 선은 벽이 아님
RECON_ITERS  = 8     # 모서리 복원 반복 횟수 (대략 WALL_KERNEL/2)
STUB_KERNEL  = 7     # 재구성 시 새어나온 얇은 가지 제거 커널
MIN_AREA     = 2000  # 벽 성분 최소 면적(px²)


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
    png_bytes = base64.b64decode(href.split(',', 1)[1])
    arr = np.frombuffer(png_bytes, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR), data


def extract_wall_mask(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, BIN_THRESH, 255, cv2.THRESH_BINARY_INV)

    # 벽 시드: 두꺼운 영역만 생존
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (WALL_KERNEL, WALL_KERNEL))
    seed = cv2.morphologyEx(binary, cv2.MORPH_OPEN, k)

    # 제한된 지오데식 재구성으로 모서리 원형 복원
    k3 = np.ones((3, 3), np.uint8)
    recon = seed.copy()
    for _ in range(RECON_ITERS):
        recon = cv2.dilate(recon, k3)
        recon = cv2.bitwise_and(recon, binary)

    # 복원 중 새어나온 얇은 가지 제거
    sk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (STUB_KERNEL, STUB_KERNEL))
    recon = cv2.morphologyEx(recon, cv2.MORPH_OPEN, sk)

    # 면적 필터
    n, labels, stats, _ = cv2.connectedComponentsWithStats(recon, 8)
    mask = np.zeros_like(recon)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= MIN_AREA:
            mask[labels == i] = 255
    return mask


def main():
    json_path = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else '.'
    os.makedirs(out_dir, exist_ok=True)

    img, src_json = load_image_from_json(json_path)
    mask = extract_wall_mask(img)

    # 안티앨리어싱 경계 포함
    mask_d = cv2.dilate(mask, np.ones((3, 3), np.uint8))

    # 흰 배경 + 원본 벽 픽셀 그대로
    walls_only = np.full_like(img, 255)
    walls_only[mask_d > 0] = img[mask_d > 0]

    # 투명 배경 RGBA
    b, g, r = cv2.split(img)
    rgba = cv2.merge([b, g, r, mask_d])

    # 검증 오버레이
    overlay = img.copy()
    overlay[mask > 0] = (0, 0, 255)

    cv2.imwrite(f'{out_dir}/walls_only.png', walls_only)
    cv2.imwrite(f'{out_dir}/walls_transparent.png', rgba)
    cv2.imwrite(f'{out_dir}/walls_mask.png', mask)
    cv2.imwrite(f'{out_dir}/overlay.png', overlay)

    # 입력과 동일 포맷의 JSON으로도 출력
    ok, buf = cv2.imencode('.png', walls_only)
    href = 'data:image/png;base64,' + base64.b64encode(buf.tobytes()).decode()
    image = src_json.setdefault('image', {})
    attrs = image.setdefault('@attributes', {})
    attrs['xlink:href'] = href
    image['href'] = href
    with open(f'{out_dir}/walls.json', 'w', encoding='utf-8') as f:
        json.dump(src_json, f, ensure_ascii=False)

    print('완료:', out_dir)


if __name__ == '__main__':
    main()
