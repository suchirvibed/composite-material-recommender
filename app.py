"""
Autoclave Prepreg Composite Decision Tool — main menu.

One program for the whole project:
  1  Fiber & prepreg recommender      (updated_database_recommender_v4.py)
  2  Mold (tool) material selector    (mold_selector.py — Matrix Engine Report)
  3  Cure-cycle planner               (cure_planner.py)
  4  BOM & cost estimator             (cost_estimator.py)
  5  Full project report              (2 + 3 + 4 for one part, saved to reports/)
  6  Validation cases                 (validation_cases.py — D6)
  7  Data sources & limitations
  8  Prepreg selector                 (prepreg_selector.py — requirements → prepreg + datasheet cure cycle)

Every prompt shows a default in [brackets]; press Enter to accept it.
Start with:  py app.py   (or double-click run.bat)
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import cost_estimator as ce
import cure_planner as cp
import mold_selector as ms
import prepreg_selector as ps
import validation_cases as vc

BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "reports"


# ------------------------------------------------------------------
# Input helpers (defaults on Enter, re-ask on bad input)
# ------------------------------------------------------------------

def ask(prompt: str, default=None, cast=str, choices=None, minimum=None):
    shown = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"{prompt}{shown}: ").strip()
        if raw == "" and default is not None:
            return default
        if raw == "" and default is None and cast is not str:
            print("  A value is required.")
            continue
        try:
            value = cast(raw)
        except ValueError:
            print(f"  Enter a valid {cast.__name__}.")
            continue
        if isinstance(value, float) and value != value:     # NaN
            print("  Enter a real number.")
            continue
        if minimum is not None and value < minimum:
            print(f"  Must be ≥ {minimum}.")
            continue
        if choices and value not in choices:
            print(f"  Choose one of: {', '.join(map(str, choices))}.")
            continue
        return value


def ask_optional_float(prompt: str):
    while True:
        raw = input(f"{prompt} [none]: ").strip()
        if raw == "":
            return None
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
        print("  Enter a positive number, or press Enter for none.")


def yes(prompt: str, default: bool = False) -> bool:
    d = "y" if default else "n"
    while True:
        raw = input(f"{prompt} (y/n) [{d}]: ").strip().lower() or d
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Answer y or n.")


def pause():
    input("\nPress Enter to return to the menu...")


# ------------------------------------------------------------------
# Part definition shared by modules 2, 3, 4, 5
# ------------------------------------------------------------------

def ask_part(default_pressure: float = 6.0) -> ms.PartDefinition:
    print("\nPART DEFINITION  (Enter = default: the project's 1 m² carbon/epoxy panel)")
    length = ask("Length (m)", 1.0, float, minimum=0.01)
    width = ask("Width (m)", 1.0, float, minimum=0.01)
    height = ask("Height / depth (m)", 0.05, float, minimum=0.0)
    geometry = ask("Geometry: flat / curved / angled", "flat", str, ["flat", "curved", "angled"])
    angle, layup = 90.0, "QI"
    if geometry == "angled":
        angle = ask("Corner angle (deg)", 90.0, float, minimum=1)
        layup = ask("Layup: UD / QI", "QI", str, ["UD", "QI"])
    cure_T = ask("Cure temperature (°C)", 180.0, float, minimum=30)
    pressure = ask("Cure pressure (bar)", default_pressure, float, minimum=0)
    ramp = ask("Heating ramp (°C/min)", 2.0, float, minimum=0.1)
    part_cte = ask("Part in-plane CTE (µm/m·°C)", 2.0, float)
    tolerance = ask_optional_float("Allowed dimensional deviation over the part (mm)")
    hard = yes("Is that tolerance a HARD limit?", False) if tolerance else False
    cycles = ask("Cure cycles the tool must survive", 50, int, minimum=1)
    ceiling = ask_optional_float("Tool cost ceiling (₹)")
    class_a = yes("Class-A cosmetic surface required?", False)
    print("Profiles: prototype | production | aerospace")
    profile = ask("Application profile", "production", str, list(ms.PROFILE_JUDGMENTS))
    return ms.PartDefinition(
        length_m=length, width_m=width, height_m=height, geometry=geometry,
        corner_angle_deg=angle, layup=layup, cure_temp_C=cure_T, cure_pressure_bar=pressure,
        ramp_rate_C_min=ramp, part_cte_ppm=part_cte, tolerance_mm=tolerance,
        tolerance_hard=hard, cycles_required=cycles, cost_ceiling_inr=ceiling,
        class_a_surface=class_a, profile=profile)


def choose_cycle(sandwich: bool) -> cp.CureCycle:
    cycles = cp.load_cycles()
    default = "M18-1_SAND" if sandwich else "M18-1_MONO"
    print("\nCURE CYCLES (from project documents)")
    for i, c in enumerate(cycles, 1):
        print(f"  {i}. {c.cycle_id:<14} {c.product} — {c.part_type}")
    ids = [c.cycle_id for c in cycles]
    choice = ask("Cycle number", ids.index(default) + 1, int, list(range(1, len(cycles) + 1)))
    return cycles[choice - 1]


# ------------------------------------------------------------------
# Menu actions
# ------------------------------------------------------------------

def run_fiber_recommender():
    import updated_database_recommender_v4 as v4
    try:
        v4.main()
    except (EOFError, KeyboardInterrupt):
        print("\nFiber recommender cancelled.")


def run_mold_selector() -> ms.SelectionResult:
    part = ask_part()
    result = ms.select(part)
    print("\n" + ms.report_card(result))
    return result


def run_cure_planner(tool_calc=None, sandwich=None, pressure=None) -> cp.CurePlan:
    if sandwich is None:
        sandwich = yes("\nIs the part a honeycomb sandwich panel?", True)
    cycle = choose_cycle(sandwich)
    if pressure is None:
        pressure = ask("Autoclave pressure (bar)", cycle.pressure_max, float, minimum=0)
    kwargs = {}
    if tool_calc is not None:
        kwargs = dict(tool_max_service_C=tool_calc.material.max_service_C,
                      tool_tau_min=tool_calc.tau_min, tool_name=tool_calc.material.name)
    plan = cp.plan(cycle, pressure_bar=pressure, sandwich=sandwich, **kwargs)
    print("\n" + cp.plan_text(plan))
    if yes("\nExport the ANSYS convection table (CSV)?", False):
        REPORT_DIR.mkdir(exist_ok=True)
        path = cp.write_ansys_table(plan.points, REPORT_DIR / f"ansys_table_{cycle.cycle_id}.csv")
        print(f"Saved: {path}")
    return plan


def run_cost_estimator():
    length = ask("\nPanel length (m)", 1.0, float, minimum=0.01)
    width = ask("Panel width (m)", 1.0, float, minimum=0.01)
    sandwich = yes("Honeycomb sandwich panel?", True)
    panels = ask("Panels per DOE condition", 3, int, minimum=1)
    print("\n" + ce.bom_text(length, width, sandwich, panels_per_condition=panels))


def run_full_report():
    print("\nFULL PROJECT REPORT — mold selection + cure plan + BOM/cost")
    sandwich = yes("Is the part a honeycomb sandwich panel?", True)
    # Sandwich parts cure at 2 bar so the honeycomb core is not crushed (M18/1 datasheet).
    part = ask_part(default_pressure=2.0 if sandwich else 6.0)
    panels = ask("Panels per DOE condition", 3, int, minimum=1)

    selection = ms.select(part)
    sections = [ms.report_card(selection)]
    if selection.ranking:
        best = selection.ranking[0].calc
        plan = cp.plan(choose_cycle(sandwich), pressure_bar=part.cure_pressure_bar,
                       sandwich=sandwich, tool_max_service_C=best.material.max_service_C,
                       tool_tau_min=best.tau_min, tool_name=best.material.name)
        sections.append(cp.plan_text(plan))

        moulds = mould_types_for(selection)
        sections.append(ce.bom_text(part.length_m, part.width_m, sandwich,
                                    moulds=moulds or None, panels_per_condition=panels))

    text = "\n\n".join(sections)
    print("\n" + text)
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / f"project_report_{datetime.now():%Y%m%d_%H%M%S}.txt"
    path.write_text(text, encoding="utf-8")
    print(f"\nSaved: {path}")


def mould_types_for(selection: ms.SelectionResult) -> list:
    """Map the DOE pair (or the winner) to the BOM document's mould cost rows."""
    by_material = {r["tool_material_id"]: r["mould_type"]
                   for r in ce.mould_options() if r["tool_material_id"]}
    chosen = list(selection.doe_pair) if selection.doe_pair else [selection.ranking[0].calc.material]
    return [by_material[m.material_id] for m in chosen if m.material_id in by_material]


