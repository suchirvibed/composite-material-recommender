"""
Prepreg selector: requirements in, carbon-fiber prepreg and its datasheet
cure cycle out.

Data
  Prepreg_Master_Database_v2_Expanded.csv           the project prepreg database (48 systems)
  literature_data/prepreg_laminate_properties.csv   cured-laminate values from each system's
                                                    datasheet (one row per published fiber variant)
  process_data/prepreg_cure_map.csv                 which documented cure cycle belongs to which
                                                    prepreg, by part type / thickness / equipment

Method
  1. Hard filters (pass/fail, reason given): 0° tensile strength ≥ required,
     0° tensile modulus ≥ required, laminate density ≤ allowed, dry Tg ≥ required,
     fiber form, equipment (oven-only shops need a vacuum-bag-only cycle) and a
     documented cure cycle for the part type.
  2. Survivors are scored 0-1 (min-max across survivors): specific strength
     σ/ρ 50 %, specific modulus E/ρ 30 %, Tg 20 %.
  3. The best prepreg's cure cycle is taken from its own datasheet via the map.
  Prepregs with no published laminate data are listed as "datasheet needed",
  never given guessed properties.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import cure_planner as cp

BASE_DIR = Path(__file__).resolve().parent
MASTER_FILE = BASE_DIR / "Prepreg_Master_Database_v2_Expanded.csv"
PROPERTY_FILE = BASE_DIR / "literature_data" / "prepreg_laminate_properties.csv"
CURE_MAP_FILE = BASE_DIR / "process_data" / "prepreg_cure_map.csv"
THICK_LAMINATE_MM = 15.0        # HexPly M21: separate cycle for 15-48 mm parts
WEIGHTS = {"specific_strength": 0.5, "specific_modulus": 0.3, "tg": 0.2}


def _rows(path: Path) -> List[dict]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _num(text) -> Optional[float]:
    text = "" if text is None else str(text).strip()
    try:
        return float(text) if text else None
    except ValueError:
        return None


@dataclass
class LaminateRequirements:
    min_strength_mpa: float
    min_modulus_gpa: Optional[float] = None
    max_density_g_cm3: Optional[float] = None
    min_tg_C: Optional[float] = None
    form: str = "any"                    # any | UD | fabric
    part_type: str = "monolithic"        # monolithic | sandwich
    equipment: str = "autoclave"         # autoclave | oven
    laminate_mm: Optional[float] = None


@dataclass
class Candidate:
    variant: dict
    master: dict
    cycle_id: Optional[str] = None
    cycle_reason: str = ""
    score: float = 0.0
    parts: dict = field(default_factory=dict)
    rank: int = 0

    @property
    def strength(self) -> float:
        return float(self.variant["tensile_strength_mpa"])

    @property
    def modulus(self) -> float:
        return float(self.variant["tensile_modulus_gpa"])

    @property
    def density(self) -> float:
        return float(self.variant["laminate_density_g_cm3"])

    @property
    def tg(self) -> Optional[float]:
        return _num(self.variant["tg_dry_C"])

    @property
    def tg_text(self) -> str:
        return f"Tg {self.tg:.0f} °C" if self.tg is not None else "Tg not published"

    @property
    def name(self) -> str:
        return f"{self.master['manufacturer']} {self.master['product_system']} — {self.variant['variant']}"


@dataclass
class Rejection:
    name: str
    reasons: List[str]


@dataclass
class SelectionResult:
    requirements: LaminateRequirements
    ranked: List[Candidate]
    rejected: List[Rejection]
    no_data: List[dict]

    @property
    def best(self) -> Optional[Candidate]:
        return self.ranked[0] if self.ranked else None


def cure_map() -> dict:
    return {r["product_system"]: r for r in _rows(CURE_MAP_FILE)}


def recommend_cycle(master: dict, req: LaminateRequirements) -> tuple:
    """(cycle_id or None, reason) from the prepreg's own datasheet."""
    row = cure_map().get(master["product_system"])
    if row is None:
        return None, f"no cure cycle on file for {master['product_system']} — datasheet needed"
    if req.equipment == "oven":
        if row["oven"]:
            return row["oven"], f"vacuum-bag-only oven cycle ({row['source']})"
        return None, "datasheet gives no oven (vacuum-bag-only) cycle"
    if req.part_type == "sandwich":
        if row["sandwich"]:
            return row["sandwich"], f"sandwich cycle ({row['source']})"
        return None, "datasheet gives no honeycomb-sandwich cycle"
    if req.laminate_mm and req.laminate_mm > THICK_LAMINATE_MM and row["thick"]:
        return row["thick"], f"thick-laminate cycle for > {THICK_LAMINATE_MM:g} mm ({row['source']})"
    return row["monolithic"], f"monolithic cycle ({row['source']})"


def _form_ok(form: str, wanted: str) -> bool:
    if wanted == "any":
        return True
    if wanted == "UD":
        return form == "UD"
    return form != "UD"


