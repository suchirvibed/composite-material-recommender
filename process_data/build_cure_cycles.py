"""
Build process_data/cure_cycles.csv and cure_cycle_steps.csv from cited cycles.

Every cycle is typed here in the UNITS OF ITS SOURCE (°F, psi, inHg or °C,
bar) and converted, so each number can be checked against the line it came
from. Rates and hold times keep their stated ranges (low–high). Where a
source does not state a value (often the ramp or cooling rate in
MIL-HDBK-17 summaries) the step says so in `basis` and uses the stated
assumption below — never a silent default.

Run:  py process_data/build_cure_cycles.py
"""

from __future__ import annotations

import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Assumptions used only where the source is silent (flagged per step).
ASSUMED_RAMP = (1.0, 3.0)    # °C/min — the range most cited datasheets here state
ASSUMED_COOL = (2.0, 3.0)    # °C/min
AMBIENT_C = 25.0


def F(x):            # °F → °C
    return round((x - 32) * 5 / 9, 1)


def dF(lo, hi=None):  # °F/min → °C/min
    hi = lo if hi is None else hi
    return round(lo / 1.8, 2), round(hi / 1.8, 2)


def psi(x):
    return round(x * 0.0689476, 2)


def inHg(x):         # inches of mercury vacuum → bar (negative gauge)
    return round(-x * 0.0338639, 2)


CYCLES = []          # metadata rows
STEPS = []           # step rows


def cycle(cid, product, matrix, process, part_type, source, location, notes="",
          vent_C=None, steps=(), post=(), p_range=None):
    """p_range = the documented pressure window (bar g) when the source gives one."""
    peak = max(s["target_C"] for s in steps if s["kind"] == "ramp")
    stated = [s["pressure_bar"] for s in steps if s["pressure_bar"] != ""]
    p_lo, p_hi = p_range if p_range else ((min(stated), max(stated)) if stated else (0.0, 0.0))
    CYCLES.append({"cycle_id": cid, "product": product, "matrix": matrix, "process": process,
                   "part_type": part_type, "peak_C": peak, "pressure_lo_bar": p_lo, "pressure_hi_bar": p_hi,
                   "post_cure_peak_C": max((s["target_C"] for s in post if s["kind"] == "ramp"), default=""),
                   "vent_C": "" if vent_C is None else vent_C,
                   "source": source, "source_location": location, "notes": notes})
    for phase, seq in (("cure", steps), ("postcure", post)):
        for i, s in enumerate(seq, 1):
            STEPS.append({"cycle_id": cid, "phase": phase, "step": i, **s})


def ramp(target_C, rate, pressure=None, vacuum=None, event="", basis="stated"):
    return {"kind": "ramp", "target_C": target_C, "rate_lo": rate[0], "rate_hi": rate[1],
            "min_lo": "", "min_hi": "", "pressure_bar": "" if pressure is None else pressure,
            "vacuum_bar": "" if vacuum is None else vacuum, "event": event, "basis": basis}


def hold(minutes, pressure=None, vacuum=None, event="", basis="stated", at_C=""):
    lo, hi = minutes if isinstance(minutes, tuple) else (minutes, minutes)
    return {"kind": "hold", "target_C": at_C, "rate_lo": "", "rate_hi": "", "min_lo": lo, "min_hi": hi,
            "pressure_bar": "" if pressure is None else pressure,
            "vacuum_bar": "" if vacuum is None else vacuum, "event": event, "basis": basis}


def cool(target_C, rate, pressure=None, vacuum=None, event="", basis="stated"):
    d = ramp(target_C, rate, pressure, vacuum, event, basis)
    d["kind"] = "cool"
    return d


# ----------------------------------------------------------------------
# Hexcel product data sheets (fetched, text checked)
# ----------------------------------------------------------------------
HEX = "Hexcel product data sheet"

cycle("HEX_8552_EU_MONO", "HexPly 8552", "epoxy 180 °C", "autoclave", "monolithic",
      f"{HEX} HexPly 8552 (EU)", "Curing Conditions — monolithic components", vent_C=60,
      steps=[ramp(110, (1, 3), 7.0, -0.2, "full vacuum, then 7 bar; vacuum reduced to 0.2 bar at ~1 bar gauge"),
             hold((55, 65), 7.0, -0.2, "hold 110 ± 5 °C"),
             ramp(180, (1, 3), 7.0, -0.2),
             hold((115, 125), 7.0, -0.2, "hold 180 ± 5 °C"),
             cool(60, (2, 5), 7.0, -0.2, "vent autoclave pressure at ≤ 60 °C")])

