"""
Mold (tool) Material Selection — Matrix Scoring Engine

Implements the project's Matrix Engine Report (deliverables D2-D5):

  1. User input      part envelope, geometry, cure temperature/pressure/ramp,
                     tolerance, cycle count, cost ceiling, application profile
  2. Feasibility     hard constraints as pass/fail, with the reason for every
                     rejection (a filter, never a score)
  3. Engineering     physics indices per surviving material:
                       CTE mismatch error   δ = |α_tool − α_part| · ΔT · L
                       thermal lag          τ = ρ·c_p·t / h,  lag = ramp · τ
                       tool mass            M = ρ · A · t
                       durability (cycle life) and tool cost (₹, area-scaled)
  4. Scoring         direction-aware min-max normalisation across survivors,
                     AHP-derived profile weights, ranking, and a weight sweep
                     that flags close calls

Data: tooling_data/tool_materials.csv (every value sourced, see SOURCES.md).
The engine ranks tool materials; it does not simulate the part and cannot
replace FEM distortion prediction (Matrix Engine Report, known limitations).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from ahp import CR_THRESHOLD, ahp

BASE_DIR = Path(__file__).resolve().parent
TOOL_FILE = BASE_DIR / "tooling_data" / "tool_materials.csv"

# Measured heat-transfer coefficients (Fisher, Levy & Kratz 2022): oven mean
# 37 W/m²K (≈1 bar), autoclave means 99 W/m²K at 3 bar and 138 W/m²K at 7 bar.
HTC_POINTS = [(1.0, 37.0), (3.0, 99.0), (7.0, 138.0)]

# Corner spring-in predicted by Albert & Fernlund (2002) Eq. 1 for a 90° part,
# T800H/3900-2 cured at 180 °C (project spring-in summary, Table 1).
CORNER_SPRING_IN_90 = {"UD": 0.90, "QI": 1.28}
SPRING_IN_REFERENCE_CURE_C = 180.0

CRITERIA = ["dimensional_error", "thermal_lag", "tool_mass", "durability", "tool_cost"]
BENEFIT = {"durability": True, "surface": True}          # others: lower is better
CRITERION_LABEL = {
    "dimensional_error": "CTE mismatch δ [mm]",
    "thermal_lag": "Thermal lag [°C]",
    "tool_mass": "Tool mass [kg]",
    "durability": "Cycle life [cycles]",
    "tool_cost": "Tool cost [₹]",
    "surface": "Class-A surface",
}

# Pairwise judgments (Saaty 1-9) for the three profiles of the Matrix Engine
# Report, over CRITERIA in order. Each pair: how much more important the first
# criterion is than the second.
PROFILE_JUDGMENTS = {
    "prototype": {   # "cost and lead time dominant; tolerance relaxed"
        ("dimensional_error", "thermal_lag"): 1, ("dimensional_error", "tool_mass"): 1,
        ("dimensional_error", "durability"): 1, ("dimensional_error", "tool_cost"): 1 / 7,
        ("thermal_lag", "tool_mass"): 1, ("thermal_lag", "durability"): 1,
        ("thermal_lag", "tool_cost"): 1 / 7, ("tool_mass", "durability"): 1,
        ("tool_mass", "tool_cost"): 1 / 7, ("durability", "tool_cost"): 1 / 7,
    },
    "production": {  # "balanced — durability and cycle time weighted up"
        ("dimensional_error", "thermal_lag"): 1, ("dimensional_error", "tool_mass"): 3,
        ("dimensional_error", "durability"): 1, ("dimensional_error", "tool_cost"): 2,
        ("thermal_lag", "tool_mass"): 3, ("thermal_lag", "durability"): 1,
        ("thermal_lag", "tool_cost"): 2, ("tool_mass", "durability"): 1 / 3,
        ("tool_mass", "tool_cost"): 1 / 2, ("durability", "tool_cost"): 2,
    },
    "aerospace": {   # "CTE match and dimensional stability dominant"
        ("dimensional_error", "thermal_lag"): 7, ("dimensional_error", "tool_mass"): 7,
        ("dimensional_error", "durability"): 5, ("dimensional_error", "tool_cost"): 7,
        ("thermal_lag", "tool_mass"): 1, ("thermal_lag", "durability"): 1 / 2,
        ("thermal_lag", "tool_cost"): 1, ("tool_mass", "durability"): 1 / 2,
        ("tool_mass", "tool_cost"): 1, ("durability", "tool_cost"): 2,
    },
}
PROFILE_DESCRIPTION = {
    "prototype": "Prototype / low rate — cost dominant, tolerance relaxed",
    "production": "Production — balanced, durability and cycle time weighted up",
    "aerospace": "High-precision aerospace — CTE match and dimensional stability dominant",
}

SWEEP_FACTORS = (0.8, 1.2)        # ±20 % on each weight, renormalised
SURFACE_SCORE = {"yes": 1.0, "machined": 0.5, "no": 0.0}


# ------------------------------------------------------------------
# Data
# ------------------------------------------------------------------

def _num(text: str) -> Optional[float]:
    text = (text or "").strip()
    return float(text) if text else None


@dataclass
class ToolMaterial:
    material_id: str
    name: str
    material_class: str
    cte_ppm: float
    cte_curve: List[tuple]
    density: Optional[float]
    specific_heat: Optional[float]
    conductivity: Optional[float]
    max_service_C: Optional[float]
    max_service_basis: str
    cycle_life_class: str
    cycle_life_min: Optional[float]
    cost_low: Optional[float]
    cost_high: Optional[float]
    cost_basis: str
    needs_sealing: bool
    class_a: str
    default_thickness_mm: float
    density_basis: str
    sources: str

    def cte_at(self, temp_C: float) -> float:
        """Mean CTE from room temperature to temp_C (interpolated when a curve exists)."""
        if not self.cte_curve:
            return self.cte_ppm
        temps = [t for t, _ in self.cte_curve]
        values = [v for _, v in self.cte_curve]
        return float(np.interp(temp_C, temps, values))


def load_tool_materials(path: Path = TOOL_FILE) -> List[ToolMaterial]:
    materials = []
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            curve = []
            if r["cte_curve_C_ppm"].strip():
                curve = [tuple(float(x) for x in pair.split(":"))
                         for pair in r["cte_curve_C_ppm"].split(";")]
            materials.append(ToolMaterial(
                material_id=r["material_id"], name=r["name"], material_class=r["material_class"],
                cte_ppm=float(r["cte_ppm_C"]), cte_curve=curve,
                density=_num(r["density_kg_m3"]), specific_heat=_num(r["specific_heat_J_kgK"]),
                conductivity=_num(r["conductivity_W_mK"]),
                max_service_C=_num(r["max_service_temp_C"]), max_service_basis=r["max_service_basis"],
                cycle_life_class=r["cycle_life_class"], cycle_life_min=_num(r["cycle_life_min"]),
                cost_low=_num(r["cost_inr_low_per_m2"]), cost_high=_num(r["cost_inr_high_per_m2"]),
                cost_basis=r["cost_basis"], needs_sealing=r["needs_surface_sealing"] == "yes",
                class_a=r["class_a_surface"], default_thickness_mm=float(r["default_face_thickness_mm"]),
                density_basis=r["density_basis"], sources=r["sources"],
            ))
    return materials


# ------------------------------------------------------------------
# Inputs
# ------------------------------------------------------------------

@dataclass
class PartDefinition:
    length_m: float
    width_m: float
    height_m: float = 0.05
    geometry: str = "flat"                 # flat | curved | angled
    corner_angle_deg: float = 90.0         # for angled parts
    layup: str = "QI"                      # UD | QI
    cure_temp_C: float = 180.0
    cure_pressure_bar: float = 6.0
    ramp_rate_C_min: float = 2.0
    ambient_C: float = 25.0
    part_cte_ppm: float = 2.0              # carbon/epoxy ≈ 2 µε/°C (Matrix Engine Report)
    tolerance_mm: Optional[float] = None   # allowed dimensional deviation over the part length
    tolerance_hard: bool = False
    cycles_required: int = 50
    cost_ceiling_inr: Optional[float] = None
    class_a_surface: bool = False
    autoclave_length_m: Optional[float] = None
    autoclave_diameter_m: Optional[float] = None
    service_margin_C: float = 20.0         # tool must exceed cure temp by this margin
    profile: str = "production"
    thickness_override_mm: Dict[str, float] = field(default_factory=dict)

    @property
    def delta_T(self) -> float:
        return self.cure_temp_C - self.ambient_C

    @property
    def area_m2(self) -> float:
        return self.length_m * self.width_m

    @property
    def governing_length_mm(self) -> float:
        return 1000.0 * max(self.length_m, self.width_m)


def heat_transfer_coefficient(pressure_bar: float) -> float:
    """Autoclave/oven HTC interpolated from Fisher et al. (2022) measured means."""
    p = [x for x, _ in HTC_POINTS]
    h = [y for _, y in HTC_POINTS]
    return float(np.interp(pressure_bar, p, h))


def profile_weights(profile: str) -> tuple[Dict[str, float], float]:
    if profile not in PROFILE_JUDGMENTS:
        raise ValueError(f"Unknown profile '{profile}'. Choose: {', '.join(PROFILE_JUDGMENTS)}")
    return ahp(CRITERIA, PROFILE_JUDGMENTS[profile])


# ------------------------------------------------------------------
# Stage 2 — feasibility gate
# ------------------------------------------------------------------

@dataclass
class GateResult:
    material: ToolMaterial
    passed: bool
    rejections: List[str]
    flags: List[str]


def part_level_rejections(part: PartDefinition) -> List[str]:
    """Constraints that no tool material can fix (autoclave envelope)."""
    reasons = []
    if part.autoclave_length_m and part.length_m > part.autoclave_length_m:
        reasons.append(f"Part length {part.length_m} m exceeds autoclave length "
                       f"{part.autoclave_length_m} m.")
    if part.autoclave_diameter_m:
        section = float(np.hypot(part.width_m, part.height_m))
        if section > part.autoclave_diameter_m:
            reasons.append(f"Part cross-section diagonal {section:.2f} m exceeds autoclave "
                           f"diameter {part.autoclave_diameter_m} m.")
    return reasons


def feasibility(material: ToolMaterial, part: PartDefinition) -> GateResult:
    rejections, flags = [], []
    required_temp = part.cure_temp_C + part.service_margin_C

    if material.max_service_C is None:
        flags.append("Maximum service temperature not published — verify before use.")
    elif material.max_service_C < required_temp:
        rejections.append(
            f"Service temperature {material.max_service_C:.0f} °C < cure {part.cure_temp_C:.0f} °C "
            f"+ {part.service_margin_C:.0f} °C margin ({material.max_service_basis}).")

    if material.cycle_life_min is None:
        flags.append("Cycle life not stated in project documents — verify with supplier.")
    elif material.cycle_life_min < part.cycles_required:
        rejections.append(
            f"Cycle life ~{material.cycle_life_min:.0f} ('{material.cycle_life_class}') "
            f"< {part.cycles_required} cycles required.")

    cost = tool_cost_range(material, part)
    if part.cost_ceiling_inr is not None:
        if cost is None:
            flags.append("No ₹ cost data — cost ceiling cannot be checked.")
        elif cost[0] > part.cost_ceiling_inr:
            rejections.append(
                f"Estimated tool cost ₹{cost[0]:,.0f}-{cost[1]:,.0f} exceeds the "
                f"₹{part.cost_ceiling_inr:,.0f} ceiling.")
        elif cost[1] > part.cost_ceiling_inr:
            flags.append(f"Upper cost estimate ₹{cost[1]:,.0f} exceeds the ceiling — get quotes.")

    if part.tolerance_hard and part.tolerance_mm is not None:
        delta = cte_mismatch_mm(material, part)
        if delta > part.tolerance_mm:
            rejections.append(
                f"CTE mismatch error δ = {delta:.2f} mm exceeds the HARD tolerance "
                f"{part.tolerance_mm:.2f} mm.")

    if part.class_a_surface:
        if material.class_a == "no":
            rejections.append("Cannot provide a Class-A surface (tooling report).")
        elif material.class_a == "machined":
            flags.append("Class-A needs precision machining and polishing; an electroformed "
                         "nickel shell is the reference choice for Class-A (tooling report).")

    if material.needs_sealing:
        flags.append("Porous surface: seal the tool for vacuum integrity before use.")
    if "UNVERIFIED" in material.cost_basis:
        flags.append("Cost data UNVERIFIED (see tooling_data/SOURCES.md).")
    if material.material_id == "INVAR36":
        flags.append("Long procurement/machining lead time (weeks) per project report.")

    return GateResult(material, not rejections, rejections, flags)


# ------------------------------------------------------------------
# Stage 3 — engineering calculations
# ------------------------------------------------------------------

def tool_thickness_mm(material: ToolMaterial, part: PartDefinition) -> float:
    return part.thickness_override_mm.get(material.material_id, material.default_thickness_mm)


def cte_mismatch_mm(material: ToolMaterial, part: PartDefinition) -> float:
    alpha_tool = material.cte_at(part.cure_temp_C)
    return abs(alpha_tool - part.part_cte_ppm) * 1e-6 * part.delta_T * part.governing_length_mm


def tool_cost_range(material: ToolMaterial, part: PartDefinition) -> Optional[tuple]:
    if material.cost_low is None or material.cost_high is None:
        return None
    return material.cost_low * part.area_m2, material.cost_high * part.area_m2


@dataclass
class Calculation:
    material: ToolMaterial
    alpha_tool: float
    delta_mm: float
    mismatch_strain: float
    thickness_mm: float
    mass_kg: Optional[float]
    tau_min: Optional[float]
    lag_C: Optional[float]
    biot: Optional[float]
    cycle_life: Optional[float]
    cost_mid: Optional[float]
    cost_range: Optional[tuple]
    surface: float
    notes: List[str]

    def criterion(self, name: str) -> Optional[float]:
        return {
            "dimensional_error": self.delta_mm, "thermal_lag": self.lag_C,
            "tool_mass": self.mass_kg, "durability": self.cycle_life,
            "tool_cost": self.cost_mid, "surface": self.surface,
        }[name]


def calculate(material: ToolMaterial, part: PartDefinition) -> Calculation:
    notes = []
    t_mm = tool_thickness_mm(material, part)
    t = t_mm / 1000.0
    alpha = material.cte_at(part.cure_temp_C)
    delta = cte_mismatch_mm(material, part)

    mass = material.density * part.area_m2 * t if material.density else None
    if material.density_basis.startswith("ANALOGUE"):
        notes.append("Density is an analogue value (manufacturer density not published).")

    h = heat_transfer_coefficient(part.cure_pressure_bar)
    tau_min = lag = biot = None
    if material.density and material.specific_heat:
        tau_s = material.density * material.specific_heat * t / h
        tau_min = tau_s / 60.0
        lag = part.ramp_rate_C_min * tau_min              # steady-ramp lag of a lumped tool
        if material.conductivity:
            biot = h * t / material.conductivity
            if biot > 0.1:
                notes.append(f"Biot number {biot:.2f} > 0.1: through-thickness gradients "
                             f"matter; lumped thermal lag is optimistic.")
    else:
        notes.append("Thermal lag not computed — specific heat not published (supplier data needed).")

    cost = tool_cost_range(material, part)
    return Calculation(
        material=material, alpha_tool=alpha, delta_mm=delta,
        mismatch_strain=abs(alpha - part.part_cte_ppm) * 1e-6 * part.delta_T,
        thickness_mm=t_mm, mass_kg=mass, tau_min=tau_min, lag_C=lag, biot=biot,
        cycle_life=material.cycle_life_min,
        cost_mid=(sum(cost) / 2 if cost else None), cost_range=cost,
        surface=SURFACE_SCORE.get(material.class_a, 0.0), notes=notes,
    )


def corner_spring_in(part: PartDefinition) -> Optional[dict]:
    """Tool-independent corner spring-in estimate for angled parts."""
    if part.geometry != "angled":
        return None
    base = CORNER_SPRING_IN_90.get(part.layup)
    if base is None:
        return None
    angle = base * part.corner_angle_deg / 90.0     # spring-in scales with part angle
    note = ("Albert & Fernlund (2002) Eq. 1 prediction for T800H/3900-2 at 180 °C; "
            "use as a starting compensation and calibrate with trial parts.")
    if abs(part.cure_temp_C - SPRING_IN_REFERENCE_CURE_C) > 20:
        note += f" Cure at {part.cure_temp_C:.0f} °C is outside the reference condition."
    return {"spring_in_deg": angle, "tool_angle_deg": part.corner_angle_deg + angle, "note": note}


# ------------------------------------------------------------------
# Stage 4 — scoring, ranking, sensitivity
# ------------------------------------------------------------------

@dataclass
class Ranked:
    calc: Calculation
    normalized: Dict[str, float]
    imputed: List[str]
    score: float
    rank: int = 0


def normalise(calcs: List[Calculation], criteria: List[str]) -> List[tuple]:
    """
    Direction-aware min-max across survivors.

    A missing value scores 0 ("not demonstrated") and is flagged. Imputing a
    median instead let a material with mostly unpublished data out-rank fully
    documented ones.
    """
    table = {c: [calc.criterion(c) for calc in calcs] for c in criteria}
    out = [({}, []) for _ in calcs]
    for c, values in table.items():
        known = [v for v in values if v is not None]
        lo, hi = (min(known), max(known)) if known else (0.0, 0.0)
        normed = []
        for v in values:
            if v is None:
                normed.append(None)
            elif hi == lo:
                normed.append(1.0)
            elif BENEFIT.get(c):
                normed.append((v - lo) / (hi - lo))
            else:
                normed.append((hi - v) / (hi - lo))
        for i, n in enumerate(normed):
            out[i][0][c] = 0.0 if n is None else n
            if n is None:
                out[i][1].append(c)
    return out


def rank(calcs: List[Calculation], weights: Dict[str, float]) -> List[Ranked]:
    criteria = list(weights)
    ranked = []
    for calc, (normed, imputed) in zip(calcs, normalise(calcs, criteria)):
        score = sum(weights[c] * normed[c] for c in criteria)
        ranked.append(Ranked(calc, normed, imputed, score))
    ranked.sort(key=lambda r: (-r.score, r.calc.delta_mm, r.calc.material.name))
    for i, r in enumerate(ranked, 1):
        r.rank = i
    return ranked


def weight_sweep(calcs: List[Calculation], weights: Dict[str, float]) -> dict:
    """Perturb each weight ±20 % and see whether the winner changes."""
    base_winner = rank(calcs, weights)[0].calc.material.material_id
    trials, changes = 0, {}
    for c in weights:
        for f in SWEEP_FACTORS:
            w = dict(weights)
            w[c] *= f
            total = sum(w.values())
            w = {k: v / total for k, v in w.items()}
            winner = rank(calcs, w)[0].calc.material.material_id
            trials += 1
            if winner != base_winner:
                changes[f"{c} ×{f}"] = winner
    return {"trials": trials, "stable": trials - len(changes), "changes": changes,
            "close_call": bool(changes)}


@dataclass
class SelectionResult:
    part: PartDefinition
    weights: Dict[str, float]
    consistency_ratio: float
    part_rejections: List[str]
    gates: List[GateResult]
    ranking: List[Ranked]
    sweep: dict
    spring_in: Optional[dict]
    htc: float
    doe_pair: Optional[tuple]


# DOE arms named in the Master Report (Table 1): low-CTE = Invar or CFRP
# tooling prepreg, high-CTE = aluminium or mild steel.
DOE_LOW_CTE = {"INVAR36", "CFRP_BMI"}
DOE_HIGH_CTE = {"AL6061", "STEEL_MILD"}


def doe_pairing(ranking: List[Ranked]) -> Optional[tuple]:
    """Best-ranked low-CTE and high-CTE survivor for the project's tool-material DOE."""
    low = [r for r in ranking if r.calc.material.material_id in DOE_LOW_CTE]
    high = [r for r in ranking if r.calc.material.material_id in DOE_HIGH_CTE]
    if low and high:
        return low[0].calc.material, high[0].calc.material
    return None


