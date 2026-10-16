# Changelog

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
- `sizing_compatibility` filled for 14 Toray grades (T300, T700S, T700G,
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