def run_prepreg_selector():
    print("\nPREPREG SELECTOR — state what the laminate must achieve.")
    req = ps.LaminateRequirements(
        min_strength_mpa=ask("Min 0° tensile strength (MPa)", 2000.0, float, minimum=0),
        min_modulus_gpa=ask_optional_float("Min 0° tensile modulus (GPa)"),
        max_density_g_cm3=ask_optional_float("Max laminate density (g/cm³)"),
        min_tg_C=ask_optional_float("Min dry Tg (°C)"),
        form=ask("Fiber form", "any", choices=["any", "UD", "fabric"]),
        part_type=ask("Part type", "monolithic", choices=["monolithic", "sandwich"]),
        equipment=ask("Equipment", "autoclave", choices=["autoclave", "oven"]),
        laminate_mm=ask("Laminate / skin thickness (mm)", 2.0, float, minimum=0.1))
    res = ps.select(req)
    print("\n" + ps.selection_text(res))
    if res.best:
        print("\n" + cp.plan_text(cp.plan(cp.get_cycle(res.best.cycle_id), laminate_mm=req.laminate_mm,
                                         sandwich=req.part_type == "sandwich", equipment=req.equipment)))


def show_sources():
    print("""
DATA SOURCES & LIMITATIONS
  Fibers / prepregs / resins  Carbon_Fiber_Master_v6, Prepreg_Master_v2, Resin_Master_v10 (sourced rows)
  Prepreg laminate values     literature_data/prepreg_laminate_properties.csv (Hexcel, Toray datasheets)
  Lamina data                 literature_data/SOURCES.md (NCAMP, MIL-HDBK-17-2F, Toray, Hexcel)
  Tool materials              tooling_data/SOURCES.md (Carpenter/HTM, Proto Labs, Hexcel HexTool,
                              GrafTech, Easy Composites, RAMPF, General Plastics, project reports)
  Cure cycles                 process_data/SOURCES.md (33 cycles: Hexcel, Toray, NCAMP, MIL-HDBK-17, project files)
  Costs (₹, indicative)       process_data/*.csv (project BOM document)
  Heat transfer               Fisher, Levy & Kratz (2022), measured autoclave HTCs
  Spring-in                   Albert & Fernlund (2002), via the project spring-in summary

  The engines rank and estimate; they do not replace FEM (ANSYS ACP/ACCS) distortion
  prediction, supplier qualification or trial parts. Unpublished values score as
  "not demonstrated" and are flagged in every report.""")


MENU = [
    ("1", "Fiber & prepreg recommender", run_fiber_recommender),
    ("2", "Mold (tool) material selector", run_mold_selector),
    ("3", "Cure-cycle planner", run_cure_planner),
    ("4", "BOM & cost estimator", run_cost_estimator),
    ("5", "Full project report (mold + cure + cost)", run_full_report),
    ("6", "Validation cases (D6)", lambda: print("\n" + vc.validation_text())),
    ("7", "Data sources & limitations", show_sources),
    ("8", "Prepreg selector (requirements → prepreg + cure cycle)", run_prepreg_selector),
]


def main():
    while True:
        print("\n" + "=" * 60)
        print(" AUTOCLAVE PREPREG COMPOSITE DECISION TOOL")
        print("=" * 60)
        for key, label, _ in MENU:
            print(f"  {key}. {label}")
        print("  0. Exit")
        choice = input("Choose: ").strip()
        if choice in ("0", "q", "exit"):
            print("Goodbye.")
            return
        action = next((a for k, _, a in MENU if k == choice), None)
        if action is None:
            print("Choose a number from the menu.")
            continue
        action()
        pause()


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print("\nExited.")
