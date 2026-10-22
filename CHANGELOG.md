# Changelog

## v5.3 — documented cure-cycle library

### Added
- **30 cure cycles** (was 5, mostly M18/1) from Hexcel 8552 (EU/US), M21
  (thin/thick/sandwich), 913, M56 (oven, OOA), M18/1, HexTool M61, the NCAMP
  5320-1 process specification, 13 MIL-HDBK-17-2F processing lines (epoxies,
  BMIs with post-cure, cyanate ester, APC-2 PEEK, polyimide, vacuum-bag
  adhesive) and the EC out-of-autoclave guide — `process_data/SOURCES.md`.
- **Richer step model**: ramp-rate and hold-time *ranges*, pressure and
  vacuum per step (staged pressure, vacuum vents, late pressure on M21
  sandwich), pre-cure vacuum holds, free-standing post-cures, vent
  temperature, documented pressure window; every unstated value flagged.
- **Planner**: cycle-time band (fast / nominal / slow), post-cure time,
  checks for oven-vs-autoclave equipment, sandwich on a monolithic cycle,
  laminate thickness vs a thin-part cycle, 913 exotherm dwell, tool rating,
  assumptions; ANSYS table now carries pressure and vacuum columns.
- **Cure tab**: filter by process / matrix / part type, readable cycle names,
  details card, pressure-vacuum strip under the temperature chart, compare up
  to 4 cycles; planning a cycle sets the study article's cycle and cure
  temperature so the DOE follows it.
- 9 tests (72 total).

## v5.1 — project-centred desktop tool

### Added
- **Desktop window** (`project_gui.py`, launched by `run.bat`): tabs follow the
  Master Report methodology — Project (study article, PS1–PS3, §2.4 scoping
  question), Material system (+ HexPly M18/1 reference card), Tooling (PS1),
  Cure cycle (PS2) with an air-vs-tool temperature chart, DOE matrix, Cost,
  Report. Study article preloaded; input errors shown as dialogs; friendly
  tool names; unverified costs marked ⚠.
- **DOE builder** (`doe.py`): Master Report Table 1 factors at two levels,
  full factorial or half fraction, replication, randomised order, predicted
  δ / tool lag / cycle time / corner spring-in per run, study ₹ cost, CSV
  export with blank measured columns, and main-effects analysis of measured
  results (effect and t-ratio against replicate scatter).
- 11 tests (63 total), including the window driven end to end.

### Data issues found
- Master Report Table 1 pressure levels (4 / 6 bar) exceed the M18/1
  sandwich-cycle limit (2 bar) for the honeycomb study article — DOE runs
  are warned (docs/DATA_ISSUES.md).

## v5.0 — finalised decision tool (built from the project documents)

### Added
- **`app.py` + `run.bat`**: one menu program — fiber recommender, mold
  selector, cure planner, BOM/cost, full project report (saved to
  `reports/`), validation cases, data sources. Defaults on Enter, re-asks
  invalid input.
- **Mold (tool) material selector** (`mold_selector.py`, `ahp.py`) per the
  *Matrix Engine Report*: feasibility gate with rejection reasons, CTE
  mismatch δ (Invar temperature-dependent CTE), thermal lag from measured
  autoclave HTCs (Fisher et al. 2022), tool mass, cycle life, ₹ cost, corner
  spring-in compensation (Albert & Fernlund 2002), three AHP profiles, ±20 %
  weight sweep with close-call flag, DOE low/high-CTE pairing, report card.
- **Tool-material database (D1)** `tooling_data/tool_materials.csv`: 9
  materials, every value sourced (`tooling_data/SOURCES.md`).
- **Validation set (D6)** `validation_cases.py`: 6 documented industry
  choices, all reproduced.
- **Cure-cycle planner** (`cure_planner.py`): documented cycles only,
  reproduces the project ANSYS calculation, tool-lag hold extension,
  sandwich-pressure and tool-temperature checks, ANSYS table export.
- **BOM & cost estimator** (`cost_estimator.py`): project BOM rows scaled by
  area/perimeter/panel, DOE scenarios, Indian number formatting.
- **MIL-HDBK-17-2F lamina data**: 11 measured systems (AS4, T300, IM6, M55J;
  epoxy, BMI, PEEK, cyanate ester) → lamina model now 27 points, modulus R²
  0.96, valid to 540 GPa.
- `docs/DATA_ISSUES.md`: arithmetic slips and gaps found in the project
  documents; 23 new tests (52 total).

