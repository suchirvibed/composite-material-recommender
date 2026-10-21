"""
Validate lamina_estimator.py against the published lamina data.

Reports:
  1. Leave-one-out cross-validation (each point predicted by a model fitted
     WITHOUT it): MSE, RMSE, MAE, MAPE, R^2 for E1 and Xt, against the
     textbook rule of mixtures (E1 = Vf*Ef + (1-Vf)*Em, Xt = Vf*sigma_f).
  2. 100-resample bootstrap confidence intervals for the fitted coefficients.
  3. Datasheet vs NCAMP measured, for fibers that have both.
  4. Does fiber-level ranking survive at lamina level? (Spearman rho), and do
     compression / ILSS track fiber properties at all?

Usage:  py evaluate_lamina_model.py [n_bootstrap]
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

import lamina_estimator as le

VF = 0.60          # all calibration data is normalized to ~60 % fiber volume
EM_GPA = 3.5       # typical cured structural epoxy modulus (textbook ROM input)
N_BOOT = 100
SEED = 42


def regression_metrics(y: np.ndarray, pred: np.ndarray) -> dict:
    err = pred - y
    ss_res = float(np.sum(err ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return {
        "MSE": float(np.mean(err ** 2)),
        "RMSE": float(np.sqrt(np.mean(err ** 2))),
        "MAE": float(np.mean(np.abs(err))),
        "MAPE_%": float(np.mean(np.abs(err) / y) * 100),
        "R2": 1 - ss_res / ss_tot if ss_tot > 0 else np.nan,
    }


def leave_one_out(data: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    e1_pred, xt_pred = np.empty(len(data)), np.empty(len(data))
    for i in range(len(data)):
        model = le.fit(data.drop(index=i))
        est = model.estimate(data.loc[i, "fiber_strength_mpa"], data.loc[i, "fiber_modulus_gpa"])
        e1_pred[i], xt_pred[i] = est["E1_GPa"], est["Xt_MPa"]
    return e1_pred, xt_pred


def spearman(a, b) -> float:
    # Positional arrays: a pandas Series would align on its (gappy) index.
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return float(pd.Series(a).rank().corr(pd.Series(b).rank()))


def main() -> None:
    n_boot = int(sys.argv[1]) if len(sys.argv) > 1 else N_BOOT
    data = le.load_calibration_data()
    ef, sf = data["fiber_modulus_gpa"].to_numpy(), data["fiber_strength_mpa"].to_numpy()
    e1, xt = data["lamina_tensile_modulus_gpa"].to_numpy(), data["lamina_tensile_strength_mpa"].to_numpy()

    model = le.fit(data)
    print("=" * 74)
    print(f"LAMINA MODEL — calibrated on {len(data)} published fiber/lamina pairs")
    print("=" * 74)
    print(f"  E1 = {model.modulus_slope:.3f} x E_fiber + {model.modulus_intercept:.1f} GPa")
    print(f"  Xt = {model.strength_efficiency:.3f} x sigma_fiber   "
          f"(ideal rule of mixtures at 60% Vf would be 0.600)")

    # 1. LOO-CV vs textbook rule of mixtures
    e1_loo, xt_loo = leave_one_out(data)
    rows = {
        ("E1 [GPa]", "rule of mixtures"): regression_metrics(e1, VF * ef + (1 - VF) * EM_GPA),
        ("E1 [GPa]", "calibrated (LOO)"): regression_metrics(e1, e1_loo),
        ("Xt [MPa]", "rule of mixtures"): regression_metrics(xt, VF * sf),
        ("Xt [MPa]", "calibrated (LOO)"): regression_metrics(xt, xt_loo),
    }
    table = pd.DataFrame(rows).T.round(3)
    print("\n1) Prediction error, leave-one-out cross-validation")
    print(table.to_string())

    # 2. Bootstrap CIs on coefficients
    rng = np.random.default_rng(SEED)
    boots = []
    for _ in range(n_boot):
        sample = data.iloc[rng.integers(0, len(data), len(data))].reset_index(drop=True)
        if sample["fiber_modulus_gpa"].nunique() < 2:
            continue
        m = le.fit(sample)
        boots.append([m.modulus_slope, m.modulus_intercept, m.strength_efficiency])
    boots = np.array(boots)
    lo, hi = np.percentile(boots, [2.5, 97.5], axis=0)
    print(f"\n2) {len(boots)}-resample bootstrap, 95% intervals")
    for name, val, l, h in zip(["E1 slope a", "E1 intercept b", "Xt efficiency k"],
                               [model.modulus_slope, model.modulus_intercept, model.strength_efficiency],
                               lo, hi):
        print(f"  {name:<16} {val:8.3f}   [{l:.3f}, {h:.3f}]")

    # 3. Datasheet vs independent NCAMP measurement
    print("\n3) Manufacturer datasheet vs NCAMP measured (same fiber, same resin)")
    both = data.groupby("fiber_id").filter(
        lambda g: {"manufacturer_datasheet", "NCAMP_measured"} <= set(g["source_type"]))
    for fid, g in both.groupby("fiber_id"):
        ds = g[g["source_type"] == "manufacturer_datasheet"].iloc[0]
        nc = g[g["source_type"] == "NCAMP_measured"].iloc[0]
        print(f"  {ds['fiber_product']:<12} Xt {ds['lamina_tensile_strength_mpa']:.0f} vs "
              f"{nc['lamina_tensile_strength_mpa']:.0f} MPa "
              f"({(ds['lamina_tensile_strength_mpa'] / nc['lamina_tensile_strength_mpa'] - 1) * 100:+.1f}%) | "
              f"E1 {ds['lamina_tensile_modulus_gpa']:.0f} vs {nc['lamina_tensile_modulus_gpa']:.0f} GPa "
              f"({(ds['lamina_tensile_modulus_gpa'] / nc['lamina_tensile_modulus_gpa'] - 1) * 100:+.1f}%)")

    # 4. Ranking preservation and resin-dominated properties
    xc = data["lamina_compressive_strength_mpa"]
    ilss = data["lamina_sbs_or_ilss_mpa"]
    ok_c, ok_i = xc.notna(), ilss.notna()
    print("\n4) Does the fiber property ranking carry over to the lamina? (Spearman rho)")
    print(f"  fiber modulus  -> lamina E1      rho = {spearman(ef, e1):+.2f}")
    print(f"  fiber strength -> lamina Xt      rho = {spearman(sf, xt):+.2f}")
    print(f"  fiber strength -> lamina Xc      rho = {spearman(sf[ok_c], xc[ok_c]):+.2f}   (n={ok_c.sum()})")
    print(f"  fiber strength -> SBS/ILSS       rho = {spearman(sf[ok_i], ilss[ok_i]):+.2f}   (n={ok_i.sum()})")

    worst = np.argsort(-np.abs(xt_loo - xt))[:3]
    print("\n  Largest Xt misses (LOO):")
    for i in worst:
        r = data.loc[i]
        print(f"    {r['fiber_product']:<24} {r['resin']:<16} predicted {xt_loo[i]:.0f}, "
              f"published {xt[i]:.0f} MPa ({(xt_loo[i] / xt[i] - 1) * 100:+.0f}%)")

    out = data.assign(E1_pred_LOO=e1_loo.round(1), Xt_pred_LOO=xt_loo.round(0))
    out.to_csv("lamina_model_validation.csv", index=False)
    print("\nSaved: lamina_model_validation.csv")


if __name__ == "__main__":
    main()
