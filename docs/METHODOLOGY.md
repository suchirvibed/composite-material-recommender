# Methodology

This engine is a **rule-based multi-criteria decision-making (MCDM) system**.
It does not train a machine-learning model to make recommendations; it ranks
database candidates with a transparent weighted-sum score, using weights
derived by the **Analytic Hierarchy Process (AHP)**. Data-driven components
(weight learning, the lamina estimator) are calibrated and validated against
published data, and are reported with their errors.

## 1. Pipeline

```
Load databases → User inputs → Hard filter → (none survive? → diagnostics)
      → Score 0-100 → Rank fibers → Rank prepregs & resins → Output
```

| Step | What happens |
|---|---|
| Load | Fiber, prepreg and resin CSVs, each normalized once (numbers parsed from text such as "6,370 MPa"). |
| Inputs | Application, min. strength / modulus / elongation, max. density, each **HARD** (must pass) or **PREFERRED**; process; matrix; certification. |
| Hard filter | Fibers failing any HARD limit are removed. Missing data fails a HARD limit (it cannot be demonstrated). |
| Diagnostics | If nothing survives, each limit is tested on its own so the user sees which one eliminated every candidate. |
| Score | See §3. |
| Prepreg / resin | Ranked independently on process, matrix and certification text. A prepreg made with one of the top fibers (exact grade token) gets an explicit-match bonus. No full fiber+prepreg+resin compatibility is claimed. |

## 2. AHP weights

For each application, four criteria — strength, modulus, density,
elongation — are compared in pairs on Saaty's 1–9 scale
(1 equal, 3 moderate, 5 strong, 7 very strong, 9 extreme; 1/x when the second
criterion is more important). Six judgments build a reciprocal 4×4 matrix *A*
(a<sub>ji</sub> = 1/a<sub>ij</sub>).

- **Weights** = normalized principal eigenvector of *A*.
- **Consistency**: λ<sub>max</sub> is the principal eigenvalue;
  CI = (λ<sub>max</sub> − n)/(n − 1); CR = CI / RI with RI(4) = 0.90.
  Judgments are accepted only if **CR < 0.10**. Custom mode re-asks the
  comparisons until they are consistent.

Preset weights (all CR ≤ 0.004):

| Application | Strength | Modulus | Density | Elongation |
|---|---|---|---|---|
| Aerospace | 0.193 | 0.368 | 0.368 | 0.070 |
| Automotive / Motorsport | 0.227 | 0.227 | 0.424 | 0.122 |
| Pressure Vessel / Energy | 0.500 | 0.167 | 0.167 | 0.167 |
| Sporting Goods | 0.125 | 0.375 | 0.375 | 0.125 |
| Industrial | 0.424 | 0.227 | 0.227 | 0.122 |

## 3. Scoring

**Property score** (0–100) compares each value with its target:

- higher is better (strength, modulus, elongation):
  `min(value/target, 1.5) / 1.5 × 100` — exceeding the target by 50 % is full marks;
- lower is better (density): 100 at or under the limit, else `target/value × 100`;
- target 0 = no requirement (100); **unpublished value = 0** ("not demonstrated").

**Engineering score** = AHP-weighted mean of the four property scores.

**Final score**:

| Component | Weight |
|---|---|
| Engineering score | 70 % |
| Application fit (datasheet use text) | 8 % |
| Process fit (fiber-dependent only: filament winding tows, pultrusion) | 8 % |
| Grade fit (aerospace vs industrial grade) | 6 % |
| Matrix fit (explicit compatibility, or epoxy sizing code GP/GS/G) | 6 % |
| Certification | 2 % |

Text matching uses whole words/tokens, so "pa" does not match "capable" and
grade "AS4" does not match "AS4C".

## 4. Lamina estimator

Parts are made from laminas (fiber + resin), not bare fibers. For each
recommended fiber the engine shows 0° unidirectional lamina properties:

1. **Published** values when available (NCAMP measured, then MIL-HDBK-17-2F
   measured, then manufacturer datasheets) — see `literature_data/SOURCES.md`.
2. Otherwise an **estimate** calibrated by least squares on 27 published
   fiber/lamina pairs (≈60 % fiber volume; epoxy, BMI, PEEK and cyanate-ester
   matrices; fiber modulus 230–540 GPa):
   - E<sub>1</sub> = 0.631 · E<sub>fiber</sub> − 13.3 GPa
   - X<sub>t</sub> = 0.476 · σ<sub>fiber</sub>
   Fibers outside the calibrated strength/modulus range get **no number**
   ("no reliable estimate") rather than an extrapolation.

Compression and interlaminar shear are deliberately not estimated: they
depend on resin and interface, and track fiber tensile strength only weakly
(Spearman ρ = 0.66 and 0.12).

## 4a. Mold (tool) material selector

Implements the project's *Matrix Engine Report* in four stages.