def select(part: PartDefinition, materials: Optional[List[ToolMaterial]] = None) -> SelectionResult:
    materials = materials if materials is not None else load_tool_materials()
    weights, cr = profile_weights(part.profile)
    if part.class_a_surface:
        # Add the surface criterion with the weight of dimensional error, renormalised.
        weights = dict(weights, surface=weights["dimensional_error"])
        total = sum(weights.values())
        weights = {k: v / total for k, v in weights.items()}

    part_reasons = part_level_rejections(part)
    gates = [feasibility(m, part) for m in materials]
    if part_reasons:
        for g in gates:
            g.passed, g.rejections = False, part_reasons + g.rejections

    survivors = [calculate(g.material, part) for g in gates if g.passed]
    ranking = rank(survivors, weights) if survivors else []
    sweep = weight_sweep(survivors, weights) if len(survivors) > 1 else \
        {"trials": 0, "stable": 0, "changes": {}, "close_call": False}

    return SelectionResult(
        part=part, weights=weights, consistency_ratio=cr, part_rejections=part_reasons,
        gates=gates, ranking=ranking, sweep=sweep, spring_in=corner_spring_in(part),
        htc=heat_transfer_coefficient(part.cure_pressure_bar), doe_pair=doe_pairing(ranking),
    )


# ------------------------------------------------------------------
# D5 — report card
# ------------------------------------------------------------------

