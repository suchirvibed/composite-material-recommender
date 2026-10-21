# Validation results

All numbers are reproducible with the commands shown (fixed random seeds).

## Lamina estimator — `py evaluate_lamina_model.py 100`

Leave-one-out cross-validation on 27 published fiber/lamina pairs
(2 NCAMP, 11 MIL-HDBK-17-2F, 14 manufacturer datasheets):

| Target | Model | RMSE | MAE | MAPE | R² |
|---|---|---|---|---|---|
| E1 [GPa] | textbook rule of mixtures | 10.33 | 8.03 | 5.8 % | 0.93 |
| E1 [GPa] | **calibrated** | **8.23** | **5.77** | **4.0 %** | **0.96** |
| Xt [MPa] | textbook rule of mixtures | 659 | 613 | 27.7 % | −0.96 |
| Xt [MPa] | **calibrated** | **237** | **178** | **8.0 %** | **0.75** |

100-resample bootstrap 95 % intervals: E1 slope 0.631 [0.517, 0.662];
strength efficiency 0.476 [0.461, 0.491]. Adding MIL-HDBK data (BMI, PEEK,
cyanate ester, and the 540 GPa M55J) raised the modulus R² from 0.92 to 0.96
and extended the valid range to high-modulus fibers; strength MAPE rose from
6.5 % to 8.0 % because resin choice drives strength.

## Mold selector — `py validation_cases.py`

| Case | Documented choice | Engine |
|---|---|---|
| V1 2 m close-tolerance aerospace skin, 1000 cycles | Invar | Invar ✓ |
| V2 low-rate motorsport, tight tolerance, cost-driven | CFRP tooling | CFRP ✓ |
| V3 Class-A surface | Electroformed nickel; composite/board excluded | Nickel ✓ |
| V4 180 °C cure | 130 °C board rejected | rejected ✓ |
| V5 2 m tool, 1 mm HARD tolerance | aluminium (≈6.5 mm mismatch) rejected | rejected ✓ |
| V6 project 1 m² DOE | low-CTE + high-CTE arm | Invar + mild steel ✓ |

Physics reproduces the Matrix Engine Report worked check (2 m, ΔT 155 °C):
steel 3.10 mm, aluminium 6.70 mm (report 6.5 mm with α = 23), Invar 0.21 mm
(report 0.16 mm with a constant 1.5 µm/m·°C; the datasheet curve gives 2.69 at 180 °C).

## Cure planner

Reproduces the project ANSYS parameter calculation exactly: heating end
3,321.43 s, hold end 14,121.43 s, cycle end 17,442.86 s (4 h 50 min 43 s).

Datasheet vs independent NCAMP measurement (same fiber, same resin):

| Fiber / 8552 | Xt datasheet vs NCAMP | E1 datasheet vs NCAMP |
|---|---|---|
| AS4 | 2137 vs 1996 MPa (+7.1 %) | 135 vs 127 GPa (+6.0 %) |
| IM7 | 2723 vs 2501 MPa (+8.9 %) | 164 vs 158 GPa (+3.5 %) |

Fiber ranking carries over to the lamina for stiffness and tensile strength
(Spearman ρ = 0.75 and 0.89), weakly for compression (0.66) and not for ILSS (0.12).
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
