# Validation results

All numbers are reproducible with the commands shown (fixed random seeds).

## Lamina estimator — `py evaluate_lamina_model.py 100`

Leave-one-out cross-validation on 16 published fiber/lamina pairs:

| Target | Model | RMSE | MAE | MAPE | R² |
|---|---|---|---|---|---|
| E1 [GPa] | textbook rule of mixtures | 7.97 | 6.50 | 4.5 % | 0.83 |
| E1 [GPa] | **calibrated** | **5.47** | **4.69** | **3.1 %** | **0.92** |
| Xt [MPa] | textbook rule of mixtures | 626 | 582 | 23.4 % | −1.10 |
| Xt [MPa] | **calibrated** | **221** | **163** | **6.5 %** | **0.74** |

100-resample bootstrap 95 % intervals: E1 slope 0.634 [0.545, 0.706];
strength efficiency 0.489 [0.473, 0.508].

Datasheet vs independent NCAMP measurement (same fiber, same resin):

| Fiber / 8552 | Xt datasheet vs NCAMP | E1 datasheet vs NCAMP |
|---|---|---|
| AS4 | 2137 vs 1996 MPa (+7.1 %) | 135 vs 127 GPa (+6.0 %) |
| IM7 | 2723 vs 2501 MPa (+8.9 %) | 164 vs 158 GPa (+3.5 %) |

Fiber ranking carries over to the lamina for stiffness and tensile strength
(Spearman ρ = 0.85 and 0.90), but not for compression (0.56) or ILSS (0.12).
The resin matters: T700S and T700G share a fiber strength of 4900 MPa but
their published laminas differ by 40 % (2860 vs 2040 MPa).

## Weights vs manufacturer-use labels — `py evaluate_weights.py 100`

Mean ± std over 100 held-out test splits.

**Aerospace** (41/52 fibers labelled aerospace)

| Weights | MSE | RMSE | AUC | P@5 | NDCG@10 |
|---|---|---|---|---|---|
| baseline | 0.160 | 0.400 | 0.50 | 0.50 | 0.65 |
| hand (v4 original) | 0.165 ± 0.013 | 0.406 | 0.55 | 0.82 | 0.82 |
| AHP | 0.168 ± 0.013 | 0.409 | 0.40 | 0.75 | 0.75 |
| learned | 0.170 ± 0.016 | 0.412 | 0.42 | 0.75 | 0.76 |

**Industrial** (24/52 labelled industrial)

| Weights | MSE | RMSE | AUC | P@5 | NDCG@10 |
|---|---|---|---|---|---|
| baseline | 0.249 | 0.499 | 0.50 | 0.41 | 0.42 |
| hand | 0.244 ± 0.028 | 0.493 | 0.62 | 0.55 | 0.73 |
| AHP | 0.242 ± 0.029 | 0.492 | 0.63 | 0.57 | 0.75 |
| learned | 0.246 ± 0.034 | 0.495 | 0.62 | 0.56 | 0.73 |

**Reading:** the scoring clearly improves *top-K ranking* over the baseline,
but no weight set improves *calibration* (MSE/RMSE) on these weak labels, and
learning barely moves the weights from AHP. The engine therefore keeps the AHP
weights; learned weights should be revisited once expert ratings
(`EXPERT_RATING_GUIDE.md`) or simulation results exist.

## Literature weights (`literature_data/literature_mcdm_weights.csv`)

Kishore & Subbaiah (2025), automobile roof, entropy weights: strength 0.370,
modulus 0.264, density 0.080, elongation 0.094 (+ availability 0.192).
Entropy weights measure data dispersion across very different fibers (glass,
aramid, natural, carbon), not engineering preference, so they are recorded for
comparison rather than adopted.
