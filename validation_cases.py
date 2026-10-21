"""
D6 — validation set for the mold selector.

Each case is a worked part definition whose accepted industry choice is
stated in the project documents. The engine must reproduce it (Matrix
Engine Report, actionable A6: "engine reproduces accepted industry choices").

Run:  py validation_cases.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List

import mold_selector as ms


@dataclass
class Case:
    case_id: str
    title: str
    part: ms.PartDefinition
    expectation: str                      # what the documents say
    source: str
    check: Callable[[ms.SelectionResult], bool]


def top(result: ms.SelectionResult) -> str:
    return result.ranking[0].calc.material.material_id if result.ranking else ""


def top_two(result: ms.SelectionResult) -> List[str]:
    return [r.calc.material.material_id for r in result.ranking[:2]]


def rejected(result: ms.SelectionResult, material_id: str) -> bool:
    return any(not g.passed for g in result.gates if g.material.material_id == material_id)


CASES = [
    Case("V1", "Large close-tolerance aerospace skin",
         ms.PartDefinition(length_m=2.0, width_m=1.0, cure_temp_C=180, cure_pressure_bar=7,
                           cycles_required=1000, tolerance_mm=0.5, tolerance_hard=True,
                           profile="aerospace"),
         "Invar for high-volume, close-tolerance aerostructure tooling (thousands of cycles)",
         "Tooling report §3.1, §6; Master Report Table 2",
         lambda r: top(r) == "INVAR36"),
    Case("V2", "Low-rate motorsport part, tight tolerance, cost-driven",
         ms.PartDefinition(length_m=1.5, width_m=0.8, cure_temp_C=180, cure_pressure_bar=6,
                           cycles_required=150, tolerance_mm=1.0, tolerance_hard=True,
                           profile="prototype"),
         "Composite (soft) tooling in motorsport / low-rate production where tool cost and "
         "lead time outweigh maximum cycle life",
         "Tooling report §6; Master Report §4.8",
         lambda r: top(r) == "CFRP_BMI"),
    Case("V3", "Class-A cosmetic / aerodynamic surface",
         ms.PartDefinition(length_m=1.2, width_m=0.8, cure_temp_C=180, cure_pressure_bar=6,
                           cycles_required=300, class_a_surface=True, profile="production"),
         "Electroformed nickel shell (or precision-machined metal) for Class-A surfaces; "
         "composite and board tools excluded",
         "Tooling report §3.4, §6",
         lambda r: top(r) == "NICKEL_EF"
         and all(rejected(r, m) for m in ("CFRP_BMI", "BOARD_EPOXY_HT", "FOAM_EPU_HT"))),
    Case("V4", "Low-temperature board cannot survive a 180 °C cure",
         ms.PartDefinition(length_m=1.0, width_m=1.0, cure_temp_C=180, cure_pressure_bar=2,
                           cycles_required=6, profile="prototype"),
         "130 °C epoxy board rejected for a 180 °C cure (service temperature)",
         "EB700 TDS (max 130 °C); Matrix Engine Report feasibility gate",
         lambda r: rejected(r, "BOARD_EPOXY_130")),
    Case("V5", "Aluminium unsuitable for a large precision tool",
         ms.PartDefinition(length_m=2.0, width_m=1.0, cure_temp_C=180, cure_pressure_bar=7,
                           cycles_required=100, tolerance_mm=1.0, tolerance_hard=True,
                           profile="production"),
         "Aluminium gives millimetres of mismatch on a 2 m tool (≈6.5 mm) — rejected at 1 mm",
         "Matrix Engine Report worked check",
         lambda r: rejected(r, "AL6061") and rejected(r, "STEEL_MILD")),
    Case("V6", "Project DOE: 1 m² sandwich panel, two tool-material arms",
         ms.PartDefinition(length_m=1.0, width_m=1.0, cure_temp_C=180, cure_pressure_bar=2,
                           cycles_required=6, profile="production"),
         "At least one low-CTE tool (Invar or CFRP) and one high-CTE tool (aluminium or "
         "mild steel)",
         "Master Report §3.3, §5.5",
         lambda r: r.doe_pair is not None),
]


def run_cases() -> List[tuple]:
    results = []
    for case in CASES:
        result = ms.select(case.part)
        results.append((case, result, case.check(result)))
    return results


def validation_text() -> str:
    lines = ["=" * 78, "VALIDATION SET (D6) — engine vs accepted industry practice", "=" * 78]
    passed = 0
    for case, result, ok in run_cases():
        passed += ok
        winners = ", ".join(top_two(result)) or "none"
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {case.case_id} {case.title}")
        lines.append(f"       expected: {case.expectation}")
        lines.append(f"       engine top-2: {winners}"
                     + ("  (close call)" if result.sweep["close_call"] else ""))
        lines.append(f"       source: {case.source}")
    lines.append(f"\n{passed}/{len(CASES)} cases reproduce the documented choice.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(validation_text())
