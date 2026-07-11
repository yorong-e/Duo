import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from build_editable_floorplan import (
    build_labeled_non_residential_mask,
    build_labeled_residential_mask,
    build_editable_payload,
    build_topology_wall_mask,
    remove_fine_wall_strokes,
    regularize_wall_mask,
    extract_non_residential_gray_mask,
    room_type_from_text,
    split_floor_into_room_masks,
)


class RoomTextOverlayTest(unittest.TestCase):
    def test_only_known_room_names_are_accepted(self):
        self.assertEqual("kitchen", room_type_from_text("주방/식당"))
        self.assertEqual("bathroom", room_type_from_text("욕실1"))
        self.assertEqual("bedroom", room_type_from_text("침실 2"))
        self.assertEqual("non_residential", room_type_from_text("공용복도"))
        self.assertEqual("non_residential", room_type_from_text("엘리베이터"))
        self.assertIsNone(room_type_from_text("3,600"))
        self.assertIsNone(room_type_from_text("A.C"))

    def test_large_gray_fill_is_kept_but_small_gray_marks_are_removed(self):
        image = np.full((180, 280, 3), 250, np.uint8)
        image[30:145, 35:160] = (175, 175, 175)
        cv2.line(image, (190, 40), (250, 40), (160, 160, 160), 2)
        mask, metadata = extract_non_residential_gray_mask(
            image,
            np.zeros(image.shape[:2], np.uint8),
        )
        self.assertGreater(int(np.count_nonzero(mask[40:135, 45:150])), 8000)
        self.assertEqual(0, int(np.count_nonzero(mask[35:46, 185:255])))
        self.assertEqual(1, metadata["region_count"])

    def test_rgb_159_to_164_overlay_requires_800_connected_pixels(self):
        image = np.full((100, 160, 3), (75, 80, 90), np.uint8)
        image[5:35, 5:35] = (161, 160, 162)       # 900px: 포함
        image[60:80, 80:110] = (159, 164, 161)    # 600px: 제외
        mask, metadata = extract_non_residential_gray_mask(
            image,
            np.zeros(image.shape[:2], np.uint8),
        )
        self.assertEqual(900, int(np.count_nonzero(mask[5:35, 5:35])))
        self.assertEqual(0, int(np.count_nonzero(mask[60:80, 80:110])))
        self.assertEqual(1, metadata["rgb_159_164_region_count"])
        self.assertEqual(800, metadata["rgb_159_164_min_area_px"])

    def test_rgb_range_seed_expands_to_connected_gray_surface(self):
        image = np.full((120, 220, 3), 250, np.uint8)
        image[10:80, 5:185] = (178, 176, 175)
        image[25:65, 20:60] = (161, 160, 162)
        image[25:65, 60:170] = (178, 176, 175)
        room_mask = np.zeros(image.shape[:2], np.uint8)
        room_mask[15:90, 10:190] = 255
        mask, metadata = extract_non_residential_gray_mask(
            image,
            np.zeros(image.shape[:2], np.uint8),
            room_masks=[room_mask],
        )
        self.assertGreater(int(np.count_nonzero(mask[25:65, 70:160])), 3400)
        self.assertGreater(metadata["rgb_159_164_expanded_area_px"], 3000)

    def test_rgb_gray_component_near_floor_color_is_skipped(self):
        image = np.full((120, 180, 3), (185, 208, 226), np.uint8)
        image[35:65, 65:95] = (161, 161, 161)
        mask, metadata = extract_non_residential_gray_mask(
            image,
            np.zeros(image.shape[:2], np.uint8),
        )
        self.assertEqual(0, int(np.count_nonzero(mask[35:65, 65:95])))
        self.assertEqual(1, metadata["rgb_159_164_rejected_neighbor_count"])
        self.assertEqual(12, metadata["rgb_159_164_veto_radius_px"])

    def test_rgb_gray_surface_with_small_white_noise_is_kept(self):
        image = np.full((120, 180, 3), (176, 176, 176), np.uint8)
        image[35:65, 65:95] = (161, 161, 161)
        image[30:34, 60:100] = (250, 250, 250)
        mask, metadata = extract_non_residential_gray_mask(
            image,
            np.zeros(image.shape[:2], np.uint8),
        )
        self.assertEqual(900, int(np.count_nonzero(mask[35:65, 65:95])))
        self.assertEqual(0, metadata["rgb_159_164_rejected_neighbor_count"])
        self.assertEqual(0.55, metadata["rgb_159_164_veto_min_ratio"])

    def test_rgb_sink_shading_inside_kitchen_protection_is_skipped(self):
        image = np.full((140, 220, 3), (75, 80, 90), np.uint8)
        image[45:75, 80:110] = (161, 161, 161)
        protected = np.zeros(image.shape[:2], np.uint8)
        protected[30:95, 55:140] = 255
        mask, metadata = extract_non_residential_gray_mask(
            image,
            np.zeros(image.shape[:2], np.uint8),
            protected_mask=protected,
        )
        self.assertEqual(0, int(np.count_nonzero(mask[45:75, 80:110])))
        self.assertEqual(1, metadata["rgb_159_164_rejected_protected_count"])

    def test_sparse_rgb_grid_on_wood_floor_is_not_overlayed(self):
        image = np.full((140, 220, 3), (185, 208, 226), np.uint8)
        for x in range(20, 201, 12):
            cv2.line(image, (x, 20), (x, 120), (161, 161, 161), 1)
        for y in range(20, 121, 12):
            cv2.line(image, (20, y), (200, y), (161, 161, 161), 1)
        mask, metadata = extract_non_residential_gray_mask(
            image,
            np.zeros(image.shape[:2], np.uint8),
        )
        self.assertEqual(0, int(np.count_nonzero(mask)))
        self.assertEqual("seeded_neutral_surface_v2", metadata["algorithm"])

    def test_lighter_gray_patches_connected_to_common_area_are_absorbed(self):
        image = np.full((220, 320, 3), 250, np.uint8)
        room_mask = np.zeros(image.shape[:2], np.uint8)
        room_mask[20:200, 20:300] = 255
        image[35:185, 35:170] = (175, 175, 175)
        image[35:185, 170:285] = (210, 208, 206)
        mask, metadata = extract_non_residential_gray_mask(
            image,
            np.zeros(image.shape[:2], np.uint8),
            room_masks=[room_mask],
        )
        self.assertGreater(int(np.count_nonzero(mask[50:170, 190:270])), 8000)
        self.assertGreater(metadata["relaxed_connected_growth_px"], 0)

    def test_ocr_labeled_room_is_not_marked_non_residential(self):
        image = np.full((300, 400, 3), 250, np.uint8)
        image[30:100, 30:130] = (175, 175, 175)
        room_mask = np.zeros(image.shape[:2], np.uint8)
        room_mask[30:100, 30:130] = 255
        labels = [{
            "text": "욕실1",
            "room_type": "bathroom",
            "bbox": {"x": 55, "y": 50, "width": 45, "height": 20},
        }]
        protected = build_labeled_residential_mask(labels, [room_mask], image.shape)
        mask, metadata = extract_non_residential_gray_mask(
            image,
            np.zeros(image.shape[:2], np.uint8),
            protected_mask=protected,
        )
        self.assertEqual(0, int(np.count_nonzero(mask)))
        self.assertEqual(0, metadata["region_count"])

    def test_entrance_label_does_not_protect_adjacent_common_area(self):
        image = np.full((180, 280, 3), 250, np.uint8)
        image[25:155, 30:250] = (202, 200, 198)
        room_mask = np.zeros(image.shape[:2], np.uint8)
        room_mask[25:155, 30:250] = 255
        labels = [{
            "text": "현관",
            "room_type": "entrance",
            "bbox": {"x": 45, "y": 80, "width": 35, "height": 20},
        }]
        protected = build_labeled_residential_mask(labels, [room_mask], image.shape)
        mask, _metadata = extract_non_residential_gray_mask(
            image,
            np.zeros(image.shape[:2], np.uint8),
            protected_mask=protected,
            room_masks=[room_mask],
        )
        self.assertLess(int(np.count_nonzero(protected)), 5000)
        self.assertGreater(int(np.count_nonzero(mask)), 15000)

    def test_explicit_common_area_label_marks_closed_room_gray(self):
        image = np.full((180, 280, 3), 245, np.uint8)
        room_mask = np.zeros(image.shape[:2], np.uint8)
        room_mask[30:150, 70:190] = 255
        labels = [{
            "text": "공용복도",
            "room_type": "non_residential",
            "bbox": {"x": 100, "y": 75, "width": 60, "height": 25},
        }]
        protected = build_labeled_residential_mask(labels, [room_mask], image.shape)
        explicit = build_labeled_non_residential_mask(labels, [room_mask], image.shape)
        mask, metadata = extract_non_residential_gray_mask(
            image,
            np.zeros(image.shape[:2], np.uint8),
            protected_mask=protected,
            room_masks=[room_mask],
            explicit_mask=explicit,
        )
        self.assertEqual(0, int(np.count_nonzero(protected)))
        self.assertGreater(int(np.count_nonzero(mask)), 14000)
        self.assertGreater(metadata["explicit_non_residential_area_px"], 14000)

    def test_room_split_ignores_dark_furniture_lines(self):
        image = np.full((240, 320, 3), 245, np.uint8)
        cv2.line(image, (80, 60), (80, 180), (20, 20, 20), 5)
        floor_mask = np.zeros(image.shape[:2], np.uint8)
        floor_mask[20:220, 20:300] = 255
        wall_mask = np.zeros_like(floor_mask)
        rooms = split_floor_into_room_masks(image, floor_mask, wall_mask, 5)
        self.assertEqual(1, len(rooms))

    def test_small_room_closed_by_real_walls_is_not_split(self):
        image = np.full((240, 320, 3), 245, np.uint8)
        floor_mask = np.zeros(image.shape[:2], np.uint8)
        floor_mask[20:220, 20:300] = 255
        wall_mask = np.zeros_like(floor_mask)
        cv2.line(wall_mask, (75, 20), (75, 95), 255, 7)
        cv2.line(wall_mask, (20, 95), (75, 95), 255, 7)
        rooms = split_floor_into_room_masks(image, floor_mask, wall_mask, 7)
        self.assertEqual(1, len(rooms))

    def test_physical_wall_with_door_gap_does_not_split_floor(self):
        image = np.full((240, 320, 3), 245, np.uint8)
        floor_mask = np.zeros(image.shape[:2], np.uint8)
        floor_mask[20:220, 20:300] = 255
        wall_mask = np.zeros_like(floor_mask)
        cv2.line(wall_mask, (160, 20), (160, 102), 255, 5)
        cv2.line(wall_mask, (160, 126), (160, 220), 255, 5)
        rooms = split_floor_into_room_masks(image, floor_mask, wall_mask, 5)
        self.assertEqual(1, len(rooms))

    def test_disconnected_floorplans_remain_separate_components(self):
        image = np.full((240, 420, 3), 245, np.uint8)
        floor_mask = np.zeros(image.shape[:2], np.uint8)
        floor_mask[20:220, 20:180] = 255
        floor_mask[20:220, 240:400] = 255
        rooms = split_floor_into_room_masks(
            image,
            floor_mask,
            np.zeros_like(floor_mask),
            7,
        )
        self.assertEqual(2, len(rooms))

    def test_interrupted_wall_extends_straight_until_it_meets_wall(self):
        wall_mask = np.zeros((240, 320), np.uint8)
        cv2.line(wall_mask, (160, 20), (160, 85), 255, 5)
        cv2.line(wall_mask, (160, 140), (160, 220), 255, 5)
        topology, metadata = build_topology_wall_mask(wall_mask, 5)
        self.assertGreater(int(np.count_nonzero(topology[88:138, 157:164])), 250)
        self.assertGreater(metadata["straight_wall_connection_count"], 0)

    def test_wall_regularization_fills_noise_gap_but_keeps_door_gap(self):
        mask = np.zeros((130, 220), np.uint8)
        cv2.line(mask, (20, 40), (90, 40), 255, 5)
        cv2.line(mask, (95, 40), (190, 40), 255, 5)
        cv2.line(mask, (20, 90), (85, 90), 255, 5)
        cv2.line(mask, (110, 90), (190, 90), 255, 5)
        regularized, _metadata = regularize_wall_mask(mask, 5)
        self.assertGreater(int(regularized[40, 92]), 0)
        self.assertEqual(0, int(regularized[90, 98]))

    def test_fine_furniture_marks_are_removed_from_wall_mask(self):
        mask = np.zeros((140, 220), np.uint8)
        cv2.line(mask, (20, 35), (200, 35), 255, 9)
        cv2.line(mask, (65, 75), (145, 125), 255, 1)
        cv2.line(mask, (145, 75), (65, 125), 255, 1)
        cleaned, metadata = remove_fine_wall_strokes(mask, 9)
        self.assertGreater(int(np.count_nonzero(cleaned[30:41, 20:201])), 1200)
        self.assertEqual(0, int(np.count_nonzero(cleaned[70:130, 55:155])))
        self.assertGreater(metadata["removed_fine_stroke_px"], 0)

    def test_vectorization_payload_is_created_with_legacy_detector_arguments_removed(self):
        image = np.full((220, 320, 3), 245, np.uint8)
        cv2.rectangle(image, (35, 30), (285, 190), (20, 20, 20), 18)
        cv2.putText(
            image,
            "KITCHEN",
            (95, 115),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (25, 25, 25),
            2,
            cv2.LINE_AA,
        )
        encoded_ok, encoded = cv2.imencode(".png", image)
        self.assertTrue(encoded_ok)
        data_uri = "data:image/png;base64," + base64.b64encode(encoded).decode("ascii")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = root / "plan.json"
            output_path = root / "editable.json"
            input_path.write_text(
                json.dumps({"image": {"href": data_uri}}),
                encoding="utf-8",
            )
            recognized = [{
                "id": "room_label_000",
                "text": "KITCHEN",
                "room_type": "kitchen",
                "confidence": 0.99,
                "bbox": {"x": 95, "y": 92, "width": 110, "height": 26},
                "source": "test_ocr",
            }]
            with patch(
                    "build_editable_floorplan.recognize_room_labels",
                    return_value=(recognized, {"status": "ok", "label_count": 1})):
                payload = build_editable_payload(input_path, output_path)

            self.assertTrue(output_path.is_file())
            self.assertEqual([], payload["detections"])
            self.assertEqual("KITCHEN", payload["room_labels"][0]["text"])
            self.assertTrue(payload["layers"]["non_residential_mask"].startswith("data:image/png;base64,"))


if __name__ == "__main__":
    unittest.main()
