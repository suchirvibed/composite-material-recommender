# Autoclave Prepreg Composite Decision Tool

A working decision tool for the project *Design and Process Study of
Autoclave-Cured Prepreg Composites*. One menu program covers the project's
three decisions, using sourced data throughout:

| # | Module | What it answers | Project basis |
|---|---|---|---|
| 1 | Fiber & prepreg recommender | Which fiber / prepreg / resin system? | AHP-weighted MCDM over the fiber, prepreg and resin databases |
| 2 | Mold (tool) material selector | Which tool material, and why? | *Matrix Engine Report* — feasibility gate, CTE-mismatch physics, AHP profiles, sensitivity sweep, report card |
| 3 | Cure-cycle planner | What cycle, how long, does the tool keep up? | HexPly M18/1 datasheet cycles, *ANSYS thermal cycle calculation*, Fisher et al. measured HTCs |
| 4 | BOM & cost estimator | What does the DOE study cost (₹)? | *Autoclave Prepreg process BOM and cost*, Master Report Table 6 |
| 5 | Full project report | All of 2–4 for one part, saved to `reports/` | — |
| 6 | Validation cases (D6) | Does the engine reproduce accepted industry choices? | Tooling report, Master Report |

It ranks and estimates; it does **not** replace FEM (ANSYS ACP/ACCS) distortion
prediction, supplier qualification or trial parts.

## Run it

```bash
py -m pip install -r requirements.txt
py app.py
```

or double-click **`run.bat`**. Every prompt shows a default in `[brackets]` —
press Enter to accept it (defaults describe the project's 1 m² carbon/epoxy
honeycomb panel). Invalid input is re-asked, never silently accepted.

```bash
py -m unittest discover -s tests -v     # 52 tests
py validation_cases.py                  # D6 validation set (6/6 pass)
py evaluate_lamina_model.py 100         # lamina model validation
py evaluate_weights.py 100              # fiber weight evaluation
```

## Mold selector in one paragraph

Each tool material is first **gated** (service temperature ≥ cure + 20 °C,
cycle life, cost ceiling, hard tolerance, Class-A surface, autoclave envelope)
with the reason for every rejection. Survivors get physics indices — CTE
mismatch error δ = |α_tool − α_part|·ΔT·L (Invar uses its temperature-dependent
CTE curve), thermal lag τ = ρ·c_p·t/h with h from measured autoclave HTCs,
tool mass, cycle life and ₹ cost — which are min-max normalised and weighted by
one of three AHP-derived profiles (prototype, production, aerospace). A ±20 %
weight sweep flags close calls. Unpublished values score as "not demonstrated".

## Files

| Path | Contents |
|---|---|
| `app.py`, `run.bat` | Menu program and launcher |
| `updated_database_recommender_v4.py` | Fiber/prepreg/resin recommender |
| `mold_selector.py`, `ahp.py` | Mold selection engine, generic AHP |
| `cure_planner.py`, `cost_estimator.py` | Process planning and costing |
| `validation_cases.py` | D6 validation set |
| `lamina_estimator.py` | Fiber → UD lamina estimate (27 published pairs) |
| `tooling_data/` | Tool-material database (D1) + `SOURCES.md` |
| `process_data/` | Cure cycles, BOM consumables, mould cost options |
| `literature_data/` | NCAMP, MIL-HDBK-17, Toray, Hexcel lamina data + `SOURCES.md` |
| `*.csv` (root) | Fiber, prepreg, resin, compatibility, simulation master databases |
| `docs/` | `METHODOLOGY.md`, `RESULTS.md`, `DATA_ISSUES.md` |
| `tests/` | Unit tests |

## Documentation

- [docs/METHODOLOGY.md](docs/METHODOLOGY.md) — the theory behind every module
- [docs/RESULTS.md](docs/RESULTS.md) — validation numbers
- [docs/DATA_ISSUES.md](docs/DATA_ISSUES.md) — inconsistencies found in the project documents and data gaps to close
- [CHANGELOG.md](CHANGELOG.md), [EXPERT_RATING_GUIDE.md](EXPERT_RATING_GUIDE.md)
- Sources: [tooling_data/SOURCES.md](tooling_data/SOURCES.md), [literature_data/SOURCES.md](literature_data/SOURCES.md)

## Data and disclaimer

Material properties are typical values from public manufacturer datasheets,
NCAMP reports and MIL-HDBK-17-2F; costs are indicative ₹ figures from the
project BOM document. Typical values are not design allowables. Trademarks
belong to their owners; this project is not affiliated with any manufacturer.

## Credits

Original databases and recommender versions v1–v6 by
[rohv1713-sudo](https://github.com/rohv1713-sudo/ProductRecommendationAI).
No license is granted yet: all rights reserved by the authors.
