"""
Unit tests for the v4 engine, AHP, lamina estimator and evaluator.

Run:  py -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import evaluate_weights as ev  # noqa: E402
import lamina_estimator as le  # noqa: E402
import updated_database_recommender_v4 as v4  # noqa: E402


def aerospace_app() -> dict:
    app = dict(v4.APPLICATIONS["1"])
    app["importance"] = v4.ahp_weights(app["ahp_judgments"]).weights
    return app


def soft_requirements(**overrides) -> v4.Requirements:
    base = dict(strength_mpa=4000, modulus_gpa=230, max_density_g_cm3=1.85,
                elongation_percent=1.5, hard_strength=False, hard_modulus=False,
                hard_density=False, hard_elongation=False, process=None,
                matrix=None, require_certification=False)
    base.update(overrides)
    return v4.Requirements(**base)


class TestAhp(unittest.TestCase):
    def test_all_presets_consistent_and_normalized(self):
        for key, app in v4.APPLICATIONS.items():
            if not app["ahp_judgments"]:
                continue
            result = v4.ahp_weights(app["ahp_judgments"])
            self.assertTrue(result.consistent, app["name"])
            self.assertAlmostEqual(sum(result.weights.values()), 1.0, places=9)
            self.assertTrue(all(w > 0 for w in result.weights.values()))

    def test_equal_judgments_give_equal_weights(self):
        result = v4.ahp_weights(v4.judgments([1] * 6))
        for w in result.weights.values():
            self.assertAlmostEqual(w, 0.25, places=9)
        self.assertAlmostEqual(result.consistency_ratio, 0.0, places=9)

    def test_matrix_is_reciprocal(self):
        m = v4.build_pairwise_matrix(v4.APPLICATIONS["1"]["ahp_judgments"])
        np.testing.assert_allclose(m * m.T, np.ones_like(m))

    def test_contradictory_judgments_flagged(self):
        # strength >> modulus, modulus >> density, but density >> strength
        bad = v4.judgments([9, 1 / 9, 1, 9, 1, 1])
        self.assertFalse(v4.ahp_weights(bad).consistent)

    def test_aerospace_matches_hand_calculation(self):
        w = v4.ahp_weights(v4.APPLICATIONS["1"]["ahp_judgments"]).weights
        self.assertAlmostEqual(w["modulus"], 0.368, places=3)
        self.assertAlmostEqual(w["elongation"], 0.070, places=3)

    def test_non_positive_judgment_rejected(self):
        with self.assertRaises(ValueError):
            v4.build_pairwise_matrix({("strength", "modulus"): 0})


class TestScoring(unittest.TestCase):
    def test_ratio_score_bounds(self):
        self.assertEqual(v4.ratio_score(150, 100, True), 100.0)    # capped at 1.5x
        self.assertEqual(v4.ratio_score(300, 100, True), 100.0)
        self.assertAlmostEqual(v4.ratio_score(75, 100, True), 50.0)
        self.assertEqual(v4.ratio_score(1.7, 1.8, False), 100.0)   # under density limit
        self.assertAlmostEqual(v4.ratio_score(2.0, 1.8, False), 90.0)

    def test_zero_target_means_no_requirement(self):
        self.assertEqual(v4.ratio_score(2.0, 0.0, True), 100.0)
        self.assertTrue(np.isnan(v4.ratio_score(np.nan, 0.0, True)))

    def test_missing_data_scores_zero_not_skipped(self):
        weights = {"a": 0.5, "b": 0.5}
        self.assertEqual(v4.weighted_mean({"a": 100.0, "b": np.nan}, weights), 50.0)
        self.assertEqual(v4.data_completeness({"a": 1.0, "b": np.nan}), 50.0)

    def test_fiber_missing_most_data_cannot_top_ranking(self):
        fibers = v4.load_fiber_database()
        result = v4.build_ranked_results(fibers, soft_requirements(), aerospace_app())
        sparse = result[result["Data_Completeness_percent"] < 50]
        self.assertFalse(sparse.empty)
        self.assertTrue((sparse["Rank"] > 20).all(), sparse[["Product", "Rank"]])

    def test_hard_filter_removes_failing_fibers(self):
        fibers = v4.load_fiber_database()
        result = v4.build_ranked_results(
            fibers, soft_requirements(strength_mpa=6000, hard_strength=True), aerospace_app())
        self.assertTrue((result["Strength_MPa"] >= 6000).all())

    def test_impossible_hard_limit_returns_empty(self):
        fibers = v4.load_fiber_database()
        result = v4.build_ranked_results(
            fibers, soft_requirements(max_density_g_cm3=1.0, hard_density=True), aerospace_app())
        self.assertTrue(result.empty)

    def test_ranking_sorted_and_relative_score(self):
        fibers = v4.load_fiber_database()
        result = v4.build_ranked_results(fibers, soft_requirements(), aerospace_app())
        self.assertTrue(result["Final_Score"].is_monotonic_decreasing)
        self.assertEqual(result["Relative_Score_percent"].iloc[0], 100.0)
        self.assertEqual(list(result["Rank"]), list(range(1, len(result) + 1)))


class TestDiagnosticsAndTies(unittest.TestCase):
    def test_combined_limits_are_identified(self):
        fibers = v4.load_fiber_database()
        req = soft_requirements(modulus_gpa=459, max_density_g_cm3=1.84,
                                hard_modulus=True, hard_density=True)
        self.assertTrue(v4.build_ranked_results(fibers, req, aerospace_app()).empty)
        self.assertEqual(v4.smallest_conflict(fibers, req), ["Modulus", "Density"])
        closest = v4.closest_candidate(fibers, req)
        self.assertIn("M55J", closest["name"])
        self.assertTrue(any("Density" in m for m in closest["misses"]))

    def test_no_conflict_when_results_exist(self):
        fibers = v4.load_fiber_database()
        req = soft_requirements(strength_mpa=4000, hard_strength=True)
        self.assertEqual(v4.smallest_conflict(fibers, req), [])

    def test_identical_fibers_marked_tied_and_ordered(self):
        fibers = v4.load_fiber_database()
        result = v4.build_ranked_results(fibers, soft_requirements(), aerospace_app())
        top = result.head(2)
        self.assertEqual(list(top["Product"]), ["T1100G", "T1100S"])   # name tie-break
        self.assertEqual(top.iloc[0]["Tied_With"], "#2")
        self.assertEqual(top.iloc[1]["Tied_With"], "#1")
        again = v4.build_ranked_results(fibers, soft_requirements(), aerospace_app())
        self.assertEqual(list(result["Product"]), list(again["Product"]))

    def test_coverage_and_empty_reasons(self):
        prepregs, resins = v4.load_prepreg_database(), v4.load_resin_database()
        self.assertEqual(v4.system_coverage(prepregs, resins, matrix="thermoplastic"), (0, 0))
        self.assertEqual(v4.system_coverage(prepregs, resins, process="RTM")[0], 0)
        self.assertIn("liquid resin", v4.empty_reason("prepreg", soft_requirements(process="RTM")))
        self.assertIn("data gap", v4.empty_reason("resin", soft_requirements(matrix="phenolic")))

    def test_extrapolated_lamina_shows_no_number(self):
        fibers = v4.load_fiber_database()
        m60j = fibers[fibers["product"] == "M60J"].iloc[0]          # 588 GPa: outside calibration
        cols = v4.lamina_columns(m60j)
        self.assertTrue(np.isnan(cols["Lamina_Xt_MPa"]))
        self.assertIn("no reliable estimate", cols["Lamina_Basis"])


class TestTextMatching(unittest.TestCase):
    def test_epoxy_sizing_needs_real_code(self):
        row = pd.Series({"sizing_compatibility": "", "sizing_options": "sizing types 4, 5"})
        self.assertEqual(v4.fiber_matrix_fit(row, "epoxy"), 60.0)
        row = pd.Series({"sizing_compatibility": "", "sizing_options": "GP, GS"})
        self.assertEqual(v4.fiber_matrix_fit(row, "epoxy"), 95.0)

    def test_whole_word_matching(self):
        self.assertTrue(v4.has_term("epoxy; pa6 or pa", "pa"))
        self.assertFalse(v4.has_term("capable of high temperatures", "pa"))
        self.assertTrue(v4.has_term("out-of-autoclave", "autoclave"))

    def test_prepreg_grade_requires_exact_token(self):
        prepregs = pd.DataFrame([{
            "prepreg_id": "P1", "fiber_grade": "AS4", "process_suitability": "",
            "matrix_family": "", "qualification_certification": "",
        }])
        req = soft_requirements()
        as4c = pd.DataFrame({"Product": ["HexTow AS4C (Aerospace)"]})
        as4 = pd.DataFrame({"Product": ["HexTow AS4"]})
        self.assertEqual(v4.build_prepreg_results(prepregs, req, as4c)["Fiber_Match"][0], "NOT ESTABLISHED")
        self.assertEqual(v4.build_prepreg_results(prepregs, req, as4)["Fiber_Match"][0], "EXPLICIT")

    def test_process_fit_neutral_for_resin_driven_processes(self):
        row = pd.Series({"sizing_options": "3K", "recommended_uses": "", "sizing_compatibility": ""})
        for process in ["RTM", "VARTM / infusion", "autoclave"]:
            self.assertEqual(v4.process_fit(row, process), 100.0)
        self.assertEqual(v4.process_fit(row, "filament winding"), 65.0)


class TestLaminaEstimator(unittest.TestCase):
    def test_calibration_data_loads_and_fits(self):
        data = le.load_calibration_data()
        self.assertGreaterEqual(len(data), 10)
        model = le.fit(data)
        self.assertTrue(0.4 < model.strength_efficiency < 0.6)
        self.assertTrue(0.5 < model.modulus_slope < 0.8)

    def test_estimate_close_to_published(self):
        model = le.calibrated_model()
        est = model.estimate(5670, 276)      # HexTow IM7; datasheet lamina 2723 MPa / 164 GPa
        self.assertLess(abs(est["Xt_MPa"] - 2723) / 2723, 0.10)
        self.assertLess(abs(est["E1_GPa"] - 164) / 164, 0.05)
        self.assertFalse(est["extrapolated"])

    def test_extrapolation_flagged(self):
        self.assertTrue(le.calibrated_model().estimate(9000, 600)["extrapolated"])

    def test_published_prefers_ncamp(self):
        rec = le.published_lamina("HEX-015")
        self.assertEqual(rec["source_type"], "NCAMP_measured")


class TestEvaluator(unittest.TestCase):
    def test_metrics_perfect_prediction(self):
        y = np.array([0, 1, 1, 0])
        m = ev.metrics(y, y.astype(float))
        self.assertEqual(m["MSE"], 0.0)
        self.assertEqual(m["AUC"], 1.0)

    def test_calibration_recovers_signal(self):
        rng = np.random.default_rng(0)
        s = rng.normal(size=400)
        y = (rng.random(400) < ev.sigmoid(2 * s)).astype(float)
        p = ev.fit_calibration(s, y)(s)
        self.assertGreater(ev.auc(y, p), 0.75)

    def test_learning_moves_toward_true_weights(self):
        rng = np.random.default_rng(1)
        X = rng.random((300, 4))
        true_w = np.array([0.7, 0.1, 0.1, 0.1])
        y = (rng.random(300) < ev.sigmoid(12 * (X @ true_w - 0.5))).astype(float)
        prior = np.full(4, 0.25)
        learned = ev.learn_weights(X, y, prior, l2=0.0)
        self.assertGreater(learned[0], 0.5)
        self.assertAlmostEqual(learned.sum(), 1.0, places=9)


if __name__ == "__main__":
    unittest.main()
