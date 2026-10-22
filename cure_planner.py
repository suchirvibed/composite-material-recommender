"""
Autoclave / oven cure-cycle planner.

Cycles come from process_data/cure_cycles.csv + cure_cycle_steps.csv, built by
process_data/build_cure_cycles.py from cited datasheets (Hexcel 8552, M21,
913, M56, M18/1, HexTool M61), the NCAMP 5320-1 process specification,
MIL-HDBK-17-2F processing lines and project documents — 30 cycles.

Each step keeps its documented RANGE (ramp °C/min low–high, hold min low–high)
and its own pressure and vacuum, so the planner can show:
  - the time-temperature-pressure-vacuum schedule (nominal = mid-range),
  - the cycle-time band: fastest (max rates, min holds) to slowest,
  - a separate free-standing post-cure where the source calls for one,
  - an ANSYS Transient Thermal convection table (CSV),
  - checks: equipment (oven cannot apply pressure), sandwich core on a
    monolithic cycle, laminate thickness vs a thin-part cycle, tool service
    limit vs the cure peak, pressure outside the documented range, and
    every value the source did not state (flagged as an assumption),
  - the lagging-thermocouple hold extension: Hexcel — cure time starts when the
    lagging thermocouple reaches the cure temperature; with a lumped tool of
    time constant τ, the tool needs ≈ τ·ln(lag / 5 °C) to come within 5 °C.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import List, Optional

BASE_DIR = Path(__file__).resolve().parent
CYCLE_FILE = BASE_DIR / "process_data" / "cure_cycles.csv"
STEP_FILE = BASE_DIR / "process_data" / "cure_cycle_steps.csv"
THERMOCOUPLE_TOLERANCE_C = 5.0     # Hexcel Prepreg Technology: cure temperature ±5 °C
MODES = ("fast", "nominal", "slow")


def _num(text) -> Optional[float]:
    text = "" if text is None else str(text).strip()
    return float(text) if text else None


@dataclass
class Step:
    kind: str                          # ramp | hold | cool
    rate_lo: float = 0.0               # °C/min (ramp/cool)
    rate_hi: float = 0.0
    target_C: Optional[float] = None
    min_lo: float = 0.0                # minutes (hold)
    min_hi: float = 0.0
    pressure_bar: Optional[float] = None
    vacuum_bar: Optional[float] = None
    event: str = ""
    basis: str = "stated"

    @property
    def assumed(self) -> bool:
        return self.basis != "stated"

    def rate(self, mode: str = "nominal") -> float:
        return {"fast": self.rate_hi, "slow": self.rate_lo}.get(mode, (self.rate_lo + self.rate_hi) / 2)

    def minutes(self, mode: str = "nominal") -> float:
        return {"fast": self.min_lo, "slow": self.min_hi}.get(mode, (self.min_lo + self.min_hi) / 2)

    # Backward-compatible names
    @property
    def rate_C_min(self) -> float:
        return self.rate()


@dataclass
class CureCycle:
    cycle_id: str
    product: str
    matrix: str
    process: str
    part_type: str
    steps: List[Step]
    post_steps: List[Step] = field(default_factory=list)
    vent_C: Optional[float] = None
    source: str = ""
    location: str = ""
    notes: str = ""
    p_range: tuple = (0.0, 0.0)       # documented cure-pressure window, bar g

    @property
    def peak_C(self) -> float:
        return max(s.target_C for s in self.steps if s.kind == "ramp")

    @property
    def post_peak_C(self) -> Optional[float]:
        peaks = [s.target_C for s in self.post_steps if s.kind == "ramp"]
        return max(peaks) if peaks else None

    @property
    def pressures(self) -> List[float]:
        return [s.pressure_bar for s in self.steps if s.pressure_bar is not None]

    @property
    def pressure_max(self) -> float:
        """Top of the documented cure-pressure window."""
        return max(self.p_range[1], max(self.pressures, default=0.0))

    @property
    def pressure_min(self) -> float:
        """Bottom of the documented cure-pressure window (staging steps excluded)."""
        return self.p_range[0] if self.p_range[1] > 0 else min(self.pressures, default=0.0)

    @property
    def vacuum_bar(self) -> Optional[float]:
        v = [s.vacuum_bar for s in self.steps if s.vacuum_bar is not None]
        return min(v) if v else None

    @property
    def needs_pressure(self) -> bool:
        return self.pressure_max > 0.05

    @property
    def assumptions(self) -> List[str]:
        return sorted({s.basis for s in self.steps + self.post_steps if s.assumed})

    @property
    def label(self) -> str:
        return f"{self.product} — {self.part_type} ({self.process}, {self.peak_C:.0f} °C)"


def load_cycles() -> List[CureCycle]:
    with open(STEP_FILE, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    steps_by = {}
    for r in rows:
        st = Step(kind=r["kind"], rate_lo=_num(r["rate_lo"]) or 0.0, rate_hi=_num(r["rate_hi"]) or 0.0,
                  target_C=_num(r["target_C"]), min_lo=_num(r["min_lo"]) or 0.0,
                  min_hi=_num(r["min_hi"]) or 0.0, pressure_bar=_num(r["pressure_bar"]),
                  vacuum_bar=_num(r["vacuum_bar"]), event=r["event"], basis=r["basis"])
        steps_by.setdefault((r["cycle_id"], r["phase"]), []).append(st)
    cycles = []
    with open(CYCLE_FILE, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            cid = r["cycle_id"]
            cycles.append(CureCycle(
                cid, r["product"], r["matrix"], r["process"], r["part_type"],
                steps_by.get((cid, "cure"), []), steps_by.get((cid, "postcure"), []),
                _num(r["vent_C"]), r["source"], r["source_location"], r["notes"],
                (_num(r["pressure_lo_bar"]) or 0.0, _num(r["pressure_hi_bar"]) or 0.0)))
    return cycles


def get_cycle(cycle_id: str) -> CureCycle:
    for c in load_cycles():
        if c.cycle_id == cycle_id:
            return c
    raise KeyError(f"No cure cycle '{cycle_id}'")


def with_overrides(cycle: CureCycle, ramp_C_min: Optional[float] = None,
                   final_hold_min: Optional[float] = None) -> CureCycle:
    """A copy with every heating ramp at one rate and/or a new final cure hold (DOE runs)."""
    steps = list(cycle.steps)
    if ramp_C_min is not None:
        steps = [replace(s, rate_lo=ramp_C_min, rate_hi=ramp_C_min) if s.kind == "ramp" else s
                 for s in steps]
    if final_hold_min is not None:
        last = max(i for i, s in enumerate(steps) if s.kind == "hold")
        steps[last] = replace(steps[last], min_lo=final_hold_min, min_hi=final_hold_min)
    return replace(cycle, steps=steps)


def schedule(cycle: CureCycle, start_C: float = 25.0, hold_extension_min: float = 0.0,
             mode: str = "nominal", phase: str = "cure") -> List[dict]:
    """
    Breakpoints of the programmed air temperature with the pressure and vacuum
    in force: t_s, T_C, P_bar, V_bar, stage. hold_extension_min is added to the
    final (cure) hold of the cure phase.
    """
    seq = cycle.steps if phase == "cure" else cycle.post_steps
    if not seq:
        return []
    holds = [i for i, s in enumerate(seq) if s.kind == "hold"]
    last_hold = holds[-1] if holds else -1
    first = seq[0]
    points = [{"t_s": 0.0, "T_C": start_C, "P_bar": first.pressure_bar or 0.0,
               "V_bar": first.vacuum_bar or 0.0, "stage": "Start", "event": first.event}]
    t, temp = 0.0, start_C
    for i, s in enumerate(seq):
        P, V = s.pressure_bar or 0.0, s.vacuum_bar or 0.0
        if s.kind in ("ramp", "cool"):
            rate = s.rate(mode)
            t += abs(s.target_C - temp) / rate * 60.0 if rate > 0 else 0.0
            temp = s.target_C
            label = "End of heating ramp" if s.kind == "ramp" else "End of cooling"
            points.append({"t_s": t, "T_C": temp, "P_bar": P, "V_bar": V,
                           "stage": f"{label} ({temp:.0f} °C)", "event": s.event})
        else:
            minutes = s.minutes(mode) + (hold_extension_min if (phase == "cure" and i == last_hold) else 0.0)
            t += minutes * 60.0
            points.append({"t_s": t, "T_C": temp, "P_bar": P, "V_bar": V,
                           "stage": f"End of {minutes:.0f} min hold at {temp:.0f} °C", "event": s.event})
    return points


def total_minutes(points: List[dict]) -> float:
    return points[-1]["t_s"] / 60.0 if points else 0.0


def duration_band(cycle: CureCycle, start_C: float = 25.0, extension: float = 0.0) -> dict:
    """Cycle minutes at the fast end, nominal and slow end of the documented ranges."""
    return {m: total_minutes(schedule(cycle, start_C, extension, m)) for m in MODES}


def hold_extension_for_lag(tau_min: Optional[float], ramp_C_min: float,
                           tol_C: float = THERMOCOUPLE_TOLERANCE_C) -> Optional[float]:
    """Minutes for a lumped tool lagging by ramp·τ to come within tol of the set point."""
    if tau_min is None:
        return None
    lag = ramp_C_min * tau_min
    if lag <= tol_C:
        return 0.0
    return tau_min * math.log(lag / tol_C)


def write_ansys_table(points: List[dict], path: Path) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Elapsed time (s)", "Elapsed time (min)", "Ambient temperature (C)",
                    "Autoclave pressure (bar g)", "Vacuum (bar g)", "Meaning"])
        for p in points:
            w.writerow([f"{p['t_s']:.2f}", f"{p['t_s'] / 60:.3f}", f"{p['T_C']:.0f}",
                        f"{p['P_bar']:g}", f"{p['V_bar']:g}", p["stage"]])
    return path


@dataclass
class CurePlan:
    cycle: CureCycle
    points: List[dict]
    post_points: List[dict]
    hold_extension_min: float
    band: dict
    warnings: List[str]
    pressure_bar: float


def plan(cycle: CureCycle, start_C: float = 25.0, pressure_bar: Optional[float] = None,
         sandwich: bool = False, tool_max_service_C: Optional[float] = None,
         tool_tau_min: Optional[float] = None, tool_name: str = "",
         laminate_mm: Optional[float] = None, equipment: str = "autoclave") -> CurePlan:
    warnings = []
    pressure = cycle.pressure_max if pressure_bar is None else pressure_bar

    if cycle.needs_pressure and (pressure < cycle.pressure_min - 1e-6 or pressure > cycle.pressure_max + 1e-6):
        warnings.append(f"Pressure {pressure:g} bar is outside the documented "
                        f"{cycle.pressure_min:g}-{cycle.pressure_max:g} bar for this cycle.")
    if equipment == "oven" and cycle.needs_pressure:
        warnings.append(f"This cycle needs {cycle.pressure_max:g} bar autoclave pressure — an oven "
                        f"(vacuum only) cannot run it. Choose a vacuum-bag-only cycle (e.g. M56, 5320-1).")
    if sandwich and "monolithic" in cycle.part_type:
        warnings.append("Sandwich part on a monolithic cycle: honeycomb cores need the sandwich version "
                        "(lower pressure, e.g. M18/1 2 bar, 8552 3.2 bar, M21 2-3 bar applied late) "
                        "to avoid core crush.")
    if laminate_mm is not None:
        if laminate_mm > 15 and "< 15 mm" in cycle.part_type:
            warnings.append(f"{laminate_mm:g} mm laminate exceeds this cycle's < 15 mm limit — use the "
                            f"thick-part cycle (slow ramps, intermediate dwell) to control exotherm.")
        if laminate_mm > 3 and cycle.cycle_id.startswith("HEX_913"):
            warnings.append("HexPly 913 parts over 3 mm need a heat-up dwell (usually 80-100 °C) to "
                            "avoid exotherm; dwell length depends on tool mass.")
    if tool_max_service_C is not None and tool_max_service_C < cycle.peak_C + 20:
        warnings.append(f"Tool {tool_name} max service {tool_max_service_C:.0f} °C is below peak cure "
                        f"{cycle.peak_C:.0f} °C + 20 °C margin.")
    if cycle.post_steps:
        warnings.append(f"Free-standing post-cure to {cycle.post_peak_C:.0f} °C follows: the part leaves "
                        f"the mould, so the mould does not need that rating, but the post-cure oven does.")

    first_ramp = next((s for s in cycle.steps if s.kind == "ramp"), None)
    ramp = first_ramp.rate() if first_ramp else 0.0
    extension = hold_extension_for_lag(tool_tau_min, ramp) or 0.0
    if tool_tau_min is None and tool_name:
        warnings.append(f"Tool {tool_name}: thermal lag unknown — place a lagging thermocouple on the "
                        f"tool and start the hold timer only when it reaches cure temperature.")
    elif extension > 0:
        warnings.append(f"Tool {tool_name} lags ≈{ramp * tool_tau_min:.0f} °C during the ramp: final hold "
                        f"extended by {extension:.0f} min so the lagging thermocouple completes the cure.")
    for basis in cycle.assumptions:
        warnings.append(f"Assumption: {basis}.")

    return CurePlan(cycle, schedule(cycle, start_C, extension),
                    schedule(cycle, start_C, phase="postcure"), extension,
                    duration_band(cycle, start_C, extension), warnings, pressure)


def pressure_text(c: CureCycle) -> str:
    if not c.needs_pressure:
        return "none (vacuum only)"
    if abs(c.pressure_max - c.pressure_min) < 1e-6:
        return f"{c.pressure_max:g} bar g"
    return f"{c.pressure_min:g}-{c.pressure_max:g} bar g"


def _fmt_minutes(m: float) -> str:
    return f"{m:.0f} min ({int(m // 60)} h {m % 60:.0f} min)"


def plan_text(p: CurePlan) -> str:
    c = p.cycle
    vac = "none" if c.vacuum_bar is None else f"{c.vacuum_bar:g} bar"
    lines = ["=" * 78, f"CURE PLAN — {c.product} · {c.part_type}", "=" * 78,
             f"Matrix: {c.matrix} | Process: {c.process} | Peak {c.peak_C:.0f} °C",
             f"Source: {c.source} — {c.location}",
             f"Pressure: {pressure_text(c)} | Vacuum: {vac}"
             + (f" | vent at ≤ {c.vent_C:.0f} °C" if c.vent_C else "")
             + (f" | final hold +{p.hold_extension_min:.0f} min for tool lag" if p.hold_extension_min else ""),
             "", f"  {'Time (min)':>10} {'Air T (°C)':>10} {'P (bar)':>8} {'Vac (bar)':>9}  Stage / action"]
    for pt in p.points:
        action = f" — {pt['event']}" if pt["event"] else ""
        lines.append(f"  {pt['t_s'] / 60:>10.1f} {pt['T_C']:>10.0f} {pt['P_bar']:>8g} {pt['V_bar']:>9g}  "
                     f"{pt['stage']}{action}")
    b = p.band
    lines.append(f"\nCycle time: {_fmt_minutes(b['nominal'])} nominal — "
                 f"{b['fast']:.0f} min at the fast end of the documented ranges, "
                 f"{b['slow']:.0f} min at the slow end.")
    if p.post_points:
        lines.append(f"Post-cure (free-standing): {_fmt_minutes(total_minutes(p.post_points))} "
                     f"to {c.post_peak_C:.0f} °C.")
    lines.append("Keep pressure and vacuum on through cooling until the vent temperature (Hexcel).")
    if c.notes:
        lines.append(f"Note: {c.notes}")
    if p.warnings:
        lines.append("\nCHECKS")
        lines += [f"  • {w}" for w in p.warnings]
    return "\n".join(lines)