cycle("HEX_8552_EU_SAND", "HexPly 8552", "epoxy 180 °C", "autoclave", "sandwich",
      f"{HEX} HexPly 8552 (EU)", "Curing Conditions — honeycomb sandwich components", vent_C=60,
      steps=[ramp(110, (1, 3), 3.2, -0.2, "full vacuum, then 3.2 bar; vacuum reduced to 0.2 bar at ~1 bar gauge"),
             hold((55, 65), 3.2, -0.2, "hold 110 ± 5 °C"),
             ramp(180, (1, 3), 3.2, -0.2),
             hold((115, 125), 3.2, -0.2, "hold 180 ± 5 °C"),
             cool(60, (2, 5), 3.2, -0.2, "vent autoclave pressure at ≤ 60 °C")])

cycle("HEX_8552_US", "HexPly 8552", "epoxy 180 °C", "autoclave", "monolithic",
      f"{HEX} HexPly 8552 (US)", "Cure Cycle — Autoclave, steps 1-7", vent_C=F(150), p_range=(psi(85), psi(100)),
      steps=[ramp(F(225), dF(3, 5), psi(15), -1.0, "full vacuum and 15 psig"),
             hold((30, 60), psi(15), -1.0, "hold 225 °F"),
             ramp(F(350), dF(3, 5), psi(92.5), 0.0,
                  "raise to 85-100 psig; vent vacuum at 30 psig",
                  basis="ramp rate to 350 °F not restated — 3-5 °F/min of step 2 used"),
             hold((110, 130), psi(92.5), 0.0, "hold 350 °F, 120 ± 10 min"),
             cool(F(150), dF(2, 5), psi(92.5), 0.0, "vent pressure at 150 °F")])

cycle("HEX_M21_THIN", "HexPly M21", "epoxy 180 °C (toughened)", "autoclave", "monolithic < 15 mm",
      f"{HEX} HexPly M21 (global)", "Typical autoclave cure, monolithic < 15 mm", vent_C=60,
      notes="Rate is the actual component heat-up rate, not the air set point.",
      steps=[ramp(180, (1, 2), 7.0, -0.2, "full vacuum, then 7 bar; vacuum to -0.2 bar at ~1 bar gauge"),
             hold((115, 125), 7.0, -0.2, "hold 180 ± 5 °C"),
             cool(60, (2, 5), 7.0, -0.2, "vent at ≤ 60 °C")])

cycle("HEX_M21_THICK", "HexPly M21", "epoxy 180 °C (toughened)", "autoclave", "monolithic 15-48 mm",
      f"{HEX} HexPly M21 (global)", "Typical autoclave cure, monolithic 15-48 mm", vent_C=60,
      notes="Slow ramps and a 150 °C dwell control exotherm in thick laminates.",
      steps=[ramp(150, (0.5, 1), 7.0, -0.2, "full vacuum, then 7 bar; vacuum to -0.2 bar at ~1 bar gauge"),
             hold((175, 185), 7.0, -0.2, "hold 150 ± 5 °C"),
             ramp(180, (0.5, 1), 7.0, -0.2),
             hold((115, 125), 7.0, -0.2, "hold 180 ± 5 °C"),
             cool(60, (2, 5), 7.0, -0.2, "vent at ≤ 60 °C")])

cycle("HEX_M21_SAND", "HexPly M21", "epoxy 180 °C (toughened)", "autoclave", "sandwich",
      f"{HEX} HexPly M21 (global)", "Typical autoclave cure, sandwich (honeycomb or foam)", vent_C=60, p_range=(2.0, 3.0),
      notes="No autoclave pressure until the resin has been at 135 °C for 60 min.",
      steps=[ramp(135, (1, 2), 0.0, -0.3, "max -0.3 bar vacuum, no autoclave pressure"),
             hold((55, 65), 0.0, -0.3, "hold 135 ± 5 °C"),
             ramp(180, (1, 2), 2.5, 0.0, "apply 2-3 bar (core density); remove vacuum at ~1 bar gauge"),
             hold((115, 125), 2.5, 0.0, "hold 180 ± 5 °C"),
             cool(60, (2, 5), 2.5, 0.0, "vent at ≤ 60 °C")])

