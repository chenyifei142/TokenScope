import unittest

from ui.geometry import (
    WorkArea,
    compact_geometry,
    expanded_geometry,
    expanded_panel_geometry,
    snap_compact,
)


class GeometryTests(unittest.TestCase):
    def test_four_corners_choose_inward_direction(self):
        work = WorkArea(0, 0, 1920, 1080)
        cases = [
            ((8, 8, 72, 72), ("right", "down")),
            ((1840, 8, 72, 72), ("left", "down")),
            ((8, 1000, 72, 72), ("right", "up")),
            ((1840, 1000, 72, 72), ("left", "up")),
        ]
        for compact, expected in cases:
            result = expanded_geometry(compact, (390, 710), work)
            self.assertEqual(result[4:], expected)
            x, y, width, height = result[:4]
            self.assertEqual(width, 390 + 72 + 16)
            self.assertGreaterEqual(x, work.left)
            self.assertGreaterEqual(y, work.top)
            self.assertLessEqual(x + width, work.right)
            self.assertLessEqual(y + height, work.bottom)

    def test_negative_monitor_and_anchor_restore(self):
        work = WorkArea(-1920, 0, 0, 1080)
        expanded = expanded_geometry((-80, 1000, 72, 72), (390, 710), work)
        x, y, width, height, horizontal, vertical = expanded
        compact = compact_geometry((x, y, width, height), 72, horizontal, vertical, work)
        self.assertEqual(horizontal, "left")
        self.assertEqual(vertical, "up")
        self.assertGreaterEqual(compact[0], work.left)
        self.assertLessEqual(compact[0] + 72, work.right)

    def test_compact_snaps_to_nearest_work_area_edge(self):
        work = WorkArea(-1600, 40, 0, 1040)
        self.assertEqual(snap_compact(-1500, 20, 120, work), (-1592, 48))
        self.assertEqual(snap_compact(-100, 1100, 120, work), (-128, 912))

    def test_panel_only_expansion_preserves_ball_anchor(self):
        work = WorkArea(0, 0, 1920, 1080)
        for compact, expected_direction in (
            ((300, 90, 96, 96), ("right", "down")),
            ((1500, 900, 96, 96), ("left", "up")),
        ):
            expanded = expanded_panel_geometry(compact, (820, 650), work)
            self.assertEqual(expanded[2:4], (820, 650))
            self.assertEqual(expanded[4:], expected_direction)
            restored = compact_geometry(expanded[:4], 96, *expanded[4:], work)
            self.assertEqual(restored, (compact[0], compact[1]))

    def test_compact_restore_only_clamps_out_of_bounds_position(self):
        work = WorkArea(0, 0, 1920, 1080)
        self.assertEqual(
            compact_geometry((420, 200, 820, 564), 96, "right", "down", work),
            (420, 200),
        )
        self.assertEqual(
            compact_geometry((-50, 200, 820, 564), 96, "right", "down", work),
            (8, 200),
        )


if __name__ == "__main__":
    unittest.main()
