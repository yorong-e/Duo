from __future__ import annotations

import argparse
import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


@dataclass(frozen=True)
class DetectorConfig:
    """도면마다 조정 가능한 영상 처리 파라미터."""

    canny_threshold1: int = 50
    canny_threshold2: int = 150
    blur_kernel_size: int = 5
    morph_kernel_size: int = 3
    morph_iterations: int = 1
    axis_kernel_scale: int = 40
    min_axis_kernel_size: int = 25
    contour_epsilon_ratio: float = 0.01
    min_contour_area: float = 25.0
    wall_buffer_px: float = 2.0
    min_intersection_area: float = 1.0
    overlay_alpha: float = 0.45


class FloorplanCollisionDetector:
    """
    JSON에 포함된 base64 평면도 이미지를 분석해 구조물 간 간섭 영역을 찾는다.

    기본 입력은 다음 두 형태를 모두 지원한다.
    - {"image": {"href": "data:image/png;base64,..."}}
    - {"base64": "..."}
    """

    def __init__(self, config: DetectorConfig | None = None) -> None:
        self.config = config or DetectorConfig()

    def analyze_json_file(
        self,
        json_path: str | Path,
        overlay_output_path: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        """JSON 파일을 읽어 간섭 리스트를 반환하고, 필요하면 시각화 이미지를 저장한다."""
        with Path(json_path).open("r", encoding="utf-8") as f:
            payload = json.load(f)
        return self.analyze_payload(payload, overlay_output_path=overlay_output_path)

    def analyze_payload(
        self,
        payload: dict[str, Any],
        overlay_output_path: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        """이미 로드된 JSON dict를 분석한다."""
        image = self.decode_image_from_payload(payload)
        collisions, overlay = self.analyze_image(image)

        if overlay_output_path:
            output_path = Path(overlay_output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(output_path), overlay)

        return collisions

    def decode_image_from_payload(self, payload: dict[str, Any]) -> np.ndarray:
        """JSON 내부에서 base64 문자열을 찾아 OpenCV BGR 이미지로 디코딩한다."""
        encoded = self._find_base64_image(payload)
        if not encoded:
            raise ValueError("JSON payload에서 base64 이미지 데이터를 찾지 못했습니다.")

        if "," in encoded and encoded.strip().lower().startswith("data:"):
            encoded = encoded.split(",", 1)[1]

        image_bytes = base64.b64decode(encoded, validate=False)
        image_array = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("base64 데이터가 OpenCV 이미지로 디코딩되지 않았습니다.")
        return image

    def analyze_image(self, image: np.ndarray) -> tuple[list[dict[str, Any]], np.ndarray]:
        """
        OpenCV 이미지에서 구조물 윤곽을 추출하고 Shapely 교차 연산을 수행한다.

        반환값:
        - collisions: 간섭 좌표/면적 리스트
        - overlay: 원본 위에 간섭 영역을 붉게 표시한 BGR 이미지
        """
        binary, edges = self._preprocess(image)
        contours = self._extract_contours(binary, edges)
        polygons = self._contours_to_polygons(contours)
        collisions, geometries = self._find_intersections(polygons)
        overlay = self.draw_collision_overlay(image, geometries)
        return collisions, overlay

    def draw_collision_overlay(
        self,
        image: np.ndarray,
        geometries: Iterable[BaseGeometry],
    ) -> np.ndarray:
        """간섭 geometry들을 원본 이미지 위에 붉은색 반투명 마스크로 합성한다."""
        overlay = image.copy()
        mask = np.zeros(image.shape[:2], dtype=np.uint8)

        for geometry in geometries:
            for polygon in self._iter_polygons(geometry):
                points = np.array(polygon.exterior.coords, dtype=np.int32)
                if len(points) >= 3:
                    cv2.fillPoly(mask, [points], 255)

        red_layer = np.zeros_like(image)
        red_layer[:, :] = (0, 0, 255)
        highlighted = cv2.addWeighted(
            image,
            1.0,
            red_layer,
            self.config.overlay_alpha,
            0,
        )
        overlay[mask > 0] = highlighted[mask > 0]
        return overlay

    def _preprocess(self, image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """이진화와 Canny Edge를 함께 사용해 벽체/구조선 후보를 만든다."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        kernel_size = self._odd_kernel_size(self.config.blur_kernel_size)
        blurred = cv2.GaussianBlur(gray, (kernel_size, kernel_size), 0)

        # 밝은 배경의 검은 도면선이 흰색 전경이 되도록 역이진화한다.
        _, binary = cv2.threshold(
            blurred,
            0,
            255,
            cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU,
        )

        edges = cv2.Canny(
            blurred,
            self.config.canny_threshold1,
            self.config.canny_threshold2,
        )

        morph_kernel = np.ones(
            (
                self._odd_kernel_size(self.config.morph_kernel_size),
                self._odd_kernel_size(self.config.morph_kernel_size),
            ),
            np.uint8,
        )
        binary = cv2.morphologyEx(
            binary,
            cv2.MORPH_CLOSE,
            morph_kernel,
            iterations=self.config.morph_iterations,
        )
        return binary, edges

    def _extract_contours(
        self,
        binary: np.ndarray,
        edges: np.ndarray,
    ) -> list[np.ndarray]:
        """이진화 결과와 edge 결과를 합쳐 객체 경계 Contour를 검출한다."""
        axis_contours = self._extract_axis_contours(binary)
        if len(axis_contours) >= 2:
            return axis_contours

        combined = cv2.bitwise_or(binary, edges)
        contours, _ = cv2.findContours(
            combined,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        return list(contours)

    def _extract_axis_contours(self, binary: np.ndarray) -> list[np.ndarray]:
        """
        수평/수직 구조선을 분리해 교차 구조물도 별도 contour로 잡는다.

        일반 contour 검출은 서로 닿거나 겹친 구조물을 하나의 덩어리로 합치는 경향이 있다.
        평면도 벽체는 대부분 직교하므로 방향성 morphology를 먼저 적용해 개별 구조 후보를
        분리한 뒤 Shapely 교차 연산에 넘긴다.
        """
        height, width = binary.shape[:2]
        horizontal_size = max(self.config.min_axis_kernel_size, width // self.config.axis_kernel_scale)
        vertical_size = max(self.config.min_axis_kernel_size, height // self.config.axis_kernel_scale)

        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (horizontal_size, 1))
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, vertical_size))

        horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
        vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)

        contours: list[np.ndarray] = []
        for mask in (horizontal, vertical):
            found, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            contours.extend(found)
        return contours

    def _contours_to_polygons(self, contours: Iterable[np.ndarray]) -> list[Polygon]:
        """OpenCV contour를 Shapely Polygon으로 변환한다."""
        polygons: list[Polygon] = []

        for contour in contours:
            if cv2.contourArea(contour) < self.config.min_contour_area:
                continue

            perimeter = cv2.arcLength(contour, closed=True)
            epsilon = self.config.contour_epsilon_ratio * perimeter
            approx = cv2.approxPolyDP(contour, epsilon, closed=True)
            points = approx.reshape(-1, 2)

            # 얇은 선이나 작은 객체는 점이 부족할 수 있어 최소 외접 사각형으로 보정한다.
            if len(points) < 3:
                rect = cv2.minAreaRect(contour)
                points = cv2.boxPoints(rect).astype(np.int32)

            polygon = Polygon([(float(x), float(y)) for x, y in points])
            polygon = self._make_valid_polygon(polygon)
            if polygon.is_empty or polygon.area < self.config.min_contour_area:
                continue

            if self.config.wall_buffer_px > 0:
                polygon = polygon.buffer(self.config.wall_buffer_px)

            if not polygon.is_empty:
                polygons.extend(self._iter_polygons(polygon))

        return polygons

    def _find_intersections(
        self,
        polygons: list[Polygon],
    ) -> tuple[list[dict[str, Any]], list[BaseGeometry]]:
        """모든 Polygon 쌍의 교차 영역을 계산한다."""
        collisions: list[dict[str, Any]] = []
        geometries: list[BaseGeometry] = []

        for i, first in enumerate(polygons):
            for j in range(i + 1, len(polygons)):
                second = polygons[j]
                if not first.bounds or not second.bounds:
                    continue
                if not first.intersects(second):
                    continue

                intersection = first.intersection(second)
                if intersection.is_empty or intersection.area < self.config.min_intersection_area:
                    continue

                geometries.append(intersection)
                collisions.append(
                    {
                        "polygon_a_index": i,
                        "polygon_b_index": j,
                        "area": float(intersection.area),
                        "bbox": [float(v) for v in intersection.bounds],
                        "centroid": [
                            float(intersection.centroid.x),
                            float(intersection.centroid.y),
                        ],
                        "coordinates": self._geometry_coordinates(intersection),
                    }
                )

        return collisions, geometries

    def _geometry_coordinates(self, geometry: BaseGeometry) -> list[list[list[float]]]:
        """Polygon/MultiPolygon을 JSON 직렬화 가능한 좌표 배열로 변환한다."""
        return [
            [[float(x), float(y)] for x, y in polygon.exterior.coords]
            for polygon in self._iter_polygons(geometry)
        ]

    def _iter_polygons(self, geometry: BaseGeometry) -> list[Polygon]:
        """여러 Shapely geometry 타입에서 Polygon만 꺼낸다."""
        if isinstance(geometry, Polygon):
            return [geometry]
        if isinstance(geometry, MultiPolygon):
            return list(geometry.geoms)
        if isinstance(geometry, GeometryCollection):
            polygons: list[Polygon] = []
            for item in geometry.geoms:
                polygons.extend(self._iter_polygons(item))
            return polygons
        return []

    def _make_valid_polygon(self, polygon: Polygon) -> BaseGeometry:
        """자가 교차 등으로 invalid한 polygon을 가능한 범위에서 보정한다."""
        if polygon.is_valid:
            return polygon
        fixed = polygon.buffer(0)
        if not fixed.is_empty:
            return fixed
        return unary_union([polygon])

    def _find_base64_image(self, value: Any) -> str | None:
        """dict/list를 재귀적으로 훑어 이미지 base64 후보를 찾는다."""
        if isinstance(value, dict):
            for key in ("base64", "image_base64", "data", "href"):
                candidate = value.get(key)
                if isinstance(candidate, str) and self._looks_like_image_data(candidate):
                    return candidate
            for child in value.values():
                candidate = self._find_base64_image(child)
                if candidate:
                    return candidate
        elif isinstance(value, list):
            for child in value:
                candidate = self._find_base64_image(child)
                if candidate:
                    return candidate
        elif isinstance(value, str) and self._looks_like_image_data(value):
            return value
        return None

    def _looks_like_image_data(self, text: str) -> bool:
        stripped = text.strip()
        if stripped.lower().startswith("data:image/"):
            return True
        return len(stripped) > 100 and all(ch.isalnum() or ch in "+/=\n\r" for ch in stripped[:200])

    def _odd_kernel_size(self, size: int) -> int:
        size = max(1, int(size))
        return size if size % 2 == 1 else size + 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect collision areas in a base64 floorplan JSON.")
    parser.add_argument("json_path", help="Input JSON path containing a base64 image.")
    parser.add_argument(
        "-o",
        "--overlay-output",
        default="collision_overlay.png",
        help="Output image path for the red collision overlay.",
    )
    args = parser.parse_args()

    detector = FloorplanCollisionDetector()
    collisions = detector.analyze_json_file(args.json_path, args.overlay_output)
    print(json.dumps(collisions, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
