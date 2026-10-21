"""
UD lamina property estimator, calibrated on published lamina data.

v4 ranks FIBERS, but parts are made from LAMINAS (fiber + resin). This
module turns fiber datasheet properties into an estimate of 0-degree
unidirectional lamina properties at ~60 % fiber volume in a structural
epoxy, calibrated on literature_data/lamina_calibration_data.csv
(NCAMP measured data + Toray/Hexcel datasheets).

Models (fitted by least squares):
    E1  = a * E_fiber + b        (rule-of-mixtures form: a ~ Vf, b ~ (1-Vf) Em)
    Xt  = k * sigma_fiber        (strength translation efficiency)

Compression and interlaminar shear are NOT estimated: they are governed by
the resin, sizing and fiber-matrix interface, and the calibration data shows
they don't track fiber tensile properties (see evaluate_lamina_model.py).

When a fiber has published lamina data, use that instead of the estimate:
published_lamina() returns it, preferring NCAMP measured values.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
CALIBRATION_FILE = BASE_DIR / "literature_data" / "lamina_calibration_data.csv"
FIBER_FILE = BASE_DIR / "Carbon_Fiber_Master_v6_Top5(1).csv"

SOURCE_PRIORITY = {"NCAMP_measured": 0, "MIL-HDBK-17_measured": 1, "manufacturer_datasheet": 2}


@dataclass
class LaminaModel:
    modulus_slope: float
    modulus_intercept: float
    strength_efficiency: float
    modulus_rmse_gpa: float      # in-sample residual RMSE, for +/- display
    strength_rmse_mpa: float
    n_points: int
    strength_range_mpa: tuple = (np.nan, np.nan)   # fiber range seen in calibration
    modulus_range_gpa: tuple = (np.nan, np.nan)

    def estimate(self, fiber_strength_mpa: float, fiber_modulus_gpa: float) -> dict:
        e1 = self.modulus_slope * fiber_modulus_gpa + self.modulus_intercept
        xt = self.strength_efficiency * fiber_strength_mpa
        inside = (
            self.strength_range_mpa[0] <= fiber_strength_mpa <= self.strength_range_mpa[1]
            and self.modulus_range_gpa[0] <= fiber_modulus_gpa <= self.modulus_range_gpa[1]
        )
        return {
            "E1_GPa": float(e1) if np.isfinite(e1) else np.nan,
            "Xt_MPa": float(xt) if np.isfinite(xt) else np.nan,
            "extrapolated": not inside,
        }


def load_calibration_data() -> pd.DataFrame:
    """Lamina rows joined with the fiber database's fiber properties."""
    lamina = pd.read_csv(CALIBRATION_FILE)
    fibers = pd.read_csv(FIBER_FILE)[
        ["fiber_id", "tensile_strength_mpa", "tensile_modulus_gpa"]
    ].rename(columns={"tensile_strength_mpa": "fiber_strength_mpa",
                      "tensile_modulus_gpa": "fiber_modulus_gpa"})
    for col in ["fiber_strength_mpa", "fiber_modulus_gpa"]:
        # Same parsing as v4's number(): first numeric token, commas ignored.
        fibers[col] = pd.to_numeric(
            fibers[col].astype(str).str.replace(",", "").str.extract(r"(-?\d+(?:\.\d+)?)")[0],
            errors="coerce",
        )
    data = lamina.merge(fibers, on="fiber_id", how="left")
    return data.dropna(subset=["fiber_strength_mpa", "fiber_modulus_gpa"]).reset_index(drop=True)


def fit_modulus(ef: np.ndarray, e1: np.ndarray) -> tuple[float, float]:
    slope, intercept = np.polyfit(ef, e1, 1)
    return float(slope), float(intercept)


def fit_strength(sf: np.ndarray, xt: np.ndarray) -> float:
    return float((sf @ xt) / (sf @ sf))         # least squares through origin


def fit(data: pd.DataFrame) -> LaminaModel:
    ef, e1 = data["fiber_modulus_gpa"].to_numpy(), data["lamina_tensile_modulus_gpa"].to_numpy()
    sf, xt = data["fiber_strength_mpa"].to_numpy(), data["lamina_tensile_strength_mpa"].to_numpy()
    a, b = fit_modulus(ef, e1)
    k = fit_strength(sf, xt)
    return LaminaModel(
        modulus_slope=a, modulus_intercept=b, strength_efficiency=k,
        modulus_rmse_gpa=float(np.sqrt(np.mean((a * ef + b - e1) ** 2))),
        strength_rmse_mpa=float(np.sqrt(np.mean((k * sf - xt) ** 2))),
        n_points=len(data),
        strength_range_mpa=(float(sf.min()), float(sf.max())),
        modulus_range_gpa=(float(ef.min()), float(ef.max())),
    )


@lru_cache(maxsize=1)
def calibrated_model() -> Optional[LaminaModel]:
    """Model fitted on the shipped calibration data; None if the file is missing."""
    if not CALIBRATION_FILE.exists():
        return None
    data = load_calibration_data()
    return fit(data) if len(data) >= 3 else None


@lru_cache(maxsize=1)
def _published_by_fiber() -> dict:
    if not CALIBRATION_FILE.exists():
        return {}
    lamina = pd.read_csv(CALIBRATION_FILE)
    lamina["_rank"] = lamina["source_type"].map(SOURCE_PRIORITY).fillna(9)
    best = lamina.sort_values("_rank").drop_duplicates("fiber_id")
    return {r["fiber_id"]: r.to_dict() for _, r in best.iterrows()}


def published_lamina(fiber_id: str) -> Optional[dict]:
    """Best published lamina record for a fiber (NCAMP before datasheet)."""
    return _published_by_fiber().get(fiber_id)
