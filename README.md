# Composite Material Recommendation Engine (v4)

Recommends carbon fibers, prepregs and resins for an application from
manufacturer databases, with traceable sources. It is a rule-based
multi-criteria decision model (weighted sum), with weights derived by AHP.
It recommends candidates — it does not replace engineering qualification.

## Quick start

```bash
py -m pip install -r requirements.txt
py updated_database_recommender_v4.py          # interactive recommender
py -m unittest discover -s tests -v            # 24 unit tests
```

## How it works

1. **Load** the fiber, prepreg and resin CSV databases.
2. **Inputs**: application, minimum strength / modulus / elongation, maximum
   density (each HARD or PREFERRED), process, matrix, certification.
3. **Weights** come from AHP pairwise judgments per application
   (`APPLICATIONS`), checked for consistency (CR < 0.10). Custom mode asks the
   six pairwise questions and re-asks if they contradict each other.
4. **Hard filter** removes fibers that fail a HARD limit; if none survive,
   diagnostics explain which limit eliminated everyone.
5. **Score** 0-100: 70 % engineering (property ratio vs target, AHP-weighted;
   unpublished properties score 0) + application, grade, process, matrix and
   certification fit.
6. **Output**: top fibers with UD lamina properties (published where
   available, NCAMP preferred; otherwise a calibrated estimate), then
   independently ranked prepregs and resins.

## Files

| File | Purpose |
|---|---|
| `updated_database_recommender_v4.py` | The engine (CLI) |
| `lamina_estimator.py` | Fiber → 0° UD lamina estimate, calibrated on published data |
| `literature_data/` | Cited lamina data (NCAMP + datasheets), MCDM literature weights, `SOURCES.md` |
| `evaluate_weights.py` | 100-trial weight evaluation/learning (`--expert` for expert ratings) |
| `evaluate_lamina_model.py` | LOO-CV + bootstrap validation of the lamina estimator |
| `make_expert_template.py` / `EXPERT_RATING_GUIDE.md` | Blind expert-rating sheet for learning weights |
| `tests/test_engine.py` | Unit tests |
| `updated_database_recommender_v1/v2/v5/v6.py`, `recommendv2.py` | Earlier/other versions (not maintained here) |

## Documentation

- [docs/METHODOLOGY.md](docs/METHODOLOGY.md) — pipeline, AHP math, scoring, lamina model, limitations
- [docs/RESULTS.md](docs/RESULTS.md) — validation numbers (RMSE, MAPE, R², AUC, NDCG)
- [CHANGELOG.md](CHANGELOG.md) — what changed from the original upload, including bug fixes
- [literature_data/SOURCES.md](literature_data/SOURCES.md) — every external number and where it came from
- [EXPERT_RATING_GUIDE.md](EXPERT_RATING_GUIDE.md) — how to produce expert labels for weight learning

## Data and disclaimer

Material properties are typical values transcribed from public manufacturer
datasheets (Hexcel, Toray, Teijin, SGL) and NCAMP qualification reports; each
row keeps its source. Typical values are not design allowables. Trademarks
belong to their owners. This project is not affiliated with any manufacturer.

## Credits

Original databases and recommender versions v1–v6 by
[rohv1713-sudo](https://github.com/rohv1713-sudo/ProductRecommendationAI).
v4.1 extensions (AHP, lamina estimator, evaluation, fixes) are listed in the
changelog.

No license is granted yet: all rights reserved by the authors.

## Validation commands

```bash
py evaluate_lamina_model.py 100                  # lamina model: RMSE, MAPE, R², bootstrap CIs
py evaluate_weights.py 100                       # weights vs manufacturer-use labels
py evaluate_weights.py 100 --expert expert_ratings.csv   # once expert ratings exist
```
