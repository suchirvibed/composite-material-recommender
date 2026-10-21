"""
BOM and cost estimator for the autoclave prepreg study (₹, indicative).

Data: process_data/bom_consumables.csv (process consumables for a 1 m²
carbon/epoxy honeycomb sandwich panel) and process_data/mold_cost_options.csv
(mould cost for ~1 m²), both transcribed from the project document
"Autoclave Prepeg process BOM and cost". All figures are indicative and should
be re-quoted against local suppliers (Master Report §5).

Scaling from the 1 m² basis (an assumption, stated in the output):
  area       ∝ panel area           (skins, core, films, fabrics, wastage)
  perimeter  ∝ panel perimeter / 4 m (sealant tape, edge dams)
  per_panel  fixed per panel        (ports, hoses, thermocouples, inserts)
Mould cost scales with tool face area.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

BASE_DIR = Path(__file__).resolve().parent
BOM_FILE = BASE_DIR / "process_data" / "bom_consumables.csv"
MOLD_FILE = BASE_DIR / "process_data" / "mold_cost_options.csv"
BASIS_PERIMETER_M = 4.0        # 1 m × 1 m basis panel


@dataclass
class Line:
    item: str
    low: float
    high: float
    basis: str


def _rows(path: Path) -> List[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def mould_options() -> List[dict]:
    return _rows(MOLD_FILE)


def panel_bom(length_m: float = 1.0, width_m: float = 1.0, sandwich: bool = True) -> List[Line]:
    area = length_m * width_m
    perimeter = 2 * (length_m + width_m)
    factor = {"area": area, "perimeter": perimeter / BASIS_PERIMETER_M, "per_panel": 1.0}
    lines = []
    for r in _rows(BOM_FILE):
        if r["sandwich_only"] == "yes" and not sandwich:
            continue
        f = factor[r["scaling"]]
        lines.append(Line(r["item"], float(r["inr_low"]) * f, float(r["inr_high"]) * f,
                          f"{r['basis_quantity']} per m² basis, scaled by {r['scaling']}"))
    return lines


def total(lines: List[Line]) -> tuple:
    return sum(l.low for l in lines), sum(l.high for l in lines)


def mould_cost(mould_type: str, tool_area_m2: float = 1.0) -> tuple:
    for r in mould_options():
        if r["mould_type"] == mould_type:
            return float(r["inr_low"]) * tool_area_m2, float(r["inr_high"]) * tool_area_m2
    raise KeyError(f"Unknown mould type '{mould_type}'")


@dataclass
class Scenario:
    name: str
    moulds: List[str]
    mould_cost: tuple
    consumables: tuple
    panels: int

    @property
    def total(self) -> tuple:
        return (self.mould_cost[0] + self.consumables[0], self.mould_cost[1] + self.consumables[1])


def study_cost(moulds: List[str], panels_per_condition: int = 3, length_m: float = 1.0,
               width_m: float = 1.0, sandwich: bool = True, name: str = "Custom") -> Scenario:
    """DOE study: one mould per condition, reused for that condition's panels."""
    area = length_m * width_m
    mlow = sum(mould_cost(m, area)[0] for m in moulds)
    mhigh = sum(mould_cost(m, area)[1] for m in moulds)
    panels = panels_per_condition * len(moulds)
    clow, chigh = total(panel_bom(length_m, width_m, sandwich))
    return Scenario(name, moulds, (mlow, mhigh), (clow * panels, chigh * panels), panels)


# Master Report Table 6 scenarios (2 conditions × 3 panels).
MASTER_SCENARIOS = {
    "Low-cost": ["PU tooling board", "Aluminium mould"],
    "Mid-range": ["Composite tooling", "Aluminium mould"],
    "Aerospace-grade": ["Invar mould", "Mild steel mould"],
}


def inr(x: float) -> str:
    """Indian digit grouping, e.g. 121500 -> 1,21,500."""
    s = f"{x:.0f}"
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups) + "," + tail


def bom_text(length_m: float = 1.0, width_m: float = 1.0, sandwich: bool = True,
             moulds: Optional[List[str]] = None, panels_per_condition: int = 3) -> str:
    lines = panel_bom(length_m, width_m, sandwich)
    low, high = total(lines)
    out = ["=" * 78, f"BOM & COST — {length_m} × {width_m} m "
           f"{'sandwich' if sandwich else 'monolithic'} panel (₹, indicative)", "=" * 78]
    for l in lines:
        out.append(f"  {l.item:<34} ₹{inr(l.low):>9} – ₹{inr(l.high):<9} ({l.basis})")
    out.append(f"\n  Consumables per panel: ₹{inr(low)} – ₹{inr(high)}")

    scenarios = ([study_cost(moulds, panels_per_condition, length_m, width_m, sandwich)]
                 if moulds else
                 [study_cost(m, panels_per_condition, length_m, width_m, sandwich, name)
                  for name, m in MASTER_SCENARIOS.items()])
    out.append(f"\nDOE STUDY SCENARIOS ({panels_per_condition} panels per condition, one mould per condition)")
    for s in scenarios:
        out.append(f"  {s.name:<16} {' + '.join(s.moulds)}")
        out.append(f"  {'':<16} moulds ₹{inr(s.mould_cost[0])}–{inr(s.mould_cost[1])} | "
                   f"{s.panels} panels ₹{inr(s.consumables[0])}–{inr(s.consumables[1])} | "
                   f"total ₹{inr(s.total[0])}–{inr(s.total[1])}")
    if any("Mild steel" in m for s in scenarios for m in s.moulds):
        out.append("\n  ! Mild steel mould ₹3k–13k is UNVERIFIED (10–100× below aluminium) — confirm.")
    out.append("  Scaling from the 1 m² basis is linear (area / perimeter / per panel); "
               "re-quote with two suppliers before budgeting (Master Report §5.6).")
    return "\n".join(out)
