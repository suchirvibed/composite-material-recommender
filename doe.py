"""
DOE test-matrix builder for the project's tolerance study.

Implements Master Report §3.2: the candidate independent variables of Table 1,
each at two levels, combined as a full factorial or a half fraction, with
replication (≥3 panels per condition). Every run gets the engine's
*predicted* indicators so the matrix doubles as a pre-test expectation sheet:

  PS1  CTE mismatch δ between tool and part            (mold_selector)
  PS2  cycle time incl. tool-lag hold extension          (cure_planner)
  PS3  corner spring-in for angled runs                  (Albert & Fernlund)

Measured columns (deviation, spring-in, flatness, thickness variation) are
left blank for CMM / 3D-scan results; analyse_main_effects() then estimates
each factor's main effect once they are filled (§3.5 DOE analysis).
"""

from __future__ import annotations

import csv
import itertools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

import cost_estimator as ce
import cure_planner as cp
import mold_selector as ms

MEASURED_COLUMNS = ["measured_deviation_mm", "measured_spring_in_deg",
                    "measured_flatness_mm", "measured_thickness_var_mm"]


@dataclass
class Factor:
    key: str
    label: str
    problem: str            # PS1 / PS2 / PS3
    low: object
    high: object
    note: str = ""


def default_factors() -> List[Factor]:
    """Master Report Table 1 — candidate variables and levels."""
    return [
        Factor("tool", "Tool material", "PS1", "CFRP_BMI", "AL6061",
               "low-CTE (Invar or CFRP tooling) vs high-CTE (aluminium or mild steel)"),
        Factor("pressure", "Cure pressure (bar)", "PS2", 4.0, 6.0,
               "within resin datasheet range"),
        Factor("ramp", "Heating ramp (°C/min)", "PS2", 1.0, 3.0, ""),
        Factor("dwell", "Cure dwell (min)", "PS2", 120.0, 180.0,
               "manufacturer-recommended vs extended"),
        Factor("layup", "Ply stacking", "PS3", "QI symmetric", "unbalanced",
               "symmetric quasi-isotropic vs deliberately unbalanced"),
        Factor("thickness", "Skin thickness (mm)", "PS3", 2.0, 4.0,
               "thin (≤2 mm) vs thick (≥4 mm) skin"),
        Factor("geometry", "Corner geometry", "PS3", "flat", "corner 90°",
               "flat panel baseline vs formed corner"),
    ]


# Master Report §2.4 scoping question: which variation is the study about?
FOCUS_PRESETS = {
    "process": ["tool", "ramp", "dwell"],
    "design": ["layup", "thickness", "geometry"],
    "tooling only": ["tool"],
}


@dataclass
class StudyArticle:
    """The project's study article (Master Report §1.4, §5.1)."""
    length_m: float = 1.0
    width_m: float = 1.0
    sandwich: bool = True
    cure_temp_C: float = 180.0
    base_pressure_bar: float = 2.0          # HexPly M18/1 sandwich cycle
    base_ramp_C_min: float = 2.0
    base_dwell_min: float = 120.0
    base_layup: str = "QI symmetric"
    base_thickness_mm: float = 2.0
    base_geometry: str = "flat"
    base_tool: str = "CFRP_BMI"
    part_cte_ppm: float = 2.0
    cycle_id: str = "M18-1_SAND"


@dataclass
class Run:
    run_id: str
    std_order: int
    replicate: int
    settings: Dict[str, object]
    coded: Dict[str, int]
    predictions: Dict[str, object]
    warnings: List[str] = field(default_factory=list)


def design_points(k: int, half_fraction: bool = False) -> List[tuple]:
    """Coded (−1/+1) runs in standard order; half fraction uses I = ABC…K."""
    full = [tuple(-1 if (i >> j) & 1 == 0 else 1 for j in range(k)) for i in range(2 ** k)]
    if half_fraction and k >= 3:
        full = [p for p in full if np.prod(p) == 1]
    return full


def _settings(article: StudyArticle, factors: List[Factor], point: tuple) -> Dict[str, object]:
    s = {"tool": article.base_tool, "pressure": article.base_pressure_bar,
         "ramp": article.base_ramp_C_min, "dwell": article.base_dwell_min,
         "layup": article.base_layup, "thickness": article.base_thickness_mm,
         "geometry": article.base_geometry}
    for f, c in zip(factors, point):
        s[f.key] = f.low if c < 0 else f.high
    return s