cycle("HEX_913", "HexPly 913", "epoxy 125 °C", "autoclave", "monolithic",
      f"{HEX} HexPly 913 (EU)", "Prepreg Curing Conditions",
      notes="Alternatives: 140 °C/40 min, 150 °C/20 min, 160 °C/10 min. Parts > 3 mm or ramps > 5 °C/min "
            "need a dwell (usually 80-100 °C) to avoid exotherm.",
      steps=[ramp(125, (2, 8), 7.0, None),
             hold(60, 7.0, None, "hold 125 °C"),
             cool(AMBIENT_C, ASSUMED_COOL, 7.0, None, basis="cooling not stated — assumed")])

cycle("HEX_913_150", "HexPly 913", "epoxy 125 °C", "autoclave", "monolithic",
      f"{HEX} HexPly 913 (EU)", "Alternative cure cycles (150 °C / 20 min)",
      steps=[ramp(150, (2, 8), 7.0, None, basis="pressure and rate of the main cycle assumed"),
             hold(20, 7.0, None, "hold 150 °C"),
             cool(AMBIENT_C, ASSUMED_COOL, 7.0, None, basis="cooling not stated — assumed")])

cycle("HEX_M56_OVEN_MONO", "HexPly M56", "epoxy 180 °C (out-of-autoclave)", "oven (vacuum bag only)",
      "monolithic", f"{HEX} HexPly M56 (global)", "Typical oven cure, monolithic part", vent_C=60,
      steps=[ramp(110, (1, 3), 0.0, -0.95, "full vacuum (-0.95 bar)"),
             hold((55, 65), 0.0, -0.95, "hold 110 ± 5 °C"),
             ramp(180, (1, 3), 0.0, -0.5, "reduce vacuum to -0.5 bar"),
             hold((120, 150), 0.0, -0.5, "hold 180 ± 5 °C, 120 +30/-0 min"),
             cool(60, dF(5), 0.0, -0.5, "cool under vacuum; release below 140 °F")])

cycle("HEX_M56_OVEN_SAND", "HexPly M56", "epoxy 180 °C (out-of-autoclave)", "oven (vacuum bag only)",
      "sandwich", f"{HEX} HexPly M56 (global)", "Typical oven cure, sandwich structure", vent_C=60,
      steps=[ramp(110, (1, 3), 0.0, -0.95, "full vacuum (-0.95 bar)"),
             hold((55, 65), 0.0, -0.95, "hold 110 ± 5 °C"),
             ramp(180, (1, 3), 0.0, -0.95),
             hold((120, 150), 0.0, -0.95, "hold 180 ± 5 °C, 120 +30/-0 min"),
             cool(60, dF(5), 0.0, -0.95, "cool under vacuum; release below 140 °F")])

M18 = "HexPly M18/1 datasheet (project HexPly_M18-1_Datasheet_Guide)"
cycle("M18-1_MONO", "HexPly M18/1", "epoxy 180 °C (toughened)", "autoclave", "monolithic",
      M18, "p.3 monolithic cure", p_range=(4.0, 7.0),
      notes="Optional extra 1 h hold at 100 °C not included.",
      steps=[ramp(80, (2, 2), 5.5, -0.8, "4-7 bar, -0.8 bar vacuum"),
             hold(60, 5.5, -0.8, "hold 80 °C — flow and air removal"),
             ramp(180, (2, 2), 5.5, -0.8),
             hold(120, 5.5, -0.8, "hold 180 °C"),
             cool(AMBIENT_C, (2, 2), 5.5, -0.8, basis="'cool at a controlled rate' — 2 °C/min assumed")])

cycle("M18-1_SAND", "HexPly M18/1", "epoxy 180 °C (toughened)", "autoclave", "sandwich",
      M18, "p.3 sandwich cure", notes="2 bar so the honeycomb core is not crushed.",
      steps=[ramp(80, (2, 2), 2.0, -0.8, "2 bar, -0.8 bar vacuum"),
             hold(60, 2.0, -0.8, "hold 80 °C — flow and air removal"),
             ramp(180, (2, 2), 2.0, -0.8),
             hold(120, 2.0, -0.8, "hold 180 °C"),
             cool(AMBIENT_C, (2, 2), 2.0, -0.8, basis="'cool at a controlled rate' — 2 °C/min assumed")])

