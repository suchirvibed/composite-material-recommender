"""
Tests for the DOE builder and the desktop window (driven without showing it).

Run:  py -m unittest discover -s tests -v
"""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cure_planner as cp  # noqa: E402
import doe  # noqa: E402


def factors(keys):
    return [f for f in doe.default_factors() if f.key in keys]


class TestDesign(unittest.TestCase):
    def test_full_and_half_fraction_sizes(self):
        self.assertEqual(len(doe.design_points(3)), 8)
        self.assertEqual(len(doe.design_points(4, half_fraction=True)), 8)
        for p in doe.design_points(4, half_fraction=True):
            self.assertEqual(np.prod(p), 1)

    def test_matrix_replicates_and_balance(self):
        runs = doe.build_matrix(doe.StudyArticle(), factors(["tool", "ramp", "dwell"]), replicates=3)
        self.assertEqual(len(runs), 24)
        for key in ("tool", "ramp", "dwell"):
            coded = [r.coded[key] for r in runs]
            self.assertEqual(coded.count(1), coded.count(-1))

    def test_predictions_follow_the_physics(self):
        runs = doe.build_matrix(doe.StudyArticle(), factors(["tool"]), replicates=1, randomize=False)
        cfrp, alu = runs[0], runs[1]                 # low = CFRP tooling, high = aluminium
        self.assertLess(cfrp.predictions["pred_cte_mismatch_mm"], alu.predictions["pred_cte_mismatch_mm"])
        fast = doe.build_matrix(doe.StudyArticle(), factors(["ramp"]), replicates=1, randomize=False)
        self.assertGreater(fast[0].predictions["pred_cycle_min"], fast[1].predictions["pred_cycle_min"])

    def test_sandwich_pressure_warning(self):
        runs = doe.build_matrix(doe.StudyArticle(), factors(["pressure"]), replicates=1, randomize=False)
        self.assertTrue(all("sandwich limit" in " ".join(r.warnings) for r in runs))

    def test_corner_runs_get_spring_in(self):
        runs = doe.build_matrix(doe.StudyArticle(), factors(["geometry"]), replicates=1, randomize=False)
        self.assertIsNone(runs[0].predictions["pred_corner_spring_in_deg"])
        self.assertAlmostEqual(runs[1].predictions["pred_corner_spring_in_deg"], 1.28)

    def test_study_cost_counts_each_tool_once(self):
        art = doe.StudyArticle()
        runs = doe.build_matrix(art, factors(["tool", "ramp"]), replicates=3)
        cost = doe.study_cost(art, runs)
        self.assertEqual(cost["panels"], 12)
        self.assertEqual(cost["mould"], (200000.0, 550000.0))   # composite + aluminium mould


class TestAnalysis(unittest.TestCase):
    def test_main_effects_recover_known_effect(self):
        fs = factors(["tool", "ramp", "dwell"])
        runs = doe.build_matrix(doe.StudyArticle(), fs, replicates=3)
        with tempfile.TemporaryDirectory() as tmp:
            path = doe.write_csv(runs, fs, Path(tmp) / "m.csv")
            with open(path, encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            rng = np.random.default_rng(3)
            for r in rows:
                r["measured_deviation_mm"] = 0.3 + 0.5 * (int(r["tool_coded"]) == 1) + rng.normal(0, 0.02)
            with open(path, "w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=rows[0].keys())
                w.writeheader()
                w.writerows(rows)
            res = doe.analyse_main_effects(path)
        self.assertEqual(next(iter(res["effects"])), "tool")
        self.assertAlmostEqual(res["effects"]["tool"]["effect"], 0.5, delta=0.05)

    def test_needs_measured_data(self):
        fs = factors(["tool"])
        with tempfile.TemporaryDirectory() as tmp:
            path = doe.write_csv(doe.build_matrix(doe.StudyArticle(), fs), fs, Path(tmp) / "m.csv")
            with self.assertRaises(ValueError):
                doe.analyse_main_effects(path)


class TestWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import project_gui
            cls.app = project_gui.StudyApp()
            cls.app.withdraw()
        except Exception as exc:          # no display available
            raise unittest.SkipTest(f"Tk not available: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()

    def test_full_workflow_builds_report(self):
        app = self.app
        app._run_material()
        app._run_tooling()
        app._run_cure()
        app._run_doe()
        self.assertTrue(app.m_tree.get_children())
        self.assertTrue(app.t_tree.get_children())
        self.assertEqual(len(app.d_tree.get_children()), 24)
        report = app.report_text()
        for section in ("1 MATERIAL SYSTEM", "2 TOOLING (PS1)", "3 CURE CYCLE (PS2)", "4 DOE MATRIX", "5 COST"):
            self.assertIn(section, report)

    def test_scoping_question_sets_factors(self):
        app = self.app
        app.focus.set("design")
        app._apply_focus()
        on = [k for k, (var, *_r) in app.doe_vars.items() if var.get()]
        self.assertEqual(on, doe.FOCUS_PRESETS["design"])
        app.focus.set("process")
        app._apply_focus()

    def test_requirements_select_prepreg_and_cycle(self):
        app = self.app
        app.r_strength.set("2500")
        app.r_modulus.set("150")
        app.a_part.set("honeycomb sandwich")
        app._select_prepreg()
        self.assertIsNotNone(app.prepreg)
        a = app.article()
        cycle = cp.get_cycle(a.cycle_id)
        self.assertTrue(a.sandwich)
        self.assertEqual(cycle.part_type, "sandwich")
        self.assertEqual(a.cure_temp_C, cycle.peak_C)
        self.assertIn("0 PREPREG SELECTION", app.report_text())
        app.r_strength.set("4000")
        app._select_prepreg()
        self.assertIsNone(app.prepreg)
        app._reset_article()
        self.assertFalse(app.article().sandwich)

    def test_bad_input_is_reported_not_crashing(self):
        app = self.app
        app.a_len.set("abc")
        with self.assertRaises(ValueError):
            app.article()
        app._reset_article()
        self.assertEqual(app.article().length_m, 1.0)


if __name__ == "__main__":
    unittest.main()