def predict(article: StudyArticle, s: Dict[str, object], materials) -> tuple:
    """Predicted indicators and warnings for one run."""
    warnings = []
    tool = next(m for m in materials if m.material_id == s["tool"])
    angled = str(s["geometry"]).startswith("corner")
    part = ms.PartDefinition(
        length_m=article.length_m, width_m=article.width_m,
        geometry="angled" if angled else "flat", corner_angle_deg=90.0,
        layup="QI", cure_temp_C=article.cure_temp_C,
        cure_pressure_bar=float(s["pressure"]), ramp_rate_C_min=float(s["ramp"]),
        part_cte_ppm=article.part_cte_ppm)
    calc = ms.calculate(tool, part)

    base = cp.get_cycle(article.cycle_id)
    cycle = cp.with_overrides(base, ramp_C_min=float(s["ramp"]), final_hold_min=float(s["dwell"]))
    extension = cp.hold_extension_for_lag(calc.tau_min, float(s["ramp"])) or 0.0
    minutes = cp.total_minutes(cp.schedule(cycle, hold_extension_min=extension))

    if article.sandwich and float(s["pressure"]) > base.pressure_max:
        warnings.append(f"{s['pressure']:g} bar exceeds the {base.pressure_max:g} bar "
                        f"sandwich limit of {base.product} (core crush risk)")
    if calc.tau_min is None:
        warnings.append("tool thermal lag unknown (supplier c_p needed)")
    if s["layup"] == "unbalanced":
        warnings.append("unbalanced layup: warpage expected beyond the Eq. 1 corner value")
    if float(s["thickness"]) <= 2.0 and angled:
        warnings.append("thin angled part: highest warpage sensitivity (Albert & Fernlund)")

    spring = ms.corner_spring_in(part) if angled else None
    return {
        "tool_alpha_ppm": round(calc.alpha_tool, 2),
        "pred_cte_mismatch_mm": round(calc.delta_mm, 3),
        "pred_tool_lag_C": None if calc.lag_C is None else round(calc.lag_C, 1),
        "hold_extension_min": round(extension, 1),
        "pred_cycle_min": round(minutes, 1),
        "pred_corner_spring_in_deg": None if spring is None else round(spring["spring_in_deg"], 2),
    }, warnings


def build_matrix(article: StudyArticle, factors: List[Factor], replicates: int = 3,
                 half_fraction: bool = False, randomize: bool = True, seed: int = 1) -> List[Run]:
    materials = ms.load_tool_materials()
    points = design_points(len(factors), half_fraction)
    runs = []
    for order, point in enumerate(points, 1):
        settings = _settings(article, factors, point)
        predictions, warnings = predict(article, settings, materials)
        for rep in range(1, replicates + 1):
            runs.append(Run(f"R{order:02d}-{rep}", order, rep, settings,
                            {f.key: c for f, c in zip(factors, point)}, predictions, warnings))
    if randomize:
        rng = np.random.default_rng(seed)
        runs = [runs[i] for i in rng.permutation(len(runs))]
    return runs


def study_cost(article: StudyArticle, runs: List[Run]) -> dict:
    """One mould per tool level (reused), consumables for every panel."""
    by_material = {r["tool_material_id"]: r["mould_type"]
                   for r in ce.mould_options() if r["tool_material_id"]}
    tools = sorted({r.settings["tool"] for r in runs})
    area = article.length_m * article.width_m
    mould_low = mould_high = 0.0
    unpriced = []
    for t in tools:
        if t in by_material:
            lo, hi = ce.mould_cost(by_material[t], area)
            mould_low, mould_high = mould_low + lo, mould_high + hi
        else:
            unpriced.append(t)
    clow, chigh = ce.total(ce.panel_bom(article.length_m, article.width_m, article.sandwich))
    n = len(runs)
    return {"tools": tools, "unpriced_tools": unpriced, "panels": n,
            "mould": (mould_low, mould_high), "consumables": (clow * n, chigh * n),
            "total": (mould_low + clow * n, mould_high + chigh * n)}


def write_csv(runs: List[Run], factors: List[Factor], path: Path) -> Path:
    keys = [f.key for f in factors]
    pred_keys = list(runs[0].predictions) if runs else []
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["run_order", "run_id", "std_order", "replicate"] + keys
                   + [f"{k}_coded" for k in keys] + pred_keys + ["warnings"] + MEASURED_COLUMNS)
        for i, r in enumerate(runs, 1):
            w.writerow([i, r.run_id, r.std_order, r.replicate]
                       + [r.settings[k] for k in keys] + [r.coded[k] for k in keys]
                       + [r.predictions[k] for k in pred_keys] + ["; ".join(r.warnings)]
                       + [""] * len(MEASURED_COLUMNS))
    return path


def analyse_main_effects(path: Path, response: str = "measured_deviation_mm") -> dict:
    """
    Main effect of each coded factor on a measured response:
    effect = mean(response | +1) − mean(response | −1), with a t-ratio against
    the replicate (pure-error) standard deviation. Use ANOVA software for the
    full interaction analysis (Master Report §3.5).
    """
    with open(path, encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get(response, "").strip()]
    if len(rows) < 4:
        raise ValueError(f"Need at least 4 measured rows in '{response}'.")
    y = np.array([float(r[response]) for r in rows])
    coded = [c[:-6] for c in rows[0] if c.endswith("_coded")]

    by_cell: Dict[str, list] = {}
    for r, v in zip(rows, y):
        by_cell.setdefault(r["std_order"], []).append(v)
    dof = sum(len(v) - 1 for v in by_cell.values())
    pooled = (np.sqrt(sum(((np.array(v) - np.mean(v)) ** 2).sum() for v in by_cell.values()) / dof)
              if dof > 0 else np.nan)

    effects = {}
    for k in coded:
        c = np.array([int(r[f"{k}_coded"]) for r in rows])
        if len(set(c)) < 2:
            continue
        hi, lo = y[c == 1], y[c == -1]
        effect = hi.mean() - lo.mean()
        se = pooled * np.sqrt(1 / len(hi) + 1 / len(lo)) if np.isfinite(pooled) else np.nan
        effects[k] = {"effect": float(effect), "t_ratio": float(effect / se) if se else np.nan,
                      "mean_low": float(lo.mean()), "mean_high": float(hi.mean())}
    ranked = dict(sorted(effects.items(), key=lambda kv: -abs(kv[1]["effect"])))
    return {"response": response, "n": len(rows), "pooled_sd": float(pooled), "effects": ranked}