def select(req: LaminateRequirements) -> SelectionResult:
    if req.min_strength_mpa is None or req.min_strength_mpa < 0:
        raise ValueError("Enter the required 0° tensile strength (MPa).")
    masters = {r["prepreg_id"]: r for r in _rows(MASTER_FILE)}
    variants = _rows(PROPERTY_FILE)
    covered = {v["prepreg_id"] for v in variants}

    passing, rejected = [], []
    for v in variants:
        master = masters.get(v["prepreg_id"])
        if master is None:
            continue
        c = Candidate(v, master)
        reasons = []
        if c.strength < req.min_strength_mpa:
            reasons.append(f"0° strength {c.strength:.0f} MPa < {req.min_strength_mpa:g} required")
        if req.min_modulus_gpa and c.modulus < req.min_modulus_gpa:
            reasons.append(f"0° modulus {c.modulus:.0f} GPa < {req.min_modulus_gpa:g} required")
        if req.max_density_g_cm3 and c.density > req.max_density_g_cm3:
            reasons.append(f"density {c.density:.2f} g/cm³ > {req.max_density_g_cm3:g} allowed")
        if req.min_tg_C:
            if c.tg is None:
                reasons.append("Tg not published")
            elif c.tg < req.min_tg_C:
                reasons.append(f"Tg {c.tg:.0f} °C < {req.min_tg_C:g} required")
        if not _form_ok(v["form"], req.form):
            reasons.append(f"form is {v['form']}, {req.form} wanted")
        c.cycle_id, c.cycle_reason = recommend_cycle(master, req)
        if c.cycle_id is None:
            reasons.append(c.cycle_reason)
        if reasons:
            rejected.append(Rejection(c.name, reasons))
        else:
            passing.append(c)

    _score(passing)
    passing.sort(key=lambda c: (-c.score, -c.strength, c.name))
    for i, c in enumerate(passing, 1):
        c.rank = i

    no_data = [{"prepreg_id": m["prepreg_id"], "product": f"{m['manufacturer']} {m['product_system']}",
                "matrix": m["matrix_family"], "cure_C": m["cure_temperature_C"],
                "source_document": m["source_document"], "source_url": m["source_url"],
                "has_cure_cycle": m["product_system"] in cure_map()}
               for pid, m in masters.items() if pid not in covered]
    return SelectionResult(req, passing, rejected, no_data)


def _score(cands: List[Candidate]):
    if not cands:
        return
    metrics = {
        "specific_strength": [c.strength / c.density for c in cands],
        "specific_modulus": [c.modulus / c.density for c in cands],
        "tg": [c.tg for c in cands],
    }
    for name, values in metrics.items():
        known = [v for v in values if v is not None]
        lo, hi = (min(known), max(known)) if known else (0.0, 0.0)
        for c, v in zip(cands, values):
            # Unpublished value = not demonstrated (0); it does not stretch the scale for the rest.
            n = 0.0 if v is None else (1.0 if hi == lo else (v - lo) / (hi - lo))
            c.parts[name] = WEIGHTS[name] * n
    for c in cands:
        c.score = sum(c.parts.values())


def selection_text(res: SelectionResult) -> str:
    r = res.requirements
    lines = ["=" * 78, "PREPREG SELECTION", "=" * 78,
             f"Required: 0° tensile ≥ {r.min_strength_mpa:g} MPa"
             + (f", modulus ≥ {r.min_modulus_gpa:g} GPa" if r.min_modulus_gpa else "")
             + (f", density ≤ {r.max_density_g_cm3:g} g/cm³" if r.max_density_g_cm3 else "")
             + (f", Tg ≥ {r.min_tg_C:g} °C" if r.min_tg_C else "")
             + f" | form {r.form} | {r.part_type} | {r.equipment}"
             + (f" | {r.laminate_mm:g} mm laminate" if r.laminate_mm else ""), ""]
    if res.best:
        b = res.best
        cycle = cp.get_cycle(b.cycle_id)
        lines += [f"SELECTED: {b.name}",
                  f"  {b.strength:.0f} MPa, {b.modulus:.0f} GPa, {b.density:.2f} g/cm³, {b.tg_text} "
                  f"({b.variant['test_condition']}; {b.variant['normalization']})",
                  f"  Source: {b.variant['source_document']} — {b.variant['source_location']}",
                  f"  Cure cycle: {cycle.cycle_id} — {cycle.product}, {cycle.part_type}, peak "
                  f"{cycle.peak_C:.0f} °C, {cp.pressure_text(cycle)} ({b.cycle_reason})"]
        if b.variant["notes"]:
            lines.append(f"  Note: {b.variant['notes']}")
        lines += ["", "RANKED CANDIDATES (score: specific strength 50 %, specific modulus 30 %, Tg 20 %)"]
        for c in res.ranked:
            lines.append(f"  #{c.rank} {c.name}: {c.strength:.0f} MPa, {c.modulus:.0f} GPa, "
                         f"{c.density:.2f} g/cm³, σ/ρ {c.strength / c.density:.0f} — score {c.score:.2f}")
    else:
        lines.append("No prepreg with published laminate data meets every requirement.")
    if res.rejected:
        lines.append("\nREJECTED")
        lines += [f"  ✗ {x.name}: {'; '.join(x.reasons)}" for x in res.rejected]
    lines.append(f"\nNOT EVALUATED — no laminate data in hand ({len(res.no_data)} systems; datasheets needed):")
    for n in res.no_data:
        lines.append(f"  • {n['product']} ({n['matrix']}, cure {n['cure_C']} °C) — {n['source_document']}")
    return "\n".join(lines)