### Fixed
- Lamina evaluator Spearman correlations misaligned rows by index after the
  dataset grew (ILSS showed −0.60 instead of +0.12).

### Tuned
- Weight-learning rate 0.3 → **3.0** (`LEARN_RATE`). A 100-trial sweep of
  learning rate (0.3 / 1 / 3) × L2 (0.05 / 0.01 / 0.001), confirmed on 100
  fresh trials, gave identical metrics for every rate; 3.0 converges in ~100
  instead of ~1600 iterations (100-trial evaluation 13 s → 1.8 s). L2 stays
  0.05: lower values only trade aerospace AUC (+0.03) for worse industrial
  AUC and RMSE. Accuracy cannot rise above the label base rate (aerospace
  0.80) with manufacturer-use labels — see docs/RESULTS.md.

## v4.2 — findings from a 1000-run random stress test

### Fixed
- "No results" diagnostics now find the smallest *combination* of HARD
  limits that conflicts (e.g. modulus ≥ 459 GPa + density ≤ 1.84 g/cm³),
  explain certification-caused empties, and name the closest fiber and its
  shortfall. Previously 8.6 % of runs ended with "All HARD constraints have at
  least one qualifying candidate" and no explanation.
- Equal scores are ordered by fixed tie-breakers (engineering score, data
  completeness, name) and labelled "(tied with #n)" for fibers, prepregs and
  resins; rankings are repeatable.
- Process and matrix menus show how many prepregs / resins the database holds
  for each option and warn when there are none; empty prepreg/resin lists
  explain why (e.g. "RTM uses liquid resin, not prepreg").
- Lamina estimates outside the calibrated fiber range (24 high-modulus and
  pitch fibers) are withheld instead of shown as an extrapolated number.
- "Certification: nan" / "Qualification: nan" now read "Not stated".
- Diagnostics no longer crash with UnicodeEncodeError when output is
  redirected on Windows (cp1252).

### Performance
- Weight learning loop ~1.8× faster with bit-identical results.

Changes relative to the original upload (`rohv1713-sudo/ProductRecommendationAI`,
commit `7d92b84`). Work focuses on v4; v1, v2, v5, v6 and `recommendv2.py`
are unchanged.

## v4.1

### Added
- **AHP weights** with a consistency check (CR < 0.10) for all application
  presets; custom mode asks the six pairwise comparisons and re-asks
  inconsistent ones.
- **Lamina estimator** (`lamina_estimator.py`): shows published 0° UD lamina
  properties per fiber (NCAMP preferred), or a calibrated estimate flagged when
  extrapolated.
- **Literature dataset** (`literature_data/`): 16 cited fiber/lamina pairs from
  NCAMP reports and Toray/Hexcel datasheets, plus MCDM literature weights.
- **Evaluation**: `evaluate_weights.py` (100-trial weight evaluation/learning,
  weak labels or expert ratings) and `evaluate_lamina_model.py` (LOO-CV,
  bootstrap CIs).
- **Expert rating workflow**: `make_expert_template.py`,
  `expert_ratings_template.csv`, `EXPERT_RATING_GUIDE.md`.
- Data-completeness column; unit tests (`tests/`); `requirements.txt`; docs.

### Data
- `sizing_compatibility` filled for 13 Toray grades (T300, T700S, T700G,
  T800H, T800S, T1000G, T1100S, T1100G, M35J, M40J, M46J, M55J, M60J) from
  each grade's official Toray data sheet, with revision and URL recorded in
  `source_file` / `source_url`.

### Fixed
- Fibers with missing properties were averaged over known values only — a
  fiber with only a density value scored a perfect engineering 100 (HexTow 85
  ranked #10; now #77). Unpublished properties now score 0.
- Epoxy sizing check matched the letter "g" anywhere ("sizing types 4, 5"),
  giving 19 fibers a false bonus; it now requires a GP/GS/G sizing code.
- Prepreg fiber matching used substrings ("AS4" matched "AS4C") over a zip of
  two unordered sets; now exact grade tokens.
- Process fit: only 2 of 7 processes reached a branch, the rest got a flat 70;
  resin-driven processes are now neutral for fibers.
- Text aliases match whole words ("pa" no longer matches "capable").
- Invalid menu choices silently became "no preference"; `nan`/`inf` were
  accepted as numbers; EOF crashed with a traceback.

### Performance
- Weight evaluation 37× faster (Newton's method for calibration, early
  stopping for learning) with identical results.
