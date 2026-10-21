"""
Autoclave cure-cycle planner.

Turns a documented cure cycle (process_data/cure_cycles.csv) into:
  - a time-temperature schedule and total cycle duration (same method as the
    project's "ANSYS Autoclave Thermal Cycle - Parameter Calculations"),
  - an ANSYS Transient Thermal convection table (CSV) for the autoclave air,
  - checks against the selected tool and part:
      * tool maximum service temperature,
      * sandwich core pressure limit,
      * lagging-thermocouple hold extension — Hexcel: "cure time starts when the
        lagging thermocouple reaches the minimum cure temperature"; with a
        lumped tool of time constant τ the tool needs ≈ τ·ln(lag/tol) to get
        within tol of the set point after the ramp ends.

Only cycles printed in project documents are included; rates that the source
does not state are marked as assumptions in the CSV notes.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

BASE_DIR = Path(__file__).resolve().parent
CYCLE_FILE = BASE_DIR / "process_data" / "cure_cycles.csv"
THERMOCOUPLE_TOLERANCE_C = 5.0     # Hexcel Prepreg Technology: operate at cure temperature ±5 °C


@dataclass
class Step:
    kind: str                  # ramp | hold | cool
    rate_C_min: float = 0.0
    target_C: float = 0.0
    minutes: float = 0.0


@dataclass
class CureCycle:
    cycle_id: str
    product: str
    part_type: str
    steps: List[Step]
    pressure_min: float
    pressure_max: float
    vacuum_bar: float
    source: str
    notes: str

    @property
    def peak_C(self) -> float:
        return max(s.target_C for s in self.steps if s.kind == "ramp")


def parse_steps(text: str) -> List[Step]:
    steps = []
    for token in text.split(";"):
        parts = token.strip().split(":")
        if parts[0] == "hold":
            steps.append(Step("hold", minutes=float(parts[1])))
        elif parts[0] in ("ramp", "cool"):
            steps.append(Step(parts[0], rate_C_min=float(parts[1]), target_C=float(parts[2])))
        else:
            raise ValueError(f"Unknown cure step '{token}'")
    return steps


def load_cycles(path: Path = CYCLE_FILE) -> List[CureCycle]:
    with open(path, encoding="utf-8") as fh:
        return [CureCycle(r["cycle_id"], r["product"], r["part_type"], parse_steps(r["steps"]),
                          float(r["pressure_bar_min"]), float(r["pressure_bar_max"]),
                          float(r["vacuum_bar"]), r["source"], r["notes"])
                for r in csv.DictReader(fh)]


def get_cycle(cycle_id: str) -> CureCycle:
    for c in load_cycles():
        if c.cycle_id == cycle_id:
            return c
    raise KeyError(f"No cure cycle '{cycle_id}'")


def schedule(cycle: CureCycle, start_C: float = 25.0,
             hold_extension_min: float = 0.0) -> List[dict]:
    """
    Breakpoints (time s, temperature °C, stage) of the programmed air temperature.
    hold_extension_min is added to the final (peak) hold.
    """
    points = [{"t_s": 0.0, "T_C": start_C, "stage": "Start"}]
    t, temp = 0.0, start_C
    last_hold = max(i for i, s in enumerate(cycle.steps) if s.kind == "hold")
    for i, s in enumerate(cycle.steps):
        if s.kind in ("ramp", "cool"):
            t += abs(s.target_C - temp) / s.rate_C_min * 60.0
            temp = s.target_C
            label = "End of heating ramp" if s.kind == "ramp" else "End of cooling"
            points.append({"t_s": t, "T_C": temp, "stage": f"{label} ({temp:.0f} °C)"})
        else:
            minutes = s.minutes + (hold_extension_min if i == last_hold else 0.0)
            t += minutes * 60.0
            points.append({"t_s": t, "T_C": temp, "stage": f"End of {minutes:.0f} min hold"})
    return points


def total_minutes(points: List[dict]) -> float:
    return points[-1]["t_s"] / 60.0


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
        w.writerow(["Elapsed time (s)", "Elapsed time (min)", "Ambient temperature (C)", "Meaning"])
        for p in points:
            w.writerow([f"{p['t_s']:.2f}", f"{p['t_s'] / 60:.3f}", f"{p['T_C']:.0f}", p["stage"]])
    return path


@dataclass
class CurePlan:
    cycle: CureCycle
    points: List[dict]
    hold_extension_min: float
    warnings: List[str]
    pressure_bar: float


def plan(cycle: CureCycle, start_C: float = 25.0, pressure_bar: Optional[float] = None,
         sandwich: bool = False, tool_max_service_C: Optional[float] = None,
         tool_tau_min: Optional[float] = None, tool_name: str = "") -> CurePlan:
    warnings = []
    pressure = pressure_bar if pressure_bar is not None else cycle.pressure_max
    if not (cycle.pressure_min <= pressure <= cycle.pressure_max):
        warnings.append(f"Pressure {pressure} bar is outside the documented "
                        f"{cycle.pressure_min}-{cycle.pressure_max} bar for this cycle.")
    if sandwich and cycle.part_type == "monolithic":
        warnings.append("Sandwich part on a monolithic cycle: honeycomb cores need the sandwich "
                        "cycle (M18/1: 2 bar) to avoid core crush.")
    if tool_max_service_C is not None and tool_max_service_C < cycle.peak_C + 20:
        warnings.append(f"Tool {tool_name} max service {tool_max_service_C:.0f} °C is below "
                        f"peak cure {cycle.peak_C:.0f} °C + 20 °C margin.")

    first_ramp = next(s for s in cycle.steps if s.kind == "ramp")
    extension = hold_extension_for_lag(tool_tau_min, first_ramp.rate_C_min) or 0.0
    if tool_tau_min is None and tool_name:
        warnings.append(f"Tool {tool_name}: thermal lag unknown — place a lagging thermocouple on "
                        f"the tool and start the hold timer only when it reaches cure temperature.")
    elif extension > 0:
        warnings.append(f"Tool {tool_name} lags ≈{first_ramp.rate_C_min * tool_tau_min:.0f} °C during "
                        f"the ramp: final hold extended by {extension:.0f} min so the lagging "
                        f"thermocouple completes the full cure time.")
    if "assum" in cycle.notes.lower():
        warnings.append(f"Source note: {cycle.notes}")

    return CurePlan(cycle, schedule(cycle, start_C, extension), extension, warnings, pressure)


def plan_text(p: CurePlan) -> str:
    c = p.cycle
    lines = ["=" * 78, f"CURE PLAN — {c.product} ({c.part_type})", "=" * 78,
             f"Source: {c.source}",
             f"Pressure: {p.pressure_bar:g} bar | Vacuum: {c.vacuum_bar:g} bar"
             + (f" | Hold extended {p.hold_extension_min:.0f} min for tool lag" if p.hold_extension_min else ""),
             "", f"  {'Time (s)':>11} {'Time (min)':>11} {'Air T (°C)':>11}  Stage"]
    for pt in p.points:
        lines.append(f"  {pt['t_s']:>11,.2f} {pt['t_s'] / 60:>11.3f} {pt['T_C']:>11.0f}  {pt['stage']}")
    minutes = total_minutes(p.points)
    lines.append(f"\nTotal cycle: {minutes:.1f} min ({int(minutes // 60)} h {minutes % 60:.0f} min)")
    lines.append("Keep pressure and vacuum on through cooling (Hexcel Prepreg Technology).")
    if p.warnings:
        lines.append("\nCHECKS")
        lines += [f"  • {w}" for w in p.warnings]
    return "\n".join(lines)
