# Expert rating guide

`expert_ratings_template.csv` holds **20 scenarios × 6 carbon fibers = 120 rows**.
Your ratings become the ground truth used to learn and test the v4 importance
weights (`py evaluate_weights.py --expert expert_ratings.csv`).

## How to fill it in

1. Save a copy as `expert_ratings.csv` (keep the template untouched).
2. For each row, read the scenario (application + target columns) and the
   fiber's properties, then fill **`expert_rating`**:

   | Rating | Meaning |
   |---|---|
   | 5 | Excellent — would specify this fiber for the scenario |
   | 4 | Good — a sound choice with minor compromises |
   | 3 | Acceptable — works, but clearly better options exist |
   | 2 | Poor — significant shortfall on an important property |
   | 1 | Unsuitable — would not use it |

3. Optional: `confidence` (1 = guess, 3 = sure) and `notes`.
4. Leave `expert_rating` blank if you can't judge a row — it is skipped.

## Rules that keep the data honest

- **Rate each fiber against its own scenario.** The same fiber can be a 5 in one
  scenario and a 2 in another.
- **Use your engineering judgment, not the v4 output.** The sheet is deliberately
  blind: no model scores, shuffled order. Don't run the recommender first.
- **Targets are guidance, not hard limits.** A fiber slightly under a target can
  still be a good choice if it excels elsewhere — rate it that way.
- **Only the four listed properties are in scope** (strength, modulus, density,
  elongation, plus fiber class). Ignore price and availability unless you note it.
- **One rater per file.** If several people rate, save one file each
  (`expert_ratings_<name>.csv`) so agreement between raters can be checked later.

## What happens next

`evaluate_weights.py --expert` runs 100 random train/test splits per application
and reports, on held-out rows:

- **MSE / RMSE / MAE in rating points** — how far the model's predicted rating is
  from yours
- **Spearman ρ** — whether it orders the fibers in a scenario the way you do
- **NDCG@3 and P@3** — whether its top picks are the ones you rated ≥ 4

and learns weights that start at the AHP values and move toward your ratings.

With 4 scenarios per application the test sets are small, so results carry wide
error bars. More scenarios (raise `SCENARIOS_PER_APPLICATION` in
`make_expert_template.py`) give tighter estimates.