**Inputs** — part envelope L×W×H, geometry (flat / curved / angled with corner
angle and UD/QI layup), cure temperature, pressure and ramp, part CTE
(carbon/epoxy ≈ 2 µm/m·°C), tolerance (target or HARD), cycle count, ₹ cost
ceiling, Class-A requirement, autoclave envelope, application profile.

**Feasibility gate** (pass/fail, every rejection explained): tool service
temperature ≥ cure + 20 °C; cycle life ≥ required cycles; lower cost estimate
≤ ceiling; δ ≤ tolerance when HARD; Class-A capability; part fits the
autoclave. Unknown limits pass with a "verify" flag.

**Engineering calculation** per survivor:

| Index | Formula | Basis |
|---|---|---|
| CTE mismatch error | δ = \|α_tool(T) − α_part\| · ΔT · L | Matrix Engine Report; Invar uses its mean-CTE curve (1.30 → 2.11 → 4.18 µm/m·°C at 93/149/260 °C) |
| Thermal lag | τ = ρ·c_p·t / h; lag = ramp · τ; Biot = h·t/k checked < 0.1 | lumped tool; h interpolated from measured means 37 (oven), 99 (3 bar), 138 W/m²K (7 bar) — Fisher et al. 2022 |
| Tool mass | M = ρ · L · W · t | face only, default thickness per class |
| Durability | cycle-life class → minimum cycles | tooling report |
| Cost | ₹/~1 m² × area | project BOM document |
| Corner spring-in | Δθ = Δθ₉₀ · θ/90, Δθ₉₀ = 0.90° (UD) / 1.28° (QI) | Albert & Fernlund 2002 Eq. 1 (T800H/3900-2, 180 °C); tool angle opened by Δθ as a starting compensation |

**Scoring** — direction-aware min-max across survivors
(benefit: n = (x − min)/(max − min); cost: n = (max − x)/(max − min)),
S = Σ wᵢ nᵢ. Weights come from AHP pairwise judgments per profile
(prototype: cost 0.64; production: δ, lag and durability 0.26 each;
aerospace: δ 0.61), all CR < 0.01. A missing value scores 0 ("not
demonstrated"). Each weight is perturbed ±20 %; if the winner changes the
result is reported as a close call with the top two.

**DOE pairing** — the best-ranked low-CTE arm (Invar or CFRP tooling) and
high-CTE arm (aluminium or mild steel) for the project's tool-material study
(Master Report §3.3).

## 4b. Cure-cycle planner

Cycles are taken only from project documents (HexPly M18/1 monolithic,
sandwich and alternative cycles; the ANSYS aluminium-mould demonstration
cycle; HexTool M61 tool cure). Each ramp lasts |ΔT|/rate, each hold its stated
time (the same arithmetic as the project's ANSYS parameter calculation, which
the planner reproduces to the second). The selected tool's time constant τ
extends the final hold by τ·ln(lag/5 °C), because cure time starts when the
lagging thermocouple reaches cure temperature (Hexcel Prepreg Technology).
It warns on pressures outside the documented range, sandwich parts on a
monolithic (high-pressure) cycle, and tools whose service limit is below the
cure peak; it exports the ANSYS convection table as CSV.

## 4c. BOM & cost estimator

The 16 consumable rows of the project BOM (1 m² sandwich basis) scale with
panel area, perimeter (sealant, edge dams) or per panel (ports, hoses,
thermocouples, inserts); core and film adhesive are dropped for monolithic
panels. DOE scenarios use one mould per condition reused for that condition's
panels (Master Report §5.5) with mould ₹ ranges from the BOM document.

## 5. Weight evaluation and learning

`evaluate_weights.py` runs N (default 100) trials per application: random
requirement targets (database 25th–75th percentiles), stratified 70/30
split, and a comparison of baseline, hand weights, AHP weights and learned
weights. Learning starts at the AHP weights (softmax-parameterized, L2-pulled
toward the prior) and minimizes log-loss; scores are calibrated to
probabilities with a 1-D logistic fit (Newton's method) before computing
MSE, RMSE, MAE, log-loss, accuracy, AUC, P@5 and NDCG@10.

Two label sources are supported:

- **Manufacturer intended use** (default) — available now, but weak
  (marketing positioning, not performance).
- **Expert ratings** (`--expert`) — a blind 1–5 rating sheet from
  `make_expert_template.py`; errors are then reported in rating points.

## 6. Limitations

- Recommendations are database-level candidates, not qualification.
- Weak labels: with manufacturer-use labels no weight set beats the
  base-rate baseline on MSE/RMSE (see `docs/RESULTS.md`); real performance or
  expert labels are needed before learned weights should replace AHP.
- Density barely varies across carbon fibers (~1.75–1.93 g/cm³), so its weight
  is hard to learn from any ranking data.
- Datasheet lamina values run 4–9 % above independent NCAMP means.
- `Simulation_Results_v1.csv` is still empty (85 DOE cases are planned).