def _fmt(value, spec: str, none: str = "n/a") -> str:
    return none if value is None else format(value, spec)


def report_card(result: SelectionResult) -> str:
    p = result.part
    lines = []
    add = lines.append
    add("=" * 78)
    add("MOLD MATERIAL SELECTION — REPORT CARD")
    add("=" * 78)
    add(f"Part: {p.length_m} × {p.width_m} × {p.height_m} m ({p.geometry}"
        + (f", {p.corner_angle_deg:.0f}° {p.layup}" if p.geometry == "angled" else "") + ")")
    add(f"Cure: {p.cure_temp_C:.0f} °C, {p.cure_pressure_bar:.1f} bar, ramp {p.ramp_rate_C_min} °C/min "
        f"(ΔT {p.delta_T:.0f} °C, HTC {result.htc:.0f} W/m²K)")
    tol = "none" if p.tolerance_mm is None else f"{p.tolerance_mm} mm ({'HARD' if p.tolerance_hard else 'target'})"
    add(f"Tolerance: {tol} | Cycles: {p.cycles_required} | Cost ceiling: "
        + ("none" if p.cost_ceiling_inr is None else f"₹{p.cost_ceiling_inr:,.0f}")
        + (" | Class-A surface required" if p.class_a_surface else ""))
    add(f"Profile: {PROFILE_DESCRIPTION[p.profile]}")
    add("Weights: " + ", ".join(f"{CRITERION_LABEL[c].split(' [')[0]} {w:.2f}"
                                for c, w in result.weights.items())
        + f"  (AHP CR {result.consistency_ratio:.3f} {'OK' if result.consistency_ratio < CR_THRESHOLD else 'INCONSISTENT'})")

    add("\nFEASIBILITY GATE")
    for g in result.gates:
        mark = "PASS" if g.passed else "REJECT"
        add(f"  [{mark:<6}] {g.material.name}")
        for reason in g.rejections:
            add(f"           ✗ {reason}")

    if not result.ranking:
        add("\nNo tool material passes every hard constraint. Relax the constraint named "
            "most often above.")
        return "\n".join(lines)

    add("\nENGINEERING CALCULATIONS (survivors)")
    add(f"  {'Material':<44}{'α@cure':>7}{'δ mm':>7}{'lag °C':>8}{'mass kg':>9}"
        f"{'cycles':>8}{'cost ₹':>12}")
    for r in result.ranking:
        c = r.calc
        add(f"  {c.material.name[:43]:<44}{c.alpha_tool:>7.1f}{c.delta_mm:>7.2f}"
            f"{_fmt(c.lag_C, '.1f'):>8}{_fmt(c.mass_kg, '.0f'):>9}"
            f"{_fmt(c.cycle_life, '.0f'):>8}{_fmt(c.cost_mid, ',.0f'):>12}")

    add("\nRANKING (score 0-1; criterion contributions)")
    for r in result.ranking:
        parts = ", ".join(f"{CRITERION_LABEL[c].split(' [')[0]} {result.weights[c] * r.normalized[c]:.2f}"
                          for c in result.weights)
        add(f"  #{r.rank} {r.calc.material.name} — {r.score:.3f}")
        add(f"      {parts}")
        if r.imputed:
            add(f"      data gap (scored 0 — not demonstrated): {', '.join(r.imputed)}")

    sweep = result.sweep
    add("\nSENSITIVITY (each weight ±20 %)")
    if sweep["close_call"]:
        runner = result.ranking[1].calc.material.name if len(result.ranking) > 1 else "-"
        add(f"  CLOSE CALL: winner changes in {len(sweep['changes'])}/{sweep['trials']} perturbations "
            f"({', '.join(f'{k} → {v}' for k, v in sweep['changes'].items())}).")
        add(f"  Report the top two together: {result.ranking[0].calc.material.name} and {runner}.")
    else:
        add(f"  Stable: the winner is unchanged in all {sweep['trials']} perturbations.")

    if result.spring_in:
        s = result.spring_in
        add("\nSPRING-IN (tool-independent corner component)")
        add(f"  Expected spring-in ≈ {s['spring_in_deg']:.2f}° → start with a tool angle of "
            f"{s['tool_angle_deg']:.2f}° for a {p.corner_angle_deg:.0f}° part.")
        add(f"  {s['note']}")
        add("  Warpage component is process-driven: gel at the final hold, use FEP release film, "
            "and match tool CTE (Albert & Fernlund rules).")

    if result.doe_pair:
        low, high = result.doe_pair
        add("\nDOE TOOL PAIRING (project tool-material study)")
        add(f"  Low-CTE arm: {low.name}  |  High-CTE arm: {high.name}")

    add("\nRISK FLAGS")
    shown = False
    for r in result.ranking:
        gate = next(g for g in result.gates if g.material is r.calc.material)
        for f in gate.flags + r.calc.notes:
            add(f"  • {r.calc.material.name}: {f}")
            shown = True
    if not shown:
        add("  none")
    add("\nNote: the engine ranks tool materials; it does not replace FEM distortion "
        "prediction or trial parts.")
    return "\n".join(lines)
