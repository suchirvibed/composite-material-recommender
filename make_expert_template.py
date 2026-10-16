"""
Generate the expert-rating template used to learn v4 importance weights.

Why
---
Manufacturer "intended use" text is too weak a label to learn weights from
(see evaluate_weights.py). This script produces a blind rating sheet that a
materials expert fills in by hand; evaluate_weights.py --expert then learns
weights from those ratings and reports MSE / RMSE / ranking metrics.

Design
------
- 20 scenarios = 5 applications x 4 requirement sets. Targets are drawn
  from the database's own 25th-75th percentiles and rounded to values an
  engineer would actually write down.
- Each scenario shortlists 6 fibers: v4's top 3 (AHP weights) plus 3 others
  drawn at random, so the sheet contains both good and mediocre options.
- Order within a scenario is shuffled and NO v4 scores are shown, so the
  expert isn't anchored by the model they are evaluating.

The expert fills `expert_rating` (1-5) for every row, and optionally
`confidence` and `notes`. Leave a row blank to skip it.

Usage:
    py make_expert_template.py            # writes expert_ratings_template.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import updated_database_recommender_v4 as v4  # noqa: E402
from evaluate_weights import PROPERTY_COLUMNS, component_matrix, load_fibers  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
OUTPUT = BASE_DIR / "expert_ratings_template.csv"
SEED = 7
SCENARIOS_PER_APPLICATION = 4
TOP_FROM_MODEL = 3
RANDOM_OTHERS = 3

# Rounding step per property, so targets read like real requirements.
ROUND_TO = {"strength": 50, "modulus": 5, "density": 0.01, "elongation": 0.1}

APPLICATIONS = {k: v for k, v in v4.APPLICATIONS.items() if v["ahp_judgments"]}


def rounded_targets(fibers: pd.DataFrame, rng: np.random.Generator) -> dict:
    targets = {}
    for name, col in PROPERTY_COLUMNS.items():
        lo, hi = np.percentile(fibers[col], [25, 75])
        step = ROUND_TO[name]
        targets[name] = round(round(rng.uniform(lo, hi) / step) * step, 2)
    return targets


def build_template() -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    fibers = load_fibers()
    rows = []
    scenario = 0

    for key, app in APPLICATIONS.items():
        weights = v4.ahp_weights(app["ahp_judgments"]).weights
        w = np.array([weights[c] for c in v4.CRITERIA])

        for _ in range(SCENARIOS_PER_APPLICATION):
            scenario += 1
            targets = rounded_targets(fibers, rng)
            score = component_matrix(fibers, targets) @ w

            top = list(np.argsort(-score, kind="stable")[:TOP_FROM_MODEL])
            rest = [i for i in range(len(fibers)) if i not in top]
            others = list(rng.choice(rest, size=RANDOM_OTHERS, replace=False))
            shortlist = rng.permutation(top + others)

            for idx in shortlist:
                f = fibers.iloc[int(idx)]
                rows.append({
                    "scenario_id": f"S{scenario:02d}",
                    "application": app["name"],
                    "target_min_strength_mpa": targets["strength"],
                    "target_min_modulus_gpa": targets["modulus"],
                    "target_max_density_g_cm3": targets["density"],
                    "target_min_elongation_percent": targets["elongation"],
                    "fiber_id": f["fiber_id"],
                    "manufacturer": f["manufacturer"],
                    "product": f["product"],
                    "fiber_class": f.get("fiber_class", ""),
                    "strength_mpa": f["tensile_strength_mpa"],
                    "modulus_gpa": f["tensile_modulus_gpa"],
                    "density_g_cm3": f["fiber_density_g_cm3"],
                    "elongation_percent": f["ultimate_elongation_percent"],
                    "expert_rating": "",
                    "confidence": "",
                    "notes": "",
                })

    return pd.DataFrame(rows)


def main() -> None:
    template = build_template()
    template.to_csv(OUTPUT, index=False)
    print(f"Saved {OUTPUT.name}: {template['scenario_id'].nunique()} scenarios, "
          f"{len(template)} fibers to rate.")
    print("Fill expert_rating with 1-5 (5 = excellent choice for this scenario, "
          "1 = unsuitable). See EXPERT_RATING_GUIDE.md.")


if __name__ == "__main__":
    main()
