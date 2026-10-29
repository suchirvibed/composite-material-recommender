"""Tests for prepreg_selector.py: requirements in, prepreg and datasheet cure cycle out."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cure_planner as cp  # noqa: E402
import prepreg_selector as ps  # noqa: E402


class TestSelection(unittest.TestCase):
    def test_every_candidate_meets_every_requirement(self):
        req = ps.LaminateRequirements(2500, min_modulus_gpa=150, max_density_g_cm3=1.56)
        res = ps.select(req)
        self.assertTrue(res.ranked)
        for c in res.ranked:
            self.assertGreaterEqual(c.strength, 2500)
            self.assertGreaterEqual(c.modulus, 150)
            self.assertLessEqual(c.density, 1.56)
        self.assertEqual(res.best.variant["variant_id"], "M56_IM7_UD")

    def test_rejections_give_reasons(self):
        res = ps.select(ps.LaminateRequirements(2500))
        weak = [r for r in res.rejected if "AS4" in r.name]
        self.assertTrue(weak and "strength" in weak[0].reasons[0])

    def test_impossible_requirement_selects_nothing(self):
        res = ps.select(ps.LaminateRequirements(4000))
        self.assertIsNone(res.best)
        self.assertIn("No prepreg", ps.selection_text(res))

    def test_cycle_comes_from_the_prepregs_datasheet(self):
        res = ps.select(ps.LaminateRequirements(1500))
        cmap = ps.cure_map()
        for c in res.ranked:
            self.assertIn(c.cycle_id, cmap[c.master["product_system"]].values())
            self.assertIsNotNone(cp.get_cycle(c.cycle_id))

    def test_part_type_and_equipment_choose_the_cycle(self):
        sand = ps.select(ps.LaminateRequirements(2000, part_type="sandwich"))
        self.assertTrue(all(cp.get_cycle(c.cycle_id).part_type == "sandwich" for c in sand.ranked))
        self.assertFalse(any("3900" in c.name for c in sand.ranked))   # no sandwich cycle in datasheet
        oven = ps.select(ps.LaminateRequirements(1500, equipment="oven"))
        self.assertTrue(oven.ranked)
        self.assertTrue(all(c.master["product_system"] in ("M56", "M18/1") for c in oven.ranked))
        thick = ps.select(ps.LaminateRequirements(2800, laminate_mm=20))
        self.assertEqual(thick.best.cycle_id, "HEX_M21_THICK")

    def test_form_filter(self):
        res = ps.select(ps.LaminateRequirements(500, form="fabric"))
        self.assertTrue(res.ranked)
        self.assertTrue(all(c.variant["form"] != "UD" for c in res.ranked))

    def test_systems_without_data_are_listed_not_guessed(self):
        res = ps.select(ps.LaminateRequirements(0))
        evaluated = {c.master["prepreg_id"] for c in res.ranked}
        self.assertFalse(evaluated & {n["prepreg_id"] for n in res.no_data})
        self.assertGreater(len(res.no_data), 0)

    def test_negative_strength_rejected(self):
        with self.assertRaises(ValueError):
            ps.select(ps.LaminateRequirements(-1))


if __name__ == "__main__":
    unittest.main()