cycle("M18-1_ALT", "HexPly M18/1", "epoxy 180 °C (toughened)", "oven (vacuum bag only)", "monolithic",
      M18, "p.3 alternative cycle",
      steps=[ramp(120, ASSUMED_RAMP, 0.0, -0.8, "vacuum only", basis="ramp not stated — assumed"),
             hold(120, 0.0, -0.8, "hold 120 °C"),
             ramp(180, ASSUMED_RAMP, 0.0, -0.8, basis="ramp not stated — assumed"),
             hold(120, 0.0, -0.8, "hold 180 °C"),
             cool(AMBIENT_C, ASSUMED_COOL, 0.0, -0.8, basis="cooling not stated — assumed")])

cycle("HEXTOOL_M61", "HexTool M61 (tooling prepreg)", "BMI", "autoclave", "tool",
      "Hexcel Industrial Selector Guide (HexTool table) + HexTool user guide", "HexTool cure",
      notes="Builds a composite TOOL, not a part.",
      steps=[ramp(190, ASSUMED_RAMP, 7.0, None, basis="ramp not stated — assumed"),
             hold(240, 7.0, None, "hold 190 °C"),
             cool(AMBIENT_C, ASSUMED_COOL, 7.0, None, basis="cooling not stated — assumed")],
      post=[ramp(220, ASSUMED_RAMP, basis="free-standing post-cure; ramp assumed"),
            hold(960, event="post-cure 16 h at 220 °C to develop full Tg"),
            cool(AMBIENT_C, ASSUMED_COOL, basis="assumed")])

# ----------------------------------------------------------------------
# Toray 3900 prepreg system data sheet (prepreg DB source URL)
# ----------------------------------------------------------------------
cycle("TORAY_3900", "Toray 3900 (T800S / T830H)", "epoxy 177 °C (highly toughened)", "autoclave",
      "monolithic", "Toray 3900 Prepreg System data sheet", "Cure Cycle - Autoclave, steps 1-6",
      vent_C=F(140), p_range=(psi(95), psi(95)),
      notes="Vacuum 28 inHg minimum at sea level. No sandwich cycle is given in the data sheet.",
      steps=[ramp(F(350), dF(1, 5), psi(95), 0.0,
                  "full vacuum, 95 psi; vent the bag when pressure reaches 20 psi; 3.0 ± 2.0 °F/min"),
             hold((120, 180), psi(95), 0.0, "hold 350 ± 10 °F, 120-180 min"),
             cool(F(140), (1.0, 2.78), psi(95), 0.0,
                  "cool to 140 °F or lower before releasing pressure",
                  basis="maximum 5 °F/min stated — lower bound 1 °C/min assumed")])

# ----------------------------------------------------------------------
# NCAMP process specification
# ----------------------------------------------------------------------
cycle("NCAMP_5320-1_C", "Solvay CYCOM 5320-1", "epoxy (out-of-autoclave)", "oven (vacuum bag only)",
      "monolithic", "NCAMP NPS 85321 Rev D (2025), 5320-1 process specification",
      "4.3 Baseline Cure Cycle (C)", vent_C=F(150),
      notes="Pre-cure vacuum hold 4 h for panels ≤ 4 ft², 16 h above. Holds start when the "
            "LAGGING thermocouple reaches temperature.",
      steps=[hold(240, 0.0, inHg(28), "pre-cure vacuum hold ≥ 28 inHg (4 h, ≤ 4 ft² panel)", at_C=AMBIENT_C),
             ramp(F(250), dF(1, 5), 0.0, inHg(28), "full vacuum"),
             hold((115, 125), 0.0, inHg(28), "hold 250 °F, 120 ± 5 min"),
             ramp(F(350), dF(1, 5), 0.0, inHg(28)),
             hold((115, 125), 0.0, inHg(28), "hold 350 °F, 120 ± 5 min (integrated post-cure)"),
             cool(F(150), dF(1, 5), 0.0, inHg(28), "cool below 150 °F")])

# ----------------------------------------------------------------------
# MIL-HDBK-17-2F Vol. 2 — processing lines of qualified material systems
# (temperature, time, pressure stated; ramp and cooling rates mostly not)
# ----------------------------------------------------------------------
MIL = "MIL-HDBK-17-2F Vol. 2 (2002)"
NR = "ramp not stated — assumed"
NC = "cooling not stated — assumed"


