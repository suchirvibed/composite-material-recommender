"""
Tests for the mold selector, cure planner, cost estimator and validation set.

Run:  py -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ahp  # noqa: E402
import cost_estimator as ce  # noqa: E402
import cure_planner as cp  # noqa: E402
import mold_selector as ms  # noqa: E402
import validation_cases as vc  # noqa: E402


def material(material_id):
    return next(m for m in ms.load_tool_materials() if m.material_id == material_id)


class TestToolDatabase(unittest.TestCase):
    def test_every_row_has_core_data_and_sources(self):
        for m in ms.load_tool_materials():
            self.assertGreater(m.cte_ppm, 0, m.material_id)
            self.assertIsNotNone(m.density, m.material_id)
            self.assertTrue(m.sources.strip(), m.material_id)

    def test_invar_cte_curve_interpolates(self):
        invar = material("INVAR36")
        self.assertAlmostEqual(invar.cte_at(93), 1.30)
        self.assertAlmostEqual(invar.cte_at(149), 2.11)
        self.assertTrue(2.11 < invar.cte_at(180) < 4.18)


class TestPhysics(unittest.TestCase):
    """Matrix Engine Report worked check: 2 m tool, ΔT 155 °C, α_part 2."""

    def setUp(self):
        self.part = ms.PartDefinition(length_m=2.0, width_m=1.0, cure_temp_C=180, ambient_C=25)

    def test_cte_mismatch_matches_report(self):
        self.assertAlmostEqual(ms.cte_mismatch_mm(material("STEEL_MILD"), self.part), 3.1, places=2)
        # Report uses α = 23 → 6.5 mm; the datasheet's 23.6 gives 6.70 mm.
        self.assertAlmostEqual(ms.cte_mismatch_mm(material("AL6061"), self.part), 6.70, places=2)
        self.assertLess(ms.cte_mismatch_mm(material("INVAR36"), self.part), 0.3)

    def test_thermal_lag_and_mass(self):
        calc = ms.calculate(material("INVAR36"), self.part)
        h = ms.heat_transfer_coefficient(self.part.cure_pressure_bar)
        expected_tau_min = 8055 * 515 * 0.012 / h / 60
        self.assertAlmostEqual(calc.tau_min, expected_tau_min, places=6)
        self.assertAlmostEqual(calc.mass_kg, 8055 * 2.0 * 0.012, places=6)

    def test_htc_interpolates_measured_points(self):
        self.assertEqual(ms.heat_transfer_coefficient(3), 99.0)
        self.assertEqual(ms.heat_transfer_coefficient(7), 138.0)
        self.assertEqual(ms.heat_transfer_coefficient(10), 138.0)     # clamped

    def test_missing_cp_gives_no_lag(self):
        self.assertIsNone(ms.calculate(material("CFRP_BMI"), self.part).lag_C)

    def test_corner_spring_in(self):
        p = ms.PartDefinition(length_m=0.1, width_m=0.05, geometry="angled",
                              corner_angle_deg=90, layup="QI")
        self.assertAlmostEqual(ms.corner_spring_in(p)["spring_in_deg"], 1.28)
        p.corner_angle_deg, p.layup = 45, "UD"
        self.assertAlmostEqual(ms.corner_spring_in(p)["spring_in_deg"], 0.45)


class TestFeasibilityAndScoring(unittest.TestCase):
    def test_low_temperature_board_rejected_with_reason(self):
        gate = ms.feasibility(material("BOARD_EPOXY_130"),
                              ms.PartDefinition(length_m=1, width_m=1, cure_temp_C=180))
        self.assertFalse(gate.passed)
        self.assertIn("Service temperature", gate.rejections[0])

    def test_cycle_life_gate(self):
        gate = ms.feasibility(material("CFRP_BMI"),
                              ms.PartDefinition(length_m=1, width_m=1, cycles_required=5000))
        self.assertFalse(gate.passed)

    def test_autoclave_envelope_rejects_everything(self):
        result = ms.select(ms.PartDefinition(length_m=5, width_m=1, autoclave_length_m=3))
        self.assertTrue(result.part_rejections)
        self.assertEqual(result.ranking, [])

    def test_profiles_are_consistent(self):
        for profile in ms.PROFILE_JUDGMENTS:
            weights, cr = ms.profile_weights(profile)
            self.assertLess(cr, ahp.CR_THRESHOLD, profile)
            self.assertAlmostEqual(sum(weights.values()), 1.0)

    def test_missing_data_is_not_rewarded(self):
        result = ms.select(ms.PartDefinition(length_m=1, width_m=1, cure_temp_C=180,
                                             cure_pressure_bar=2, cycles_required=6))
        graphite = next(r for r in result.ranking if r.calc.material.material_id == "GRAPHITE_ATJ")
        self.assertTrue(graphite.imputed)
        for c in graphite.imputed:
            self.assertEqual(graphite.normalized[c], 0.0)
        self.assertNotEqual(result.ranking[0].calc.material.material_id, "GRAPHITE_ATJ")

    def test_scores_bounded_and_sorted(self):
        result = ms.select(ms.PartDefinition(length_m=1, width_m=1))
        scores = [r.score for r in result.ranking]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(0.0 <= s <= 1.0 for s in scores))

    def test_report_card_renders(self):
        text = ms.report_card(ms.select(ms.PartDefinition(length_m=1, width_m=1)))
        for section in ("FEASIBILITY GATE", "RANKING", "SENSITIVITY", "RISK FLAGS"):
            self.assertIn(section, text)


class TestValidationSet(unittest.TestCase):
    def test_all_documented_cases_reproduced(self):
        for case, result, ok in vc.run_cases():
            self.assertTrue(ok, f"{case.case_id}: {case.title}")


class TestCurePlanner(unittest.TestCase):
    def test_reproduces_ansys_parameter_calculation(self):
        pts = cp.schedule(cp.get_cycle("ANSYS_AL_DEMO"))
        self.assertEqual([round(p["t_s"], 2) for p in pts], [0.0, 3321.43, 14121.43, 17442.86])

    def test_m18_monolithic_timing(self):
        pts = cp.schedule(cp.get_cycle("M18-1_MONO"))
        # 27.5 min ramp + 60 hold + 50 ramp + 120 hold + 77.5 cool = 335 min
        self.assertAlmostEqual(cp.total_minutes(pts), 335.0)

    def test_hold_extension_for_lagging_tool(self):
        self.assertEqual(cp.hold_extension_for_lag(1.0, 2.0), 0.0)     # 2 °C lag < 5 °C tolerance
        self.assertGreater(cp.hold_extension_for_lag(12.0, 2.0), 0)

    def test_sandwich_pressure_warning(self):
        plan = cp.plan(cp.get_cycle("M18-1_SAND"), pressure_bar=6, sandwich=True)
        self.assertTrue(any("outside the documented" in w for w in plan.warnings))
        plan = cp.plan(cp.get_cycle("M18-1_MONO"), pressure_bar=6, sandwich=True)
        self.assertTrue(any("core crush" in w for w in plan.warnings))


class TestCostEstimator(unittest.TestCase):
    def test_per_m2_totals_from_document_rows(self):
        low, high = ce.total(ce.panel_bom())
        self.assertEqual(low, 20250)          # matches the document's stated low total
        self.assertEqual(high, 42850)         # sum of the document's rows (it states 38,850)

    def test_monolithic_drops_core_and_adhesive(self):
        items = {l.item for l in ce.panel_bom(sandwich=False)}
        self.assertNotIn("Nomex/aramid honeycomb core", items)

    def test_aerospace_scenario_matches_table_6(self):
        s = ce.study_cost(ce.MASTER_SCENARIOS["Aerospace-grade"])
        self.assertEqual(s.mould_cost, (303000, 813000))
        self.assertEqual(s.panels, 6)

    def test_indian_number_format(self):
        self.assertEqual(ce.inr(121500), "1,21,500")
        self.assertEqual(ce.inr(813000), "8,13,000")
        self.assertEqual(ce.inr(950), "950")


if __name__ == "__main__":
    unittest.main()
