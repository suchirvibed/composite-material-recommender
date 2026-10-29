"""
Autoclave Prepreg Study — desktop decision tool.

A guided window that follows the project's methodology (Master Report):

  Project      study article, problem statements PS1-PS3, scoping question
  1 Material   fiber / prepreg / resin recommendation (+ HexPly M18/1 reference)
  2 Tooling    mold material selection — PS1 tool-part thermal interaction
  3 Cure       cure-cycle plan with tool lag — PS2 cure-cycle sensitivity
  4 DOE        Table 1 test matrix with predictions; analyse measured results
  5 Cost       BOM and ₹ cost of the DOE study
  6 Report     one document with every step, saved to reports/

Start:  py project_gui.py   (or double-click run.bat)
"""

from __future__ import annotations

import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import cost_estimator as ce
import cure_planner as cp
import doe
import prepreg_selector as ps
import mold_selector as ms
import updated_database_recommender_v4 as v4

BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "reports"

PROBLEMS = [
    ("PS1", "Tool–part thermal interaction",
     "How do CTE mismatch and spring-in affect the geometric tolerance of the cured part?",
     "Tab 2 (tooling) and DOE factor 'tool material'"),
    ("PS2", "Cure-cycle sensitivity",
     "How do pressure, ramp rate and dwell time relate to dimensional deviation?",
     "Tab 3 (cure plan) and DOE factors 'pressure / ramp / dwell'"),
    ("PS3", "Layup and geometry effects",
     "How do stacking sequence and geometry drive warpage and tolerance stack-up?",
     "DOE factors 'layup / thickness / corner geometry'"),
]

# HexPly M18/1 — the prepreg documented in the project folder (datasheet guide).
M18_CARD = (
    "Reference prepreg in the project folder: HexPly M18/1 (Hexcel), 180 °C toughened epoxy\n"
    "  UD (G947): 0° tensile 1750 MPa, modulus 128 GPa, compression 1200 MPa, ILSS 95 MPa (55 % Vf, RT dry)\n"
    "  Woven (G939): 0° tensile 800 MPa, modulus 65 GPa | cured ply 0.165 mm (UD) / 0.227 mm (woven)\n"
    "  Cure: 2 °C/min → 80 °C 1 h → 2 °C/min → 180 °C 2 h; monolithic 4-7 bar, sandwich 2 bar, −0.8 bar vacuum\n"
    "  Tg 200 °C dry / 170 °C wet; service 135 °C wet; out-life 15 days at 23 °C; shelf life 12 months at −18 °C")

# Short names shown in dropdowns and tables instead of database IDs.
SHORT_NAMES = {
    "INVAR36": "Invar 36", "AL6061": "Aluminium 6061-T6", "STEEL_MILD": "Mild steel",
    "NICKEL_EF": "Electroformed nickel", "CFRP_BMI": "CFRP tooling (HexTool M61)",
    "GRAPHITE_ATJ": "Graphite (ATJ)", "BOARD_EPOXY_130": "Epoxy board 130 °C",
    "BOARD_EPOXY_HT": "Epoxy board 190 °C", "FOAM_EPU_HT": "Tooling foam FR-4800",
}
UNVERIFIED = "⚠"

FONT = ("Segoe UI", 10)
MONO = ("Consolas", 9)


def number(var: tk.StringVar, name: str, minimum: float | None = None,
           optional: bool = False) -> float | None:
    """Read a numeric field, raising ValueError with a friendly message."""
    text = var.get().strip()
    if text == "" and optional:
        return None
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"'{name}' must be a number (got '{text}').")
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"'{name}' must be a finite number.")
    if minimum is not None and value < minimum:
        raise ValueError(f"'{name}' must be at least {minimum}.")
    return value


class Output(ScrolledText):
    """Read-only monospaced text area."""

    def __init__(self, master, height=14):
        super().__init__(master, height=height, font=MONO, wrap="word")
        self.configure(state="disabled")

    def show(self, text: str):
        self.configure(state="normal")
        self.delete("1.0", "end")
        self.insert("1.0", text)
        self.configure(state="disabled")


def table(master, columns, widths, height=8):
    frame = ttk.Frame(master)
    tree = ttk.Treeview(frame, columns=columns, show="headings", height=height)
    for c, w in zip(columns, widths):
        tree.heading(c, text=c)
        tree.column(c, width=w, anchor="w")
    bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    tree.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    return frame, tree


def fill(tree, rows):
    tree.delete(*tree.get_children())
    for r in rows:
        tree.insert("", "end", values=r)


def hint(master, text):
    return ttk.Label(master, text=text, foreground="#555", wraplength=980, justify="left")


class StudyApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Autoclave Prepreg Study — Decision Tool")
        self.geometry("1180x820")
        self.minsize(980, 680)
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", font=FONT)
        style.configure("Title.TLabel", font=("Segoe UI", 15, "bold"))
        style.configure("Head.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Run.TButton", font=("Segoe UI", 10, "bold"))

        self.sections: dict[str, str] = {}       # report text per step
        self.selection: ms.SelectionResult | None = None
        self.plan: cp.CurePlan | None = None
        self.runs: list = []
        self.doe_factors: list = []
        self.materials = ms.load_tool_materials()
        self.material_names = {m.material_id: SHORT_NAMES.get(m.material_id, m.name)
                               for m in self.materials}
        self.material_ids = {name: mid for mid, name in self.material_names.items()}
        self.cycles = cp.load_cycles()
        self.label_by_cycle = {c.cycle_id: f"{c.product} · {c.part_type} · {c.process} · "
                                           f"{c.peak_C:.0f} °C  [{c.cycle_id}]" for c in self.cycles}
        self.cycle_by_label = {self.label_by_cycle[c.cycle_id]: c for c in self.cycles}

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.status = tk.StringVar(value="Ready — the project's study article is loaded. "
                                         "Work through the tabs left to right.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w",
                  padding=(8, 3)).pack(fill="x", side="bottom")

        self._project_tab()
        self._material_tab()
        self._tooling_tab()
        self._cure_tab()
        self._doe_tab()
        self._cost_tab()
        self._report_tab()
        self._guard(self._select_prepreg)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _tab(self, title):
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text=title)
        return frame

    def _field(self, parent, row, col, label, default, width=9):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=(0, 4), pady=2)
        var = tk.StringVar(value=str(default))
        ttk.Entry(parent, textvariable=var, width=width).grid(row=row, column=col + 1,
                                                              sticky="w", padx=(0, 16), pady=2)
        return var

    def _combo(self, parent, row, col, label, values, default, width=24):
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=(0, 4), pady=2)
        var = tk.StringVar(value=default)
        ttk.Combobox(parent, textvariable=var, values=values, state="readonly",
                     width=width).grid(row=row, column=col + 1, sticky="w", padx=(0, 16), pady=2)
        return var

    def _check(self, parent, row, col, label, default=False):
        var = tk.BooleanVar(value=default)
        ttk.Checkbutton(parent, text=label, variable=var).grid(row=row, column=col, columnspan=2,
                                                               sticky="w", pady=2)
        return var

    def _guard(self, fn):
        """Run a step; show input problems as a dialog instead of a traceback."""
        try:
            fn()
        except ValueError as exc:
            messagebox.showwarning("Check the inputs", str(exc), parent=self)
            self.status.set(f"Input problem: {exc}")

    # ------------------------------------------------------------------
    # Project tab
    # ------------------------------------------------------------------

    def _project_tab(self):
        t = self._tab("Project")
        ttk.Label(t, text="Design and Process Study of Autoclave-Cured Prepreg Composites",
                  style="Title.TLabel").pack(anchor="w")
        hint(t, "Enter what the laminate must achieve. The tool picks the carbon-fiber prepreg from "
                "the project prepreg database (laminate values from each system's datasheet) and "
                "recommends the cure cycle from that prepreg's own datasheet. Every tab uses the result.").pack(
            anchor="w", pady=(2, 6))

        req = ttk.LabelFrame(t, text="Laminate requirements", padding=8)
        req.pack(fill="x")
        self.r_strength = self._field(req, 0, 0, "Min 0° tensile strength (MPa)", 2000)
        self.r_modulus = self._field(req, 0, 2, "Min 0° tensile modulus (GPa, blank = any)", "")
        self.r_density = self._field(req, 0, 4, "Max laminate density (g/cm³, blank = any)", 1.60)
        self.r_tg = self._field(req, 1, 0, "Min dry Tg (°C, blank = any)", "")
        self.r_form = self._combo(req, 1, 2, "Fiber form", ["any", "UD", "fabric"], "any", 10)
        self.r_equip = self._combo(req, 1, 4, "Equipment", ["autoclave", "oven"], "autoclave", 10)

        part = ttk.LabelFrame(t, text="Part", padding=8)
        part.pack(fill="x", pady=(6, 0))
        self.a_len = self._field(part, 0, 0, "Length (m)", 1.0)
        self.a_wid = self._field(part, 0, 2, "Width (m)", 1.0)
        self.a_part = self._combo(part, 0, 4, "Part type", ["monolithic laminate", "honeycomb sandwich"],
                                  "monolithic laminate", 20)
        self.a_lam = self._field(part, 1, 0, "Laminate / skin thickness (mm)", 2.0)
        self.a_cte = self._field(part, 1, 2, "Part CTE (µm/m·°C)", 2.0)
        # Set by the selected prepreg's cure cycle; editable to explore overrides.
        self.a_temp = self._field(part, 2, 0, "Cure temperature (°C) — from cycle", 180)
        self.a_press = self._field(part, 2, 2, "Cure pressure (bar) — from cycle", 7.0)
        self.a_ramp = self._field(part, 2, 4, "Heating ramp (°C/min) — from cycle", 2.0)
        self.a_cycle = self._combo(part, 3, 0, "Cure cycle", list(self.cycle_by_label),
                                   self.label_by_cycle["HEX_8552_EU_MONO"], 80)
        part.grid_slaves(row=3, column=1)[0].grid_configure(columnspan=5)   # long cycle names

        bar = ttk.Frame(t)
        bar.pack(fill="x", pady=6)
        ttk.Button(bar, text="Select prepreg and cure cycle", style="Run.TButton",
                   command=lambda: self._guard(self._select_prepreg)).pack(side="left")
        ttk.Button(bar, text="Datasheets needed…", command=self._show_missing).pack(side="left", padx=6)
        ttk.Button(bar, text="Reset requirements", command=self._reset_article).pack(side="left")
        self.p_card = tk.StringVar()
        ttk.Label(t, textvariable=self.p_card, foreground="#1d4f91", wraplength=1100,
                  justify="left").pack(anchor="w")
        frame, self.p_tree = table(t, ("#", "Prepreg", "Strength MPa", "Modulus GPa", "Density",
                                       "σ/ρ", "Cure cycle", "Score"),
                                   (36, 400, 90, 90, 70, 60, 170, 60), 4)
        frame.pack(fill="x", pady=4)
        self.prepreg = None

        probs = ttk.LabelFrame(t, text="Problem statements and where the tool answers them", padding=6)
        probs.pack(fill="x", pady=4)
        for i, (code, title, question, where) in enumerate(PROBLEMS):
            ttk.Label(probs, text=f"{code} — {title}: {question}  →  {where}", wraplength=1100).grid(
                row=i, column=0, sticky="w")

        scope = ttk.LabelFrame(t, text="Scoping question (Master Report §2.4) — sets the DOE factors",
                               padding=10)
        scope.pack(fill="x")
        self.focus = tk.StringVar(value="process")
        for i, (key, label) in enumerate([
                ("process", "Process-driven variation: tool material, ramp rate, dwell time"),
                ("design", "Design-driven variation: layup, skin thickness, corner geometry"),
                ("tooling only", "Tooling only: low-CTE vs high-CTE tool")]):
            ttk.Radiobutton(scope, text=label, value=key, variable=self.focus,
                            command=self._apply_focus).grid(row=i, column=0, sticky="w")
        hint(scope, "Confirm this with the reviewing professor before detailed experimental work "
                    "(Master Report §2.4). Subject to budget and availability of resources.").grid(
            row=3, column=0, sticky="w", pady=(6, 0))

    def _reset_article(self):
        for var, value in [(self.a_len, 1.0), (self.a_wid, 1.0), (self.a_lam, 2.0), (self.a_cte, 2.0),
                           (self.r_strength, 2000), (self.r_modulus, ""), (self.r_density, 1.60),
                           (self.r_tg, "")]:
            var.set(str(value))
        self.a_part.set("monolithic laminate")
        self.r_form.set("any")
        self.r_equip.set("autoclave")
        self._guard(self._select_prepreg)

    def requirements(self) -> ps.LaminateRequirements:
        return ps.LaminateRequirements(
            min_strength_mpa=number(self.r_strength, "Min 0° tensile strength", 0),
            min_modulus_gpa=number(self.r_modulus, "Min 0° tensile modulus", 0, optional=True),
            max_density_g_cm3=number(self.r_density, "Max laminate density", 0.5, optional=True),
            min_tg_C=number(self.r_tg, "Min dry Tg", 0, optional=True),
            form=self.r_form.get(),
            part_type="sandwich" if self.a_part.get().startswith("honeycomb") else "monolithic",
            equipment=self.r_equip.get(),
            laminate_mm=number(self.a_lam, "Laminate thickness", 0.1))

    def _select_prepreg(self):
        res = ps.select(self.requirements())
        self.prepreg_result = res
        rows = [(c.rank, c.name, f"{c.strength:.0f}", f"{c.modulus:.0f}", f"{c.density:.2f}",
                 f"{c.strength / c.density:.0f}", c.cycle_id, f"{c.score:.2f}") for c in res.ranked]
        fill(self.p_tree, rows)
        self.sections["0 Prepreg selection"] = ps.selection_text(res).split("\n", 3)[3]   # drop banner
        best = res.best
        if best is None:
            self.prepreg = None
            closest = sorted(res.rejected, key=lambda r: len(r.reasons))[:2]
            self.p_card.set("No prepreg with published laminate data meets every requirement. Closest: "
                            + " | ".join(f"{r.name}: {'; '.join(r.reasons)}" for r in closest)
                            + f"\n{len(res.no_data)} systems have no laminate data yet — see Datasheets needed.")
            self.status.set("Prepreg selection: no candidate — relax a requirement.")
            return
        self.prepreg = best
        cycle = cp.get_cycle(best.cycle_id)
        first_ramp = next((s for s in cycle.steps if s.kind == "ramp"), None)
        self.a_cycle.set(self.label_by_cycle[cycle.cycle_id])
        self.a_temp.set(f"{cycle.peak_C:g}")
        self.a_press.set(f"{cycle.pressure_max:g}")
        if first_ramp:
            self.a_ramp.set(f"{first_ramp.rate():g}")
        if hasattr(self, "c_cycle"):
            self.c_cycle.set(self.label_by_cycle[cycle.cycle_id])
            self.c_lam.set(self.a_lam.get())
            self.c_equip.set(self.r_equip.get())
        self.p_card.set(
            f"Selected: {best.name} — {best.strength:.0f} MPa, {best.modulus:.0f} GPa, "
            f"{best.density:.2f} g/cm³, {best.tg_text} ({best.variant['source_document']})\n"
            f"Cure cycle from its datasheet: {cycle.product} · {cycle.part_type} · {cycle.process}, "
            f"{cycle.peak_C:.0f} °C, {cp.pressure_text(cycle)} — {best.cycle_reason}. "
            f"{len(res.ranked)} candidate(s) pass; {len(res.no_data)} systems not evaluated (no data).")
        self.status.set(f"Prepreg: {best.name}; cure cycle {cycle.cycle_id} set for every tab.")

    def _show_missing(self):
        res = getattr(self, "prepreg_result", None) or ps.select(self.requirements())
        with_cycle = [n for n in res.no_data if n["has_cure_cycle"]]
        lines = [f"{len(res.no_data)} prepreg systems in the database have no laminate data in hand, so "
                 f"they cannot be selected by strength. Send their product data sheets (0° tensile "
                 f"strength and modulus, laminate density, Tg, cure cycle):", ""]
        lines += [f"• {n['product']} — {n['matrix']}, cure {n['cure_C']} °C" for n in res.no_data]
        if with_cycle:
            lines += ["", "Cure cycle already on file (laminate data still needed): "
                      + ", ".join(n["product"] for n in with_cycle)]
        messagebox.showinfo("Datasheets needed", "\n".join(lines), parent=self)

    def article(self) -> doe.StudyArticle:
        return doe.StudyArticle(
            length_m=number(self.a_len, "Length", 0.01), width_m=number(self.a_wid, "Width", 0.01),
            sandwich=self.a_part.get().startswith("honeycomb"),
            cure_temp_C=number(self.a_temp, "Cure temperature", 30),
            base_pressure_bar=number(self.a_press, "Cure pressure", 0),
            base_ramp_C_min=number(self.a_ramp, "Heating ramp", 0.1),
            part_cte_ppm=number(self.a_cte, "Part CTE"), cycle_id=self.a_cycle_id())

    def a_cycle_id(self) -> str:
        cycle = self.cycle_by_label.get(self.a_cycle.get())
        return cycle.cycle_id if cycle else "HEX_8552_EU_MONO"

    # ------------------------------------------------------------------
    # 1 Material system
    # ------------------------------------------------------------------

    def _material_tab(self):
        t = self._tab("1 · Material system")
        hint(t, "Which fiber, prepreg and resin? Fibers are filtered by HARD limits, then scored "
                "0-100 with AHP-derived weights. The project's documented prepreg is shown for "
                "reference.").pack(anchor="w")
        ttk.Label(t, text=M18_CARD, font=MONO, foreground="#1d4f91").pack(anchor="w", pady=6)

        form = ttk.LabelFrame(t, text="Requirements", padding=8)
        form.pack(fill="x")
        apps = [a["name"] for k, a in v4.APPLICATIONS.items() if a["ahp_judgments"]]
        self.m_app = self._combo(form, 0, 0, "Application", apps, "Aerospace")
        self.m_str = self._field(form, 0, 2, "Min strength (MPa)", 4000)
        self.m_mod = self._field(form, 0, 4, "Min modulus (GPa)", 230)
        self.m_den = self._field(form, 1, 0, "Max density (g/cm³)", 1.85)
        self.m_elo = self._field(form, 1, 2, "Min elongation (%)", 1.5)
        self.m_hard_s = self._check(form, 2, 0, "Strength is HARD", True)
        self.m_hard_m = self._check(form, 2, 2, "Modulus is HARD", False)
        self.m_hard_d = self._check(form, 2, 4, "Density is HARD", True)
        procs = [p for p in v4.PROCESS_OPTIONS.values() if p] + ["(none)"]
        mats = [m for m in v4.MATRIX_OPTIONS.values() if m] + ["(none)"]
        self.m_proc = self._combo(form, 3, 0, "Process", procs, "autoclave")
        self.m_matrix = self._combo(form, 3, 2, "Matrix", mats, "epoxy")
        self.m_cert = self._check(form, 3, 4, "Require stated certification", False)
        ttk.Button(form, text="Recommend materials", style="Run.TButton",
                   command=lambda: self._guard(self._run_material)).grid(row=4, column=0, pady=6, sticky="w")

        frame, self.m_tree = table(t, ("#", "Fiber", "Strength MPa", "Modulus GPa", "Density",
                                       "Score %", "UD lamina 0°"),
                                   (40, 230, 95, 95, 70, 70, 420), 8)
        frame.pack(fill="both", expand=True, pady=6)
        self.m_out = Output(t, 9)
        self.m_out.pack(fill="both", expand=True)

    def _run_material(self):
        app_key = next(k for k, a in v4.APPLICATIONS.items() if a["name"] == self.m_app.get())
        app = dict(v4.APPLICATIONS[app_key])
        app["importance"] = v4.ahp_weights(app["ahp_judgments"]).weights
        proc = None if self.m_proc.get() == "(none)" else self.m_proc.get()
        matrix = None if self.m_matrix.get() == "(none)" else self.m_matrix.get()
        req = v4.Requirements(
            number(self.m_str, "Min strength", 0), number(self.m_mod, "Min modulus", 0),
            number(self.m_den, "Max density", 0.01), number(self.m_elo, "Min elongation", 0),
            self.m_hard_s.get(), self.m_hard_m.get(), self.m_hard_d.get(), False,
            proc, matrix, self.m_cert.get())
        fibers = v4.load_fiber_database()
        result = v4.build_ranked_results(fibers, req, app)
        if result.empty:
            fill(self.m_tree, [])
            conflict = v4.smallest_conflict(fibers, req)
            closest = v4.closest_candidate(fibers, req)
            msg = "No fiber meets every HARD limit."
            if conflict:
                msg += f"\nThese limits conflict together: {' + '.join(conflict)}."
            if closest:
                msg += f"\nClosest fiber: {closest['name']} — " + "; ".join(closest["misses"])
            self.m_out.show(msg)
            self.status.set("Material system: no candidate — relax a HARD limit.")
            return
        rows = []
        for _, r in result.head(15).iterrows():
            lam = (f"Xt {r['Lamina_Xt_MPa']:.0f} MPa, E1 {r['Lamina_E1_GPa']:.0f} GPa — {r['Lamina_Basis']}"
                   if r["Lamina_Xt_MPa"] == r["Lamina_Xt_MPa"] else r["Lamina_Basis"])
            rows.append((int(r["Rank"]), f"{r['Manufacturer']} {r['Product']}{v4.tie_note(r)}",
                         f"{r['Strength_MPa']:.0f}", f"{r['Modulus_GPa']:.0f}",
                         f"{r['Density_g_cm3']:.2f}", f"{r['Relative_Score_percent']:.1f}", lam))
        fill(self.m_tree, rows)

        prepregs = v4.build_prepreg_results(v4.load_prepreg_database(), req, result.head(5))
        resins = v4.build_resin_results(v4.load_resin_database(), req)
        lines = ["PREPREG SYSTEMS"]
        lines += ([f"  #{int(p['Rank'])} {p['Manufacturer']} {p['Product_System']} — "
                   f"{p['Final_Score']:.0f}/100{v4.tie_note(p)} | {p['Matrix']} | fiber {p['Fiber_Grade']} "
                   f"({p['Fiber_Match']})" for _, p in prepregs.head(5).iterrows()]
                  if not prepregs.empty else ["  " + v4.empty_reason("prepreg", req)])
        lines.append("\nRESIN SYSTEMS")
        lines += ([f"  #{int(s['Rank'])} {s['Manufacturer']} {s['Product_System']} — "
                   f"{s['Final_Score']:.0f}/100{v4.tie_note(s)} | {s['Resin_Family']} | "
                   f"{s['Process_Suitability']}" for _, s in resins.head(5).iterrows()]
                  if not resins.empty else ["  " + v4.empty_reason("resin", req)])
        lines.append("\nCandidates are database-level; they are not proof of qualified "
                     "fiber + resin compatibility.")
        self.m_out.show("\n".join(lines))

        top = result.iloc[0]
        self.sections["1 Material system"] = (
            f"Application {app['name']}; strength ≥ {req.strength_mpa:g} MPa, modulus ≥ "
            f"{req.modulus_gpa:g} GPa, density ≤ {req.max_density_g_cm3:g}, process {proc}, matrix {matrix}.\n"
            + "\n".join(f"  #{r[0]} {r[1]} — {r[5]} % — {r[6]}" for r in rows[:5])
            + "\n\n" + "\n".join(lines))
        self.status.set(f"Material system: top fiber {top['Manufacturer']} {top['Product']}.")

    # ------------------------------------------------------------------
    # 2 Tooling (PS1)
    # ------------------------------------------------------------------

    def _tooling_tab(self):
        t = self._tab("2 · Tooling (PS1)")
        hint(t, "Which mold material? Hard constraints reject unsuitable tools with a reason; "
                "survivors are scored on CTE mismatch δ = |α_tool − α_part|·ΔT·L, thermal lag, "
                "mass, cycle life and ₹ cost, weighted by the chosen profile.").pack(anchor="w")
        form = ttk.LabelFrame(t, text="Tooling requirements", padding=8)
        form.pack(fill="x", pady=6)
        self.t_profile = self._combo(form, 0, 0, "Profile", list(ms.PROFILE_JUDGMENTS), "production", 14)
        self.t_tol = self._field(form, 0, 2, "Allowed deviation (mm, blank = none)", "")
        self.t_hard = self._check(form, 0, 4, "Tolerance is HARD", False)
        self.t_cycles = self._field(form, 1, 0, "Cure cycles needed", 6)
        self.t_cost = self._field(form, 1, 2, "Tool cost ceiling ₹ (blank = none)", "")
        self.t_classa = self._check(form, 1, 4, "Class-A surface", False)
        self.t_geom = self._combo(form, 2, 0, "Geometry", ["flat", "curved", "angled"], "flat", 14)
        self.t_angle = self._field(form, 2, 2, "Corner angle (°, angled only)", 90)
        self.t_layup = self._combo(form, 2, 4, "Layup", ["QI", "UD"], "QI", 6)
        ttk.Button(form, text="Select tool material", style="Run.TButton",
                   command=lambda: self._guard(self._run_tooling)).grid(row=3, column=0, pady=6, sticky="w")
        self.t_pair = tk.StringVar(value="")
        ttk.Label(form, textvariable=self.t_pair, foreground="#1d4f91").grid(row=3, column=1, columnspan=5, sticky="w")

        frame, self.t_tree = table(t, ("#", "Tool material", "δ mm", "Lag °C", "Mass kg", "Cycles",
                                       "Cost ₹", "Score"),
                                   (40, 380, 70, 70, 80, 70, 110, 70), 7)
        frame.pack(fill="x", pady=4)
        self.t_out = Output(t, 14)
        self.t_out.pack(fill="both", expand=True)

    def tooling_part(self) -> ms.PartDefinition:
        a = self.article()
        tol = number(tk.StringVar(value=self.t_tol.get()), "Allowed deviation", 0, optional=True)
        return ms.PartDefinition(
            length_m=a.length_m, width_m=a.width_m, geometry=self.t_geom.get(),
            corner_angle_deg=number(self.t_angle, "Corner angle", 1), layup=self.t_layup.get(),
            cure_temp_C=a.cure_temp_C, cure_pressure_bar=a.base_pressure_bar,
            ramp_rate_C_min=a.base_ramp_C_min, part_cte_ppm=a.part_cte_ppm,
            tolerance_mm=tol, tolerance_hard=self.t_hard.get() and tol is not None,
            cycles_required=int(number(self.t_cycles, "Cure cycles", 1)),
            cost_ceiling_inr=number(self.t_cost, "Tool cost ceiling", 0, optional=True),
            class_a_surface=self.t_classa.get(), profile=self.t_profile.get())

    def _run_tooling(self):
        self.selection = ms.select(self.tooling_part())
        rows = [(r.rank, r.calc.material.name, f"{r.calc.delta_mm:.2f}",
                 "n/a" if r.calc.lag_C is None else f"{r.calc.lag_C:.1f}",
                 "n/a" if r.calc.mass_kg is None else f"{r.calc.mass_kg:.0f}",
                 "n/a" if r.calc.cycle_life is None else f"{r.calc.cycle_life:.0f}",
                 "n/a" if r.calc.cost_mid is None else ce.inr(r.calc.cost_mid) + (f" {UNVERIFIED}" if "UNVERIFIED" in r.calc.material.cost_basis else ""),
                 f"{r.score:.3f}") for r in self.selection.ranking]
        fill(self.t_tree, rows)
        card = ms.report_card(self.selection)
        self.t_out.show(card)
        self.sections["2 Tooling (PS1)"] = card
        if self.selection.doe_pair:
            low, high = self.selection.doe_pair
            self.t_pair.set(f"DOE pairing → low-CTE: {low.name} | high-CTE: {high.name} "
                            f"(copied to the DOE tab)")
            self.doe_vars["tool"][1].set(self.material_names[low.material_id])
            self.doe_vars["tool"][2].set(self.material_names[high.material_id])
        else:
            self.t_pair.set("No low-CTE + high-CTE pair survives — the DOE keeps its tool levels.")
        if self.selection.ranking:
            winner = self.selection.ranking[0].calc.material
            self.c_tool.set(self.material_names[winner.material_id])
            close = " (close call — see sensitivity)" if self.selection.sweep["close_call"] else ""
            self.status.set(f"Tooling: {winner.name} ranks first{close}.")
        else:
            self.status.set("Tooling: no material passes the hard constraints.")

    # ------------------------------------------------------------------
    # 3 Cure cycle (PS2)
    # ------------------------------------------------------------------

    def _cure_tab(self):
        t = self._tab("3 · Cure cycle (PS2)")
        hint(t, "Which cure cycle, how long, and does the tool keep up? 30 documented cycles "
                "(Hexcel datasheets, NCAMP, MIL-HDBK-17, project files) with their ramp ranges, "
                "staged pressure and vacuum, vent temperature and post-cure. The tool curve is a "
                "lumped model (τ = ρ·c_p·t / h); the final hold is extended for tool lag.").pack(anchor="w")

        find = ttk.LabelFrame(t, text="Find a documented cycle", padding=6)
        find.pack(fill="x", pady=(6, 2))
        self.c_proc = self._combo(find, 0, 0, "Process", ["All", "autoclave", "oven (vacuum bag only)"], "All", 20)
        self.c_matrix = self._combo(find, 0, 2, "Matrix", ["All", "epoxy", "BMI", "cyanate ester",
                                                           "PEEK", "polyimide"], "All", 14)
        self.c_part = self._combo(find, 0, 4, "Part", ["All", "monolithic", "sandwich", "tool"], "All", 12)
        ttk.Label(find, text="Cycle").grid(row=1, column=0, sticky="w")
        self.c_cycle = tk.StringVar()
        self.c_cycle_box = ttk.Combobox(find, textvariable=self.c_cycle, state="readonly", width=92)
        self.c_cycle_box.grid(row=1, column=1, columnspan=5, sticky="w", pady=2)
        for var in (self.c_proc, self.c_matrix, self.c_part):
            var.trace_add("write", lambda *_: self._refresh_cycles())

        form = ttk.Frame(t)
        form.pack(fill="x", pady=2)
        self.c_tool = self._combo(form, 0, 0, "Tool", list(self.material_names.values()),
                                  self.material_names["CFRP_BMI"], 24)
        self.c_lam = self._field(form, 0, 2, "Laminate thickness (mm)", 2.0, 6)
        self.c_equip = self._combo(form, 0, 4, "Equipment", ["autoclave", "oven"], "autoclave", 10)
        bar = ttk.Frame(t)
        bar.pack(fill="x", pady=4)
        ttk.Button(bar, text="Plan cure cycle", style="Run.TButton",
                   command=lambda: self._guard(self._run_cure)).pack(side="left")
        ttk.Button(bar, text="Add to comparison",
                   command=lambda: self._guard(self._add_comparison)).pack(side="left", padx=6)
        ttk.Button(bar, text="Clear comparison", command=self._clear_comparison).pack(side="left")
        ttk.Button(bar, text="Export ANSYS table…",
                   command=lambda: self._guard(self._export_ansys)).pack(side="left", padx=6)
        self.c_card = tk.StringVar()
        ttk.Label(t, textvariable=self.c_card, foreground="#1d4f91", wraplength=1100,
                  justify="left").pack(anchor="w")

        self.canvas = tk.Canvas(t, height=330, background="white", highlightthickness=1,
                                highlightbackground="#ccc")
        self.canvas.pack(fill="x", pady=4)
        self.c_out = Output(t, 9)
        self.c_out.pack(fill="both", expand=True)
        self.comparison: list = []
        self._refresh_cycles()

    def _refresh_cycles(self):
        proc, matrix, part = self.c_proc.get(), self.c_matrix.get(), self.c_part.get()
        labels = [lbl for lbl, c in self.cycle_by_label.items()
                  if (proc == "All" or c.process == proc)
                  and (matrix == "All" or matrix.lower() in c.matrix.lower())
                  and (part == "All" or part in c.part_type)]
        self.c_cycle_box["values"] = labels
        if self.c_cycle.get() not in labels:
            current = self.label_by_cycle.get(self.a_cycle_id(), "")
            self.c_cycle.set(current if current in labels else (labels[0] if labels else ""))

    def _selected_cycle(self) -> cp.CureCycle:
        cycle = self.cycle_by_label.get(self.c_cycle.get())
        if cycle is None:
            raise ValueError("No cycle matches the filters — set a filter back to 'All'.")
        return cycle

    def _cure_plan(self, cycle):
        a = self.article()
        tool = next(m for m in self.materials if m.material_id == self.material_ids[self.c_tool.get()])
        first_ramp = next((s for s in cycle.steps if s.kind == "ramp"), None)
        ramp = first_ramp.rate() if first_ramp else a.base_ramp_C_min
        part = ms.PartDefinition(length_m=a.length_m, width_m=a.width_m, cure_temp_C=cycle.peak_C,
                                 cure_pressure_bar=cycle.pressure_max, ramp_rate_C_min=ramp)
        calc = ms.calculate(tool, part)
        plan = cp.plan(cycle, sandwich=a.sandwich, tool_max_service_C=tool.max_service_C,
                       tool_tau_min=calc.tau_min, tool_name=tool.name,
                       laminate_mm=number(self.c_lam, "Laminate thickness", 0.1),
                       equipment=self.c_equip.get())
        return plan, calc

    def _run_cure(self):
        cycle = self._selected_cycle()
        self.plan, calc = self._cure_plan(cycle)
        # The study article follows the planned cycle, so the DOE uses the same cure.
        self.a_cycle.set(self.label_by_cycle[cycle.cycle_id])
        self.a_temp.set(f"{cycle.peak_C:g}")
        text = cp.plan_text(self.plan)
        self.c_out.show(text)
        self.sections["3 Cure cycle (PS2)"] = text
        b = self.plan.band
        vac = "none" if cycle.vacuum_bar is None else f"{cycle.vacuum_bar:g} bar"
        self.c_card.set(
            f"{cycle.product} · {cycle.matrix} · {cycle.process} · {cycle.part_type}  |  "
            f"pressure {cp.pressure_text(cycle)}, vacuum {vac}"
            + (f", vent ≤ {cycle.vent_C:.0f} °C" if cycle.vent_C else "")
            + f"  |  cycle {b['fast']:.0f} / {b['nominal']:.0f} / {b['slow']:.0f} min (fast / nominal / slow)"
            + (f"  |  + post-cure {cp.total_minutes(self.plan.post_points):.0f} min to "
               f"{cycle.post_peak_C:.0f} °C" if self.plan.post_points else "")
            + f"\nSource: {cycle.source} — {cycle.location}")
        self._draw_cycle(self.plan.points, calc.tau_min)
        flagged = sum(1 for w in self.plan.warnings if not w.startswith("Assumption"))
        self.status.set(f"Cure plan: {b['nominal']:.0f} min nominal — {flagged} check(s) to read; "
                        f"study article now uses {cycle.cycle_id} at {cycle.peak_C:.0f} °C.")

    def _add_comparison(self):
        cycle = self._selected_cycle()
        if any(cid == cycle.cycle_id for cid, _, _ in self.comparison):
            return
        if len(self.comparison) >= 4:
            raise ValueError("Up to 4 cycles can be compared — clear the comparison first.")
        plan, _ = self._cure_plan(cycle)
        self.comparison.append((cycle.cycle_id, f"{cycle.product} · {cycle.part_type}", plan.points))
        if self.plan:
            self._draw_cycle(self.plan.points, None)
        else:
            self._draw_cycle(plan.points, None)
        self.status.set(f"Comparing {len(self.comparison)} cycle(s).")

    def _clear_comparison(self):
        self.comparison = []
        if self.plan:
            self._run_cure()

    def _draw_cycle(self, points, tau_min):
        c = self.canvas
        c.delete("all")
        self.update_idletasks()
        w, h = max(c.winfo_width(), 900), 330
        pad_l, pad_r, pad_t = 55, 70, 18
        temp_bottom, strip_top, strip_bottom = 220, 250, 312
        series = [points] + [p for _, _, p in self.comparison]
        t_end = max(s[-1]["t_s"] for s in series)
        t_hi = max(50.0, 50 * (int(max(p["T_C"] for s in series for p in s) * 1.1 / 50) + 1))

        def X(t):
            return pad_l + (w - pad_l - pad_r) * t / t_end

        def Y(T):
            return temp_bottom - (temp_bottom - pad_t) * T / t_hi

        # temperature axes
        c.create_line(pad_l, temp_bottom, w - pad_r, temp_bottom)
        c.create_line(pad_l, pad_t, pad_l, temp_bottom)
        for T in range(0, int(t_hi) + 1, 50 if t_hi <= 250 else 100):
            c.create_text(pad_l - 8, Y(T), text=str(T), anchor="e", font=("Segoe UI", 8))
            c.create_line(pad_l, Y(T), w - pad_r, Y(T), fill="#eee")
        step = 60 if t_end <= 900 * 60 else 120
        for m in range(0, int(t_end / 60) + 1, step):
            c.create_text(X(m * 60), strip_bottom + 10, text=f"{m}", font=("Segoe UI", 8))
            c.create_line(X(m * 60), pad_t, X(m * 60), strip_bottom, fill="#f3f3f3")
        c.create_text(pad_l - 44, pad_t - 6, text="°C", anchor="w", font=("Segoe UI", 8))
        c.create_text(w - pad_r + 6, strip_bottom + 10, text="min", anchor="w", font=("Segoe UI", 8))

        # Legend: one row between the temperature panel and the pressure strip,
        # so it never sits on a curve.
        legend = [(f"planned — air {cp.total_minutes(points):.0f} min", "#c0392b")]
        palette = ["#7f8c8d", "#27ae60", "#8e44ad", "#d35400"]
        for (cid, label, pts), colour in zip(self.comparison, palette):
            line = [v for p in pts for v in (X(p["t_s"]), Y(p["T_C"]))]
            c.create_line(*line, fill=colour, width=1.5)
            legend.append((f"{label} {cp.total_minutes(pts):.0f} min", colour))

        air = [v for p in points for v in (X(p["t_s"]), Y(p["T_C"]))]
        c.create_line(*air, fill="#c0392b", width=2)
        if tau_min:
            tau, dt, T_tool, tool, t = tau_min * 60.0, 30.0, points[0]["T_C"], [], 0.0
            while t <= points[-1]["t_s"]:
                tool.extend((X(t), Y(T_tool)))
                T_tool += (_interp(points, t) - T_tool) * (1 - pow(2.718281828, -dt / tau))
                t += dt
            c.create_line(*tool, fill="#1d4f91", width=2, dash=(5, 3))
            legend.insert(1, (f"tool, lumped τ {tau_min:.1f} min", "#1d4f91"))
        elif not self.comparison:
            legend.insert(1, ("tool curve unavailable (c_p not published)", "#777"))
        x_leg = pad_l
        for text, colour in legend:
            c.create_line(x_leg, temp_bottom + 13, x_leg + 14, temp_bottom + 13, fill=colour, width=2)
            item = c.create_text(x_leg + 18, temp_bottom + 13, text=text, anchor="w", fill=colour,
                                 font=("Segoe UI", 8))
            x_leg = c.bbox(item)[2] + 16

        # pressure / vacuum strip for the planned cycle
        p_hi = max(1.0, max(p["P_bar"] for p in points))
        def YP(v):
            return strip_top + (strip_bottom - strip_top) * (p_hi - v) / (p_hi + 1.0)
        c.create_line(pad_l, YP(0), w - pad_r, YP(0), fill="#bbb")
        c.create_text(pad_l - 8, YP(0), text="0", anchor="e", font=("Segoe UI", 8))
        c.create_text(pad_l - 8, YP(p_hi), text=f"{p_hi:g}", anchor="e", font=("Segoe UI", 8))
        if YP(-1) - YP(0) >= 12:            # skip the label when it would sit on "0"
            c.create_text(pad_l - 8, YP(-1), text="-1", anchor="e", font=("Segoe UI", 8))
        for key, colour, name in (("P_bar", "#27ae60", "pressure (bar g)"), ("V_bar", "#555", "vacuum (bar g)")):
            line = [X(0), YP(points[0][key])]
            for p0, p1 in zip(points, points[1:]):
                line += [X(p0["t_s"]), YP(p1[key]), X(p1["t_s"]), YP(p1[key])]
            c.create_line(*line, fill=colour, width=1.5)
        c.create_text(w - pad_r + 6, YP(p_hi), text="pressure", anchor="w", fill="#27ae60", font=("Segoe UI", 8))
        c.create_text(w - pad_r + 6, YP(-1), text="vacuum", anchor="w", fill="#555", font=("Segoe UI", 8))

    def _export_ansys(self):
        if not self.plan:
            raise ValueError("Plan a cure cycle first.")
        REPORT_DIR.mkdir(exist_ok=True)
        path = filedialog.asksaveasfilename(
            parent=self, initialdir=REPORT_DIR, defaultextension=".csv",
            initialfile=f"ansys_table_{self.plan.cycle.cycle_id}.csv", filetypes=[("CSV", "*.csv")])
        if path:
            cp.write_ansys_table(self.plan.points, Path(path))
            self.status.set(f"Saved ANSYS table: {path}")

    # ------------------------------------------------------------------
    # 4 DOE matrix
    # ------------------------------------------------------------------

    def _doe_tab(self):
        t = self._tab("4 · DOE matrix")
        hint(t, "Master Report Table 1 variables at two levels. Tick the factors to vary (the "
                "Project tab's scoping question pre-selects them), set replicates (≥3 panels per "
                "condition), then generate. Each run lists the engine's predictions; the blank "
                "'measured_' columns are for CMM / 3D-scan results.").pack(anchor="w")
        grid = ttk.LabelFrame(t, text="Factors (two levels each)", padding=8)
        grid.pack(fill="x", pady=6)
        for col, head in enumerate(["Vary", "Factor", "Problem", "Low level", "High level", "Note"]):
            ttk.Label(grid, text=head, style="Head.TLabel").grid(row=0, column=col, sticky="w", padx=4)
        self.doe_vars = {}
        tool_names = list(self.material_names.values())
        for i, f in enumerate(doe.default_factors(), 1):
            on = tk.BooleanVar(value=f.key in doe.FOCUS_PRESETS["process"])
            ttk.Checkbutton(grid, variable=on).grid(row=i, column=0)
            ttk.Label(grid, text=f.label).grid(row=i, column=1, sticky="w", padx=4)
            ttk.Label(grid, text=f.problem).grid(row=i, column=2, sticky="w", padx=4)
            low, high = tk.StringVar(value=str(f.low)), tk.StringVar(value=str(f.high))
            if f.key == "tool":
                low.set(self.material_names[f.low])
                high.set(self.material_names[f.high])
                ttk.Combobox(grid, textvariable=low, values=tool_names, width=24, state="readonly").grid(row=i, column=3, padx=4)
                ttk.Combobox(grid, textvariable=high, values=tool_names, width=24, state="readonly").grid(row=i, column=4, padx=4)
            elif f.key in ("layup", "geometry"):
                ttk.Label(grid, text=str(f.low)).grid(row=i, column=3, sticky="w", padx=4)
                ttk.Label(grid, text=str(f.high)).grid(row=i, column=4, sticky="w", padx=4)
            else:
                ttk.Entry(grid, textvariable=low, width=10).grid(row=i, column=3, sticky="w", padx=4)
                ttk.Entry(grid, textvariable=high, width=10).grid(row=i, column=4, sticky="w", padx=4)
            ttk.Label(grid, text=f.note, foreground="#555", wraplength=330).grid(row=i, column=5, sticky="w", padx=4)
            self.doe_vars[f.key] = (on, low, high, f)

        opts = ttk.Frame(t)
        opts.pack(fill="x")
        self.d_reps = self._field(opts, 0, 0, "Panels per condition", 3, 5)
        self.d_half = self._check(opts, 0, 2, "Half fraction (halves the runs)", False)
        self.d_rand = self._check(opts, 0, 4, "Randomise run order", True)
        ttk.Button(opts, text="Generate test matrix", style="Run.TButton",
                   command=lambda: self._guard(self._run_doe)).grid(row=1, column=0, pady=6, sticky="w")
        ttk.Button(opts, text="Export matrix CSV…",
                   command=lambda: self._guard(self._export_doe)).grid(row=1, column=1, sticky="w")
        ttk.Button(opts, text="Analyse measured results…",
                   command=lambda: self._guard(self._analyse_doe)).grid(row=1, column=2, sticky="w")
        self.d_summary = tk.StringVar()
        ttk.Label(opts, textvariable=self.d_summary, foreground="#1d4f91").grid(row=1, column=3, columnspan=3, sticky="w")

        frame, self.d_tree = table(t, ("Order", "Run", "Settings", "δ mm", "Lag °C", "Cycle min",
                                       "Spring-in °", "Warnings"),
                                   (50, 70, 360, 60, 60, 75, 75, 380), 10)
        frame.pack(fill="both", expand=True, pady=4)

    def _apply_focus(self):
        chosen = doe.FOCUS_PRESETS[self.focus.get()]
        for key, (on, *_rest) in self.doe_vars.items():
            on.set(key in chosen)
        self.status.set(f"DOE factors set for '{self.focus.get()}' study: {', '.join(chosen)}.")

    def _setting_text(self, key, value) -> str:
        if key == "tool":
            return self.material_names.get(value, value)
        units = {"pressure": " bar", "ramp": " °C/min", "dwell": " min", "thickness": " mm"}
        if key in units:
            return f"{float(value):g}{units[key]}"
        return str(value)

    def _factors(self):
        factors = []
        for key, (on, low, high, f) in self.doe_vars.items():
            if not on.get():
                continue
            if key == "tool":
                lo, hi = self.material_ids[low.get()], self.material_ids[high.get()]
            elif key in ("layup", "geometry"):
                lo, hi = low.get(), high.get()
            else:
                lo = number(low, f"{f.label} low", 0)
                hi = number(high, f"{f.label} high", 0)
            if lo == hi:
                raise ValueError(f"'{f.label}' has the same low and high level.")
            factors.append(doe.Factor(f.key, f.label, f.problem, lo, hi, f.note))
        if not factors:
            raise ValueError("Tick at least one factor to vary.")
        return factors

    def _run_doe(self):
        reps = int(number(self.d_reps, "Panels per condition", 1))
        self.doe_factors = self._factors()
        art = self.article()
        self.runs = doe.build_matrix(art, self.doe_factors, reps, self.d_half.get(), self.d_rand.get())
        rows = []
        for i, r in enumerate(self.runs, 1):
            settings = ", ".join(self._setting_text(f.key, r.settings[f.key]) for f in self.doe_factors)
            p = r.predictions
            rows.append((i, r.run_id, settings, p["pred_cte_mismatch_mm"],
                         "n/a" if p["pred_tool_lag_C"] is None else p["pred_tool_lag_C"],
                         p["pred_cycle_min"],
                         "-" if p["pred_corner_spring_in_deg"] is None else p["pred_corner_spring_in_deg"],
                         "; ".join(r.warnings)))
        fill(self.d_tree, rows)
        conditions = len({r.std_order for r in self.runs})
        cost = doe.study_cost(art, self.runs)
        self.d_summary.set(f"{conditions} conditions × {reps} = {len(self.runs)} panels | "
                           f"study ₹{ce.inr(cost['total'][0])}–{ce.inr(cost['total'][1])}")
        if reps < 3:
            messagebox.showinfo("Replication", "The Master Report recommends at least 3 panels per "
                                               "condition (5 improves the ANOVA).", parent=self)
        self.sections["4 DOE matrix"] = self._doe_text(cost)
        self._run_cost()
        self.status.set(f"DOE: {conditions} conditions, {len(self.runs)} panels — cost tab updated.")

    def _doe_text(self, cost):
        lines = [f"Factors: " + "; ".join(f"{f.label} ({f.problem}) {f.low} / {f.high}" for f in self.doe_factors),
                 f"Design: {'half fraction' if self.d_half.get() else 'full factorial'}, "
                 f"{len({r.std_order for r in self.runs})} conditions, {len(self.runs)} panels",
                 "", "Predicted per condition:"]
        seen = set()
        for r in sorted(self.runs, key=lambda r: r.std_order):
            if r.std_order in seen:
                continue
            seen.add(r.std_order)
            s = ", ".join(self._setting_text(f.key, r.settings[f.key]) for f in self.doe_factors)
            p = r.predictions
            lines.append(f"  C{r.std_order:02d} {s} → δ {p['pred_cte_mismatch_mm']} mm, cycle "
                         f"{p['pred_cycle_min']} min" + (f", spring-in {p['pred_corner_spring_in_deg']}°"
                                                         if p["pred_corner_spring_in_deg"] else "")
                         + (f"  [{'; '.join(r.warnings)}]" if r.warnings else ""))
        lines.append(f"\nStudy cost: moulds ₹{ce.inr(cost['mould'][0])}–{ce.inr(cost['mould'][1])} + "
                     f"{cost['panels']} panels ₹{ce.inr(cost['consumables'][0])}–{ce.inr(cost['consumables'][1])}")
        return "\n".join(lines)

    def _export_doe(self):
        if not self.runs:
            raise ValueError("Generate the test matrix first.")
        REPORT_DIR.mkdir(exist_ok=True)
        path = filedialog.asksaveasfilename(parent=self, initialdir=REPORT_DIR, defaultextension=".csv",
                                            initialfile="doe_test_matrix.csv", filetypes=[("CSV", "*.csv")])
        if path:
            doe.write_csv(self.runs, self.doe_factors, Path(path))
            self.status.set(f"Saved DOE matrix: {path} — fill the measured_ columns after inspection.")

    def _analyse_doe(self):
        path = filedialog.askopenfilename(parent=self, initialdir=REPORT_DIR,
                                          filetypes=[("CSV", "*.csv")], title="DOE matrix with measured results")
        if not path:
            return
        lines = ["MAIN EFFECTS (mean at high level − mean at low level)"]
        for response in doe.MEASURED_COLUMNS:
            try:
                res = doe.analyse_main_effects(Path(path), response)
            except ValueError:
                continue
            lines.append(f"\n{response}  (n = {res['n']}, replicate SD = {res['pooled_sd']:.3f})")
            for k, e in res["effects"].items():
                flag = "  ← likely significant" if abs(e["t_ratio"]) > 2.5 else ""
                lines.append(f"  {k:<10} effect {e['effect']:+.3f} (low {e['mean_low']:.3f}, "
                             f"high {e['mean_high']:.3f}), t ≈ {e['t_ratio']:.1f}{flag}")
        if len(lines) == 1:
            raise ValueError("No measured_ column has at least 4 values yet.")
        lines.append("\nConfirm with a full ANOVA including interactions (Master Report §3.5).")
        text = "\n".join(lines)
        self.sections["4b DOE analysis"] = text
        messagebox.showinfo("DOE analysis", text, parent=self)

    # ------------------------------------------------------------------
    # 5 Cost
    # ------------------------------------------------------------------

    def _cost_tab(self):
        t = self._tab("5 · Cost (₹)")
        hint(t, "Process consumables for one panel (project BOM, scaled by area / perimeter / per "
                "panel) and the cost of the DOE study. Figures are indicative — re-quote with two "
                "suppliers (Master Report §5.6).").pack(anchor="w")
        ttk.Button(t, text="Update cost", style="Run.TButton",
                   command=lambda: self._guard(self._run_cost)).pack(anchor="w", pady=6)
        frame, self.k_tree = table(t, ("Item", "₹ low", "₹ high", "Basis"), (260, 90, 90, 520), 12)
        frame.pack(fill="x")
        self.k_out = Output(t, 12)
        self.k_out.pack(fill="both", expand=True, pady=6)

    def _run_cost(self):
        a = self.article()
        lines = ce.panel_bom(a.length_m, a.width_m, a.sandwich)
        fill(self.k_tree, [(l.item, ce.inr(l.low), ce.inr(l.high), l.basis) for l in lines])
        low, high = ce.total(lines)
        out = [f"Consumables per panel: ₹{ce.inr(low)} – ₹{ce.inr(high)}"]
        if self.runs:
            cost = doe.study_cost(a, self.runs)
            out += ["", "THIS DOE STUDY",
                    f"  Tools: {', '.join(self.material_names[t] for t in cost['tools'])}",
                    f"  Moulds ₹{ce.inr(cost['mould'][0])}–{ce.inr(cost['mould'][1])} "
                    f"+ {cost['panels']} panels ₹{ce.inr(cost['consumables'][0])}–{ce.inr(cost['consumables'][1])}",
                    f"  Total ₹{ce.inr(cost['total'][0])}–{ce.inr(cost['total'][1])}"]
            if cost["unpriced_tools"]:
                out.append(f"  No ₹ data for: {', '.join(cost['unpriced_tools'])}")
            if "STEEL_MILD" in cost["tools"]:
                out.append("  ! Mild steel ₹3k–13k is UNVERIFIED — see docs/DATA_ISSUES.md")
        out += ["", "MASTER REPORT SCENARIOS (3 panels × 2 conditions)"]
        for name, moulds in ce.MASTER_SCENARIOS.items():
            s = ce.study_cost(moulds, 3, a.length_m, a.width_m, a.sandwich, name)
            out.append(f"  {name:<16} {' + '.join(moulds):<40} total ₹{ce.inr(s.total[0])}–{ce.inr(s.total[1])}")
        text = "\n".join(out)
        self.k_out.show(text)
        self.sections["5 Cost"] = text

    # ------------------------------------------------------------------
    # 6 Report
    # ------------------------------------------------------------------

    def _report_tab(self):
        t = self._tab("6 · Report")
        hint(t, "Collects every step you have run into one document for the project report.").pack(anchor="w")
        bar = ttk.Frame(t)
        bar.pack(fill="x", pady=6)
        ttk.Button(bar, text="Build report", style="Run.TButton",
                   command=lambda: self._guard(self._build_report)).pack(side="left")
        ttk.Button(bar, text="Save report…", command=lambda: self._guard(self._save_report)).pack(side="left", padx=8)
        self.r_out = Output(t, 30)
        self.r_out.pack(fill="both", expand=True)

    def report_text(self) -> str:
        a = self.article()
        head = [
            "DESIGN AND PROCESS STUDY OF AUTOCLAVE-CURED PREPREG COMPOSITES — DECISION REPORT",
            f"Generated {datetime.now():%d %b %Y %H:%M}",
            "",
            f"Study article: {a.length_m} × {a.width_m} m {'honeycomb sandwich' if a.sandwich else 'monolithic'} "
            f"panel, cure {a.cure_temp_C:.0f} °C at {a.base_pressure_bar:g} bar, ramp {a.base_ramp_C_min:g} °C/min, "
            f"cycle {a.cycle_id}",
            f"Study focus (§2.4): {self.focus.get()}",
        ]
        order = ["0 Prepreg selection", "1 Material system", "2 Tooling (PS1)", "3 Cure cycle (PS2)", "4 DOE matrix",
                 "4b DOE analysis", "5 Cost"]
        body = []
        for key in order:
            if key in self.sections:
                body += ["", "=" * 78, key.upper(), "=" * 78, self.sections[key]]
        missing = [k for k in order if k not in self.sections and k != "4b DOE analysis"]
        if missing:
            body += ["", f"Not yet run: {', '.join(missing)}"]
        body += ["", "Limitations: the tool ranks and estimates; it does not replace FEM (ANSYS "
                     "ACP/ACCS) distortion prediction, supplier qualification or trial panels."]
        return "\n".join(head + body)

    def _build_report(self):
        self.r_out.show(self.report_text())
        self.status.set("Report built — use Save report to keep it.")

    def _save_report(self):
        REPORT_DIR.mkdir(exist_ok=True)
        path = filedialog.asksaveasfilename(
            parent=self, initialdir=REPORT_DIR, defaultextension=".txt",
            initialfile=f"study_report_{datetime.now():%Y%m%d_%H%M}.txt",
            filetypes=[("Text", "*.txt"), ("Markdown", "*.md")])
        if path:
            Path(path).write_text(self.report_text(), encoding="utf-8")
            self.status.set(f"Saved report: {path}")


def _interp(points, t):
    for p0, p1 in zip(points, points[1:]):
        if p0["t_s"] <= t <= p1["t_s"]:
            span = p1["t_s"] - p0["t_s"]
            return p0["T_C"] if span == 0 else p0["T_C"] + (p1["T_C"] - p0["T_C"]) * (t - p0["t_s"]) / span
    return points[-1]["T_C"]


def main():
    app = StudyApp()
    app.mainloop()


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    main()