def mil(cid, product, matrix, process, table, steps, post=(), notes="", p_range=None):
    cycle(cid, product, matrix, process, "monolithic", MIL, table, notes=notes, steps=steps, post=post,
          p_range=p_range)


mil("MIL_3501-6", "Hercules AS4/3501-6", "epoxy 180 °C", "autoclave", "4.2.12 processing",
    [ramp(F(240), ASSUMED_RAMP, psi(85), None, basis=NR), hold(60, psi(85), None, "hold 240 ± 10 °F"),
     ramp(F(350), ASSUMED_RAMP, psi(100), None, "raise to 100 ± 10 psig", basis=NR),
     hold((110, 130), psi(100), None, "hold 350 ± 10 °F, 120 ± 10 min"),
     cool(AMBIENT_C, ASSUMED_COOL, psi(100), None, basis=NC)], p_range=(psi(85), psi(110)))
mil("MIL_3502", "Hercules AS4/3502", "epoxy 180 °C", "autoclave", "4.2.8 processing",
    [ramp(F(280), ASSUMED_RAMP, psi(85), None, basis=NR), hold(90, psi(85), None, "hold 280 ± 5 °F"),
     ramp(F(350), ASSUMED_RAMP, psi(85), None, basis=NR), hold(120, psi(85), None, "hold 350 °F"),
     cool(AMBIENT_C, ASSUMED_COOL, psi(85), None, basis=NC)])
mil("MIL_976", "Fiberite T300/976", "epoxy 180 °C", "autoclave", "4.2.17 processing",
    [ramp(F(250), ASSUMED_RAMP, psi(100), None, basis=NR), hold(45, psi(100), None, "hold 250 °F"),
     ramp(F(350), ASSUMED_RAMP, psi(100), None, basis=NR), hold(120, psi(100), None, "hold 350 °F"),
     cool(AMBIENT_C, ASSUMED_COOL, psi(100), None, basis=NC)])
mil("MIL_3900-2", "Toray T800H/3900-2", "epoxy 180 °C (toughened)", "autoclave", "4.2.34 processing",
    [ramp(F(350), dF(3), psi(85), None, "3 °F/min ramp rate"), hold(120, psi(85), None, "hold 350 °F, 2 h"),
     cool(AMBIENT_C, ASSUMED_COOL, psi(85), None, basis=NC)],
    notes="The material system of the Albert & Fernlund spring-in study.")
mil("MIL_E7K8", "U.S. Polymeric AS4/E7K8", "epoxy 150 °C", "autoclave", "4.2.3 processing",
    [ramp(F(305), ASSUMED_RAMP, psi(55), None, basis=NR), hold((120, 130), psi(55), None, "hold 300-310 °F"),
     cool(AMBIENT_C, ASSUMED_COOL, psi(55), None, basis=NC)])
mil("MIL_938", "ICI Fiberite AS4/938", "epoxy 180 °C", "autoclave", "4.2.5 processing",
    [ramp(F(350), ASSUMED_RAMP, psi(100), None, basis=NR), hold((120, 135), psi(100), None, "hold 350 ± 10 °F"),
     cool(AMBIENT_C, ASSUMED_COOL, psi(100), None, basis=NC)], p_range=(psi(85), psi(115)))
mil("MIL_997", "ICI Fiberite AS4/997", "epoxy 180 °C (toughened)", "autoclave", "4.2.28 processing",
    [ramp(F(350), ASSUMED_RAMP, psi(85), None, basis=NR), hold(120, psi(85), None, "hold 350 °F, 2 h"),
     cool(AMBIENT_C, ASSUMED_COOL, psi(85), None, basis=NC)])
mil("MIL_954-3", "Fiberite M55J/954-3", "cyanate ester", "autoclave", "4.10.1 processing",
    [ramp(F(350), ASSUMED_RAMP, psi(100), None, basis=NR), hold(120, psi(100), None, "hold 350 °F, 2 h"),
     cool(AMBIENT_C, ASSUMED_COOL, psi(100), None, basis=NC)])
mil("MIL_F650", "Hexcel T-300/F650", "BMI", "autoclave", "4.4.1 processing",
    [ramp(F(375), ASSUMED_RAMP, psi(85), None, basis=NR), hold(240, psi(85), None, "hold 375 °F, 4 h"),
     cool(AMBIENT_C, ASSUMED_COOL, psi(85), None, basis=NC)],
    post=[ramp(F(475), ASSUMED_RAMP, basis="free-standing oven; ramp assumed"),
          hold(240, event="post-cure 475 °F, 4 h, free-standing"), cool(AMBIENT_C, ASSUMED_COOL, basis=NC)])
mil("MIL_5250-3", "Cytec AS4/5250-3", "BMI", "autoclave", "4.4.4 processing",
    [ramp(F(250), ASSUMED_RAMP, psi(85), None, basis=NR), hold(60, psi(85), None, "hold 250 °F"),
     ramp(F(350), ASSUMED_RAMP, psi(85), None, basis=NR), hold(360, psi(85), None, "hold 350 °F, 6 h"),
     cool(AMBIENT_C, ASSUMED_COOL, psi(85), None, basis=NC)],
    post=[ramp(F(475), ASSUMED_RAMP, basis="ramp assumed"),
          hold(360, event="post-cure 475 °F, 6 h"), cool(AMBIENT_C, ASSUMED_COOL, basis=NC)])
mil("MIL_APC-2", "ICI IM6/APC-2", "PEEK (thermoplastic)", "autoclave", "4.9.1 processing",
    [ramp(F(720), ASSUMED_RAMP, psi(60), None, basis=NR), hold((30, 45), psi(60), None, "hold 720 °F (melt)"),
     cool(AMBIENT_C, ASSUMED_COOL, psi(60), None, basis="cooling not stated — assumed (crystallinity depends on it)")],
    notes="Melt processing, not a chemical cure; only metal or ceramic tools survive 382 °C.")
mil("MIL_F670", "Celion/F670", "polyimide", "autoclave", "4.5.1 processing",
    [ramp(F(440), ASSUMED_RAMP, None, None, basis=NR), hold(120, None, None, "hold 440 °F"),
     ramp(F(600), ASSUMED_RAMP, psi(200), None, basis=NR), hold(180, psi(200), None, "hold 600 °F, 3 h, 200 psig"),
     cool(AMBIENT_C, ASSUMED_COOL, psi(200), None, basis=NC)],
    notes="Post-cure is called for but its schedule is not given.")
mil("MIL_EA9396_VB", "T300/EA 9396", "epoxy 93 °C", "oven (vacuum bag only)", "4.2.27 processing",
    [ramp(F(197.5), ASSUMED_RAMP, 0.0, inHg(25), "25 inHg vacuum", basis=NR),
     hold(45, 0.0, inHg(25), "hold 195-200 °F"),
     cool(AMBIENT_C, ASSUMED_COOL, 0.0, inHg(25), basis=NC)])

# ----------------------------------------------------------------------
# Others
# ----------------------------------------------------------------------
cycle("EC_OOA_80C", "Easy Composites Easy-Preg / Vari-Preg", "epoxy 80-140 °C", "oven (vacuum bag only)",
      "monolithic", "Project folder: EC-TDS Beginners' Guide to Out-of-Autoclave Prepreg",
      "13. Loading into the Oven for Curing",
      notes="Oven pre-heated to 80 °C: the part starts at the set point, no programmed ramp.",
      steps=[ramp(80, (10, 10), 0.0, -0.95, "pre-heated oven, full vacuum",
                  basis="no ramp — pre-heated oven (fast entry modelled as 10 °C/min)"),
             hold(600, 0.0, -0.95, "hold 80 °C, 10 h"),
             cool(AMBIENT_C, ASSUMED_COOL, 0.0, -0.95, basis=NC)])

cycle("ANSYS_AL_DEMO", "Project ANSYS thermal model (aluminium 6061-T6 mould)", "—", "autoclave", "any",
      "Project Autoclave_Thermal_Cycle_Parameter_Calculations.pdf", "Input assumptions",
      notes="Programmed autoclave-air temperature for the transient thermal model, not a prepreg cure.",
      steps=[ramp(180, (2.8, 2.8), None, None), hold(180, None, None, "hold 180 °C, 3 h"),
             cool(AMBIENT_C, (2.8, 2.8), None, None)])


def main():
    with open(HERE / "cure_cycles.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(CYCLES[0]))
        w.writeheader()
        w.writerows(CYCLES)
    with open(HERE / "cure_cycle_steps.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(STEPS[0]))
        w.writeheader()
        w.writerows(STEPS)
    print(f"Wrote {len(CYCLES)} cycles, {len(STEPS)} steps.")


if __name__ == "__main__":
    main()
