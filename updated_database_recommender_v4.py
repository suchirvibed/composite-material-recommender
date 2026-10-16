"""
Composite Material Recommendation Engine v4

Refactor of the earlier Hexcel-only recommender.

Key changes:
- Uses the current combined carbon-fiber master database.
- Normalizes the database schema once, instead of hard-coding older column names.
- Keeps HARD constraints separate from PREFERRED scoring.
- Uses bounded 0-100 component scores so final ranking is interpretable.
- Keeps manufacturer/source traceability in the result.
- Adds optional prepreg/resin process filtering without pretending
  generic compatibility is a manufacturer qualification.
- Leaves room for future laminate/process recommendation layers.
- Derives property importance weights with AHP (Analytic Hierarchy
  Process) pairwise comparisons, and rejects inconsistent judgments
  via the consistency ratio (CR < 0.10).

Database files expected beside this script (or set paths below):
    Carbon_Fiber_Master_v6_Top5.csv
    Prepreg_Master_Database_v2_Expanded.csv
    Resin_Master_Database_v10_HiFlow_Added.csv

This engine recommends candidate MATERIAL SYSTEM INPUTS.
It does not replace engineering qualification.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Dict, Iterable, Optional

import numpy as np
import pandas as pd

import lamina_estimator


BASE_DIR = Path(__file__).resolve().parent

# ============================================================
# DATABASE PATHS
# Each database is independent.
#
# Fiber recommendation reads ONLY the fiber database.
# Prepreg/resin databases are read separately by their own loaders.
# ============================================================

FIBER_FILE = BASE_DIR / "Carbon_Fiber_Master_v6_Top5(1).csv"
PREPREG_FILE = BASE_DIR / "Prepreg_Master_Database_v2_Expanded.csv"
RESIN_FILE = BASE_DIR / "Resin_Master_Database_v10.csv"


def resolve_file(primary: Path, description: str) -> Path:
    """Resolve one database file independently."""
    if primary.exists():
        return primary

    fallback = Path("/mnt/data") / primary.name
    if fallback.exists():
        return fallback

    raise FileNotFoundError(
        f"{description} was not found. Expected:\n"
        f"  {primary}\n"
        f"or:\n"
        f"  {fallback}\n"
    )


# ============================================================
# AHP (ANALYTIC HIERARCHY PROCESS) WEIGHTS
#
# Instead of hand-typing importance weights, each application states
# pairwise judgments on Saaty's 1-9 scale: "how much more important is
# A than B?" (1 = equal, 3 = moderate, 5 = strong, 7 = very strong,
# 9 = extreme; use 1/x when B is more important). The weights are the
# normalized principal eigenvector of the pairwise matrix.
# ============================================================

CRITERIA = ["strength", "modulus", "density", "elongation"]

# Every unordered criteria pair, in the order judgments are listed/asked.
CRITERIA_PAIRS = [
    (a, b) for i, a in enumerate(CRITERIA) for b in CRITERIA[i + 1:]
]

# Saaty's random consistency index, by matrix size.
RANDOM_INDEX = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12,
                6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}

CR_THRESHOLD = 0.10


@dataclass
class AhpResult:
    weights: Dict[str, float]
    lambda_max: float
    consistency_index: float
    consistency_ratio: float

    @property
    def consistent(self) -> bool:
        return self.consistency_ratio < CR_THRESHOLD


def build_pairwise_matrix(judgments: Dict[tuple, float]) -> np.ndarray:
    """Build the reciprocal AHP matrix from upper-triangle judgments."""
    n = len(CRITERIA)
    matrix = np.ones((n, n))
    for (a, b), value in judgments.items():
        if value <= 0:
            raise ValueError(f"AHP judgment {a} vs {b} must be positive.")
        i, j = CRITERIA.index(a), CRITERIA.index(b)
        matrix[i, j] = value
        matrix[j, i] = 1.0 / value
    return matrix


def ahp_weights(judgments: Dict[tuple, float]) -> AhpResult:
    """Derive criteria weights and the consistency ratio from judgments."""
    matrix = build_pairwise_matrix(judgments)
    n = len(matrix)

    eigenvalues, eigenvectors = np.linalg.eig(matrix)
    principal = int(np.argmax(eigenvalues.real))
    vector = np.abs(eigenvectors[:, principal].real)
    weights = vector / vector.sum()

    lambda_max = float(eigenvalues[principal].real)
    ci = max(0.0, (lambda_max - n) / (n - 1)) if n > 1 else 0.0
    ri = RANDOM_INDEX.get(n, 1.49)
    cr = ci / ri if ri > 0 else 0.0

    return AhpResult(
        weights={c: float(w) for c, w in zip(CRITERIA, weights)},
        lambda_max=lambda_max,
        consistency_index=ci,
        consistency_ratio=cr,
    )


def judgments(values: Iterable[float]) -> Dict[tuple, float]:
    """Pair a list of judgments with CRITERIA_PAIRS, in order."""
    values = list(values)
    if len(values) != len(CRITERIA_PAIRS):
        raise ValueError(f"Expected {len(CRITERIA_PAIRS)} AHP judgments.")
    return dict(zip(CRITERIA_PAIRS, values))


# Judgment order: strength/modulus, strength/density, strength/elongation,
#                 modulus/density, modulus/elongation, density/elongation
APPLICATIONS = {
    "1": {
        "name": "Aerospace",
        # Stiffness and weight dominate; elongation matters least.
        "ahp_judgments": judgments([1/2, 1/2, 3, 1, 5, 5]),
        "use_terms": ["aerospace"],
    },
    "2": {
        "name": "Automotive / Motorsport",
        # Lightweighting leads; strength and stiffness balanced.
        "ahp_judgments": judgments([1, 1/2, 2, 1/2, 2, 3]),
        "use_terms": ["motorsport", "automotive", "industrial"],
    },
    "3": {
        "name": "Pressure Vessel / Energy",
        # Burst strength dominates; other properties equal.
        "ahp_judgments": judgments([3, 3, 3, 1, 1, 1]),
        "use_terms": ["pressure vessel", "energy", "industrial"],
    },
    "4": {
        "name": "Sporting Goods",
        # Stiff and light; strength and elongation secondary.
        "ahp_judgments": judgments([1/3, 1/3, 1, 1, 3, 3]),
        "use_terms": ["sporting goods"],
    },
    "5": {
        "name": "Industrial",
        # Strength first; cost-driven so density matters less.
        "ahp_judgments": judgments([2, 2, 3, 1, 2, 2]),
        "use_terms": ["industrial"],
    },
    "6": {
        "name": "Custom",
        "ahp_judgments": None,
        "use_terms": [],
    },
}


# Composite manufacturing processes. These are deliberately separate
# from fiber-format operations such as weaving or braiding.
PROCESS_OPTIONS = {
    "1": None,
    "2": "VARTM / infusion",
    "3": "RTM",
    "4": "autoclave",
    "5": "OOA / VBO",
    "6": "press / compression molding",
    "7": "filament winding",
    "8": "pultrusion",
}

MATRIX_OPTIONS = {
    "1": None,
    "2": "epoxy",
    "3": "thermoplastic",
    "4": "polycarbonate",
    "5": "phenolic",
    "6": "vinyl ester",
    "7": "cyanate ester",
    "8": "BMI",
    "9": "polyimide",
}


def clean_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def norm(value: Any) -> str:
    return clean_text(value).lower()


def number(value: Any) -> float:
    if pd.isna(value):
        return np.nan
    text = str(value).strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return float(match.group()) if match else np.nan


def split_numbers(value: Any) -> list[float]:
    if pd.isna(value):
        return []
    return [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(value))]


def parse_tows(value: Any) -> set[int]:
    if pd.isna(value):
        return set()
    return {int(x) for x in re.findall(r"(\d+)\s*K", str(value).upper())}


def ratio_score(value: float, target: float, higher_is_better: bool) -> float:
    """
    Convert a requirement ratio into a bounded 0-100 preference score.

    A target of 0 means "no requirement": any fiber with published data
    satisfies it fully. Missing data returns NaN (scored 0 downstream).
    """
    if not np.isfinite(value) or not np.isfinite(target):
        return np.nan
    if target <= 0:
        return 100.0
    ratio = value / target
    if higher_is_better:
        return float(np.clip(ratio, 0.0, 1.5) / 1.5 * 100.0)
    if value <= target:
        return 100.0
    return float(np.clip(target / value, 0.0, 1.0) * 100.0)


def weighted_mean(values: Dict[str, float], weights: Dict[str, float]) -> float:
    """
    Weighted mean over ALL criteria; a missing value scores 0.

    Unpublished data is treated as "not demonstrated" rather than skipped:
    averaging only the known values let a fiber with a single published
    property (e.g. density) earn a perfect engineering score.
    """
    total_w = sum(weights[k] for k in values)
    if total_w <= 0:
        return np.nan

    return sum(
        (v if np.isfinite(v) else 0.0) * weights[k] for k, v in values.items()
    ) / total_w


def data_completeness(values: Dict[str, float]) -> float:
    """Share of the engineering criteria with published data, 0-100."""
    return 100.0 * sum(np.isfinite(v) for v in values.values()) / len(values)


def tokens(text: Any) -> set[str]:
    """Lower-case alphanumeric tokens, e.g. 'HexTow AS4C (Aerospace)' -> {hextow, as4c, aerospace}."""
    return set(re.findall(r"[a-z0-9]+", norm(text)))


def has_term(text: str, term: str) -> bool:
    """Whole-word/phrase match, so 'pa' does not match inside 'capable'."""
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None


def load_fiber_database() -> pd.DataFrame:
    """Read ONLY the carbon-fiber database."""
    path = resolve_file(FIBER_FILE, "Carbon-fiber database")
    fibers = pd.read_csv(path)
    return normalize_fiber_db(fibers)


def load_prepreg_database() -> pd.DataFrame:
    """Read ONLY the prepreg database."""
    path = resolve_file(PREPREG_FILE, "Prepreg database")
    prepregs = pd.read_csv(path)
    return normalize_prepreg_db(prepregs)


def load_resin_database() -> pd.DataFrame:
    """Read ONLY the resin database."""
    path = resolve_file(RESIN_FILE, "Resin database")
    resins = pd.read_csv(path)
    return normalize_resin_db(resins)


def load_data() -> pd.DataFrame:
    """
    Backward-compatible wrapper.
    Current recommender uses ONLY the fiber database.
    """
    return load_fiber_database()


def normalize_fiber_db(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    required = [
        "fiber_id", "manufacturer", "product",
        "tensile_strength_mpa", "tensile_modulus_gpa",
        "ultimate_elongation_percent", "fiber_density_g_cm3",
    ]
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise ValueError(f"Fiber database is missing columns: {missing}")

    numeric = [
        "tensile_strength_mpa",
        "tensile_modulus_gpa",
        "ultimate_elongation_percent",
        "fiber_density_g_cm3",
        "filament_diameter_um",
        "carbon_content_percent",
    ]
    for col in numeric:
        if col in out:
            out[col] = out[col].apply(number)

    return out


def normalize_prepreg_db(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    for col in [
        "fiber_areal_weight_gsm",
        "resin_content_percent",
        "nominal_cured_ply_thickness_mm",
        "nominal_fiber_volume_percent",
        "nominal_laminate_density_g_cm3",
        "cure_temperature_C",
        "Tg_C",
        "service_temperature_C",
    ]:
        if col in out:
            out[col] = out[col].apply(number)

    return out


def normalize_resin_db(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    for col in [
        "density_g_cm3",
        "viscosity_value",
        "viscosity_temperature_C",
        "cure_temperature_C",
        "Tg_C",
        "service_temperature_C",
    ]:
        if col in out:
            out[col] = out[col].apply(number)

    return out


@dataclass
class Requirements:
    strength_mpa: float
    modulus_gpa: float
    max_density_g_cm3: float
    elongation_percent: float
    hard_strength: bool
    hard_modulus: bool
    hard_density: bool
    hard_elongation: bool
    process: Optional[str]
    matrix: Optional[str]
    require_certification: bool


def constraint_diagnostics(df: pd.DataFrame, req: Requirements) -> list[dict]:
    """
    Diagnose every numerical requirement independently.

    This is intentionally separate from numerical_filter(): a failed
    candidate set should tell the user WHICH hard constraint caused it,
    rather than only reporting that no candidate survived.
    """
    checks = [
        (
            "Strength",
            "tensile_strength_mpa",
            req.strength_mpa,
            "≥",
            lambda s, x: s.notna() & (s >= x),
        ),
        (
            "Modulus",
            "tensile_modulus_gpa",
            req.modulus_gpa,
            "≥",
            lambda s, x: s.notna() & (s >= x),
        ),
        (
            "Density",
            "fiber_density_g_cm3",
            req.max_density_g_cm3,
            "≤",
            lambda s, x: s.notna() & (s <= x),
        ),
        (
            "Elongation",
            "ultimate_elongation_percent",
            req.elongation_percent,
            "≥",
            lambda s, x: s.notna() & (s >= x),
        ),
    ]

    diagnostics = []

    for name, column, threshold, operator, test in checks:
        series = pd.to_numeric(df[column], errors="coerce")
        valid = series.notna()
        passed = test(series, threshold)
        count = int(passed.sum())
        missing = int((~valid).sum())

        diagnostics.append({
            "requirement": name,
            "operator": operator,
            "threshold": threshold,
            "hard": getattr(req, f"hard_{name.lower()}"),
            "passing_candidates": count,
            "missing_data": missing,
            "total_candidates": len(df),
        })

    return diagnostics


def print_constraint_diagnostics(df: pd.DataFrame, req: Requirements) -> None:
    """Print a readable explanation of which constraints eliminate candidates."""
    diagnostics = constraint_diagnostics(df, req)

    print("\n" + "=" * 70)
    print("CONSTRAINT DIAGNOSTICS")
    print("=" * 70)

    for d in diagnostics:
        status = "✓" if d["passing_candidates"] > 0 else "✗"

        if d["requirement"] == "Strength":
            unit = "MPa"
        elif d["requirement"] == "Modulus":
            unit = "GPa"
        elif d["requirement"] == "Density":
            unit = "g/cm³"
        else:
            unit = "%"

        hard_text = "HARD" if d["hard"] else "PREFERRED"

        print(
            f"{status} {d['requirement']:<12} "
            f"{d['operator']} {d['threshold']:.2f} {unit:<7} "
            f"| {d['passing_candidates']:>3}/{d['total_candidates']} pass "
            f"| {hard_text}"
        )

        if d["missing_data"]:
            print(
                f"    Missing data: {d['missing_data']} candidate(s) "
                f"— missing values only eliminate candidates when this "
                f"requirement is HARD."
            )

    hard_failures = [
        d for d in diagnostics
        if d["hard"] and d["passing_candidates"] == 0
    ]

    if hard_failures:
        print("\nWHY NO CANDIDATE QUALIFIED:")
        for d in hard_failures:
            if d["requirement"] == "Density":
                explanation = (
                    "The maximum allowed density is below the density of "
                    "every candidate with published density data."
                )
            else:
                explanation = (
                    f"No candidate satisfies the HARD {d['requirement'].lower()} "
                    f"requirement."
                )
            print(f"  • {d['requirement']}: {explanation}")

        print("\nSUGGESTION:")
        print(
            "Relax one of the constraints marked ✗, change it from HARD "
            "to PREFERRED, or verify that the requested value/unit is correct."
        )
    else:
        print("\nAll HARD constraints have at least one qualifying candidate.")


def numerical_filter(df: pd.DataFrame, req: Requirements) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)

    constraints = [
        ("tensile_strength_mpa", req.strength_mpa, req.hard_strength, True),
        ("tensile_modulus_gpa", req.modulus_gpa, req.hard_modulus, True),
        ("ultimate_elongation_percent", req.elongation_percent, req.hard_elongation, True),
        ("fiber_density_g_cm3", req.max_density_g_cm3, req.hard_density, False),
    ]

    for col, threshold, hard, higher_is_better in constraints:
        if not hard:
            continue

        valid = df[col].notna()
        if higher_is_better:
            mask &= valid & (df[col] >= threshold)
        else:
            mask &= valid & (df[col] <= threshold)

    return df.loc[mask].copy()


def application_fit(row: pd.Series, app: dict) -> float:
    terms = app["use_terms"]
    if not terms:
        return 100.0

    text = " ".join(
        norm(row.get(col, ""))
        for col in ["recommended_uses", "market_or_grade", "fiber_class"]
    )

    hits = sum(term in text for term in terms)
    if hits >= 2:
        return 100.0
    if hits == 1:
        return 75.0
    return 50.0


def grade_fit(row: pd.Series, application_name: str) -> float:
    text = " ".join(
        norm(row.get(col, ""))
        for col in ["market_or_grade", "fiber_class", "recommended_uses"]
    )

    if application_name == "Aerospace":
        return 100.0 if "aerospace" in text else 50.0

    if application_name in {"Automotive / Motorsport", "Industrial", "Pressure Vessel / Energy"}:
        return 100.0 if "industrial" in text else 70.0

    return 100.0


def process_fit(row: pd.Series, process: Optional[str]) -> float:
    """
    Fiber-level process suitability.

    Only filament winding and pultrusion depend on the FIBER itself (heavy
    tows / an explicit pultrusion grade). For RTM, infusion, autoclave, OOA
    and press molding, suitability is decided by the resin or prepreg, which
    are ranked separately — so fibers stay neutral (100) instead of all
    receiving the same arbitrary 70.
    """
    if process == "filament winding":
        tows = parse_tows(row.get("sizing_options", ""))
        return 100.0 if tows & {12, 24, 48, 50} else 65.0

    if process == "pultrusion":
        process_text = " ".join(
            norm(row.get(col, ""))
            for col in ["recommended_uses", "sizing_compatibility"]
        )
        return 100.0 if "pultrusion" in process_text else 60.0

    return 100.0


# Hexcel epoxy-compatible sizing codes (e.g. "GP", "GS", "G").
EPOXY_SIZING_CODES = re.compile(r"(?<![a-z0-9])(gp|gs|g)(?![a-z0-9])")


def fiber_matrix_fit(row: pd.Series, matrix: Optional[str]) -> float:
    if not matrix:
        return 100.0

    compatibility = norm(row.get("sizing_compatibility", ""))
    sizing = norm(row.get("sizing_options", ""))

    if matrix == "thermoplastic":
        return 100.0 if "unsized" in sizing or "thermoplastic" in compatibility else 45.0

    if has_term(compatibility, matrix.lower()):
        return 100.0

    if matrix == "epoxy" and EPOXY_SIZING_CODES.search(sizing):
        return 95.0

    return 60.0


def certification_fit(row: pd.Series, required: bool) -> float:
    if not required:
        return 100.0

    cert = norm(row.get("certification", ""))
    return 100.0 if cert and cert not in {"not stated", "nan"} else 0.0


def text_matches(value: Any, terms: Iterable[str]) -> bool:
    text = norm(value)
    return any(term.lower() in text for term in terms)


def process_database_score(value: Any, process: Optional[str]) -> float:
    """Score only explicit process-suitability text; no inferred qualification."""
    if not process:
        return 100.0

    text = norm(value)

    aliases = {
        "VARTM / infusion": ["vartm", "vacuum infusion", "infusion", "lri"],
        "RTM": ["rtm", "resin transfer molding"],
        "autoclave": ["autoclave"],
        "OOA / VBO": ["ooa", "out-of-autoclave", "vbo", "vacuum bag only"],
        "press / compression molding": ["press", "compression molding"],
        "filament winding": ["filament winding"],
        "pultrusion": ["pultrusion"],
    }

    terms = aliases.get(process, [process])
    if any(has_term(text, term.lower()) for term in terms):
        return 100.0

    # Unknown/non-explicit suitability is not treated as incompatible.
    return 50.0


def matrix_database_score(value: Any, matrix: Optional[str]) -> float:
    """Score explicit matrix-family information only."""
    if not matrix:
        return 100.0

    text = norm(value)

    aliases = {
        "epoxy": ["epoxy"],
        "thermoplastic": ["thermoplastic", "peek", "pps", "pa", "pekk"],
        "phenolic": ["phenolic"],
        "vinyl ester": ["vinyl ester"],
        "cyanate ester": ["cyanate ester", "cyanate"],
        "BMI": ["bmi", "bismaleimide"],
        "polyimide": ["polyimide"],
        "polycarbonate": ["polycarbonate"],
    }

    terms = aliases.get(matrix, [matrix])
    if any(has_term(text, term.lower()) for term in terms):
        return 100.0

    return 50.0


def certification_database_score(value: Any, required: bool) -> float:
    if not required:
        return 100.0

    text = norm(value)
    if text and text not in {"nan", "not stated"}:
        return 100.0

    return 0.0


def build_prepreg_results(
    prepregs: pd.DataFrame,
    req: Requirements,
    selected_fibers: pd.DataFrame,
) -> pd.DataFrame:
    """Rank prepreg systems independently from the fiber database."""
    if prepregs.empty:
        return pd.DataFrame()

    candidates = prepregs.copy()

    # Hard process/matrix filters are applied only when the database explicitly
    # states suitability. Unknown does not become a false incompatibility.
    if req.process:
        explicit = candidates["process_suitability"].fillna("").astype(str)
        pass_mask = explicit.apply(lambda x: process_database_score(x, req.process) == 100.0)
        known_mask = explicit.str.strip().ne("")
        candidates = candidates.loc[(~known_mask) | pass_mask].copy()

    if req.matrix:
        explicit = candidates["matrix_family"].fillna("").astype(str)
        pass_mask = explicit.apply(lambda x: matrix_database_score(x, req.matrix) == 100.0)
        known_mask = explicit.str.strip().ne("")
        candidates = candidates.loc[(~known_mask) | pass_mask].copy()

    if req.require_certification:
        cert = candidates["qualification_certification"].fillna("").astype(str)
        candidates = candidates.loc[cert.str.strip().ne("")].copy()

    if candidates.empty:
        return pd.DataFrame()

    # Token sets of the selected fibers' product names, e.g. {hextow, as4c}.
    # Matching whole tokens keeps grade "AS4" from claiming fiber "AS4C".
    selected_tokens = [
        tokens(x) for x in selected_fibers.get("Product", pd.Series(dtype=str)).tolist()
    ]

    records = []
    for _, row in candidates.iterrows():
        grade_tokens = tokens(row.get("fiber_grade", ""))

        # A single-token grade (AS4, IM7, T800S) must appear as a whole token
        # in a selected product. Descriptive entries such as
        # "T1100-series IM+ commonly paired" are not explicit grade matches.
        exact_match = len(grade_tokens) == 1 and any(
            grade_tokens <= product for product in selected_tokens
        )

        proc_score = process_database_score(row.get("process_suitability", ""), req.process)
        matrix_score = matrix_database_score(row.get("matrix_family", ""), req.matrix)
        cert_score = certification_database_score(
            row.get("qualification_certification", ""), req.require_certification
        )

        # Explicit fiber-grade match is rewarded; otherwise the system remains
        # a standalone prepreg recommendation rather than claiming compatibility.
        fiber_match_score = 100.0 if exact_match else 50.0

        final = (
            0.40 * proc_score +
            0.30 * matrix_score +
            0.20 * fiber_match_score +
            0.10 * cert_score
        )

        records.append({
            "Rank": 0,
            "Prepreg_ID": row.get("prepreg_id", ""),
            "Manufacturer": row.get("manufacturer", ""),
            "Product_System": row.get("product_system", ""),
            "Matrix": row.get("matrix_family", ""),
            "Fiber_Manufacturer": row.get("fiber_manufacturer", ""),
            "Fiber_Grade": row.get("fiber_grade", ""),
            "Fiber_Form": row.get("fiber_form", ""),
            "FAW_gsm": row.get("fiber_areal_weight_gsm", np.nan),
            "Resin_Content_percent": row.get("resin_content_percent", np.nan),
            "Ply_Thickness_mm": row.get("nominal_cured_ply_thickness_mm", np.nan),
            "Vf_percent": row.get("nominal_fiber_volume_percent", np.nan),
            "Cure_Temperature_C": row.get("cure_temperature_C", np.nan),
            "Tg_C": row.get("Tg_C", np.nan),
            "Process_Suitability": row.get("process_suitability", ""),
            "Qualification": row.get("qualification_certification", ""),
            "Fiber_Match": "EXPLICIT" if exact_match else "NOT ESTABLISHED",
            "Process_Score": round(proc_score, 2),
            "Matrix_Score": round(matrix_score, 2),
            "Fiber_Match_Score": round(fiber_match_score, 2),
            "Certification_Score": round(cert_score, 2),
            "Final_Score": round(final, 2),
            "Source_Document": row.get("source_document", ""),
            "Source_URL": row.get("source_url", ""),
            "Data_Status": row.get("data_status", ""),
        })

    result = pd.DataFrame(records).sort_values(
        ["Final_Score", "Fiber_Match_Score"], ascending=False
    ).reset_index(drop=True)

    result["Rank"] = np.arange(1, len(result) + 1)
    return result


def build_resin_results(resins: pd.DataFrame, req: Requirements) -> pd.DataFrame:
    """Rank resin systems independently from fiber and prepreg databases."""
    if resins.empty:
        return pd.DataFrame()

    candidates = resins.copy()

    if req.process:
        explicit = candidates["process_suitability"].fillna("").astype(str)
        pass_mask = explicit.apply(lambda x: process_database_score(x, req.process) == 100.0)
        known_mask = explicit.str.strip().ne("")
        candidates = candidates.loc[(~known_mask) | pass_mask].copy()

    if req.matrix:
        explicit = candidates["resin_family"].fillna("").astype(str)
        pass_mask = explicit.apply(lambda x: matrix_database_score(x, req.matrix) == 100.0)
        known_mask = explicit.str.strip().ne("")
        candidates = candidates.loc[(~known_mask) | pass_mask].copy()

    if req.require_certification:
        cert = candidates["qualification_certification"].fillna("").astype(str)
        candidates = candidates.loc[cert.str.strip().ne("")].copy()

    if candidates.empty:
        return pd.DataFrame()

    records = []
    for _, row in candidates.iterrows():
        proc_score = process_database_score(row.get("process_suitability", ""), req.process)
        matrix_score = matrix_database_score(row.get("resin_family", ""), req.matrix)
        cert_score = certification_database_score(
            row.get("qualification_certification", ""), req.require_certification
        )

        final = 0.50 * proc_score + 0.40 * matrix_score + 0.10 * cert_score

        records.append({
            "Rank": 0,
            "Resin_ID": row.get("resin_id", ""),
            "Manufacturer": row.get("manufacturer", ""),
            "Product_System": row.get("product_system", ""),
            "Resin_Family": row.get("resin_family", ""),
            "Process_Suitability": row.get("process_suitability", ""),
            "Cure_Type": row.get("cure_type", ""),
            "Viscosity": row.get("viscosity_value", np.nan),
            "Viscosity_Unit": row.get("viscosity_unit", ""),
            "Cure_Temperature_C": row.get("cure_temperature_C", np.nan),
            "Tg_C": row.get("Tg_C", np.nan),
            "Service_Temperature_C": row.get("service_temperature_C", np.nan),
            "Qualification": row.get("qualification_certification", ""),
            "Process_Score": round(proc_score, 2),
            "Matrix_Score": round(matrix_score, 2),
            "Certification_Score": round(cert_score, 2),
            "Final_Score": round(final, 2),
            "Source_Document": row.get("source_document", ""),
            "Source_URL": row.get("source_url", ""),
            "Data_Status": row.get("data_status", ""),
        })

    result = pd.DataFrame(records).sort_values("Final_Score", ascending=False).reset_index(drop=True)
    result["Rank"] = np.arange(1, len(result) + 1)
    return result


def print_system_database_results(
    prepreg_results: pd.DataFrame,
    resin_results: pd.DataFrame,
) -> None:
    print("\n" + "=" * 70)
    print("PREPREG DATABASE RECOMMENDATIONS")
    print("=" * 70)

    if prepreg_results.empty:
        print("No prepreg candidates match the selected process/matrix filters.")
    else:
        for _, r in prepreg_results.head(5).iterrows():
            print(
                f"#{int(r['Rank'])} {r['Manufacturer']} {r['Product_System']} "
                f"— {r['Final_Score']:.1f}/100"
            )
            print(
                f"  Matrix: {r['Matrix']} | Fiber: {r['Fiber_Manufacturer']} "
                f"{r['Fiber_Grade']} | Fiber match: {r['Fiber_Match']}"
            )
            print(
                f"  Process: {r['Process_Suitability']} | "
                f"Cure: {r['Cure_Temperature_C']}°C | Tg: {r['Tg_C']}"
            )

    print("\n" + "=" * 70)
    print("RESIN DATABASE RECOMMENDATIONS")
    print("=" * 70)

    if resin_results.empty:
        print("No resin candidates match the selected process/matrix filters.")
    else:
        for _, r in resin_results.head(5).iterrows():
            print(
                f"#{int(r['Rank'])} {r['Manufacturer']} {r['Product_System']} "
                f"— {r['Final_Score']:.1f}/100"
            )
            print(
                f"  Family: {r['Resin_Family']} | Process: {r['Process_Suitability']} | "
                f"Cure: {r['Cure_Temperature_C']}°C | Tg: {r['Tg_C']}"
            )
            print(
                f"  Viscosity: {r['Viscosity']} {r['Viscosity_Unit']} | "
                f"Qualification: {r['Qualification'] or 'Not stated'}"
            )


def engineering_components(row: pd.Series, req: Requirements) -> Dict[str, float]:
    return {
        "strength": ratio_score(row["tensile_strength_mpa"], req.strength_mpa, True),
        "modulus": ratio_score(row["tensile_modulus_gpa"], req.modulus_gpa, True),
        "elongation": ratio_score(row["ultimate_elongation_percent"], req.elongation_percent, True),
        "density": ratio_score(row["fiber_density_g_cm3"], req.max_density_g_cm3, False),
    }


def engineering_score(row: pd.Series, req: Requirements, app: dict) -> float:
    weights = {
        key: val / sum(app["importance"].values())
        for key, val in app["importance"].items()
    }
    return weighted_mean(engineering_components(row, req), weights)


def lamina_columns(row: pd.Series) -> dict:
    """
    0-degree UD lamina properties for a fiber: published values when the
    literature has them (NCAMP measured preferred), otherwise an estimate
    from lamina_estimator calibrated on published fiber/lamina pairs.
    """
    published = lamina_estimator.published_lamina(row["fiber_id"])
    if published:
        return {
            "Lamina_Xt_MPa": published["lamina_tensile_strength_mpa"],
            "Lamina_E1_GPa": published["lamina_tensile_modulus_gpa"],
            "Lamina_Basis": f"published ({published['source_type']}, {published['resin']})",
            "Lamina_Source": published["source_document"],
        }

    model = lamina_estimator.calibrated_model()
    if model is None:
        return {"Lamina_Xt_MPa": np.nan, "Lamina_E1_GPa": np.nan,
                "Lamina_Basis": "", "Lamina_Source": ""}

    est = model.estimate(row["tensile_strength_mpa"], row["tensile_modulus_gpa"])
    return {
        "Lamina_Xt_MPa": round(est["Xt_MPa"], 0),
        "Lamina_E1_GPa": round(est["E1_GPa"], 1),
        "Lamina_Basis": (f"estimate ~60% Vf epoxy (±{model.strength_rmse_mpa:.0f} MPa, "
                         f"±{model.modulus_rmse_gpa:.0f} GPa; n={model.n_points})"
                         + (" — EXTRAPOLATED beyond calibration range" if est["extrapolated"] else "")),
        "Lamina_Source": "lamina_estimator.py calibrated on literature_data/",
    }


def build_ranked_results(df: pd.DataFrame, req: Requirements, app: dict) -> pd.DataFrame:
    candidates = numerical_filter(df, req)

    if req.require_certification:
        cert_mask = candidates["certification"].fillna("").astype(str).str.strip().ne("")
        candidates = candidates.loc[cert_mask].copy()

    if candidates.empty:
        return pd.DataFrame()

    records = []
    for _, row in candidates.iterrows():
        eng = engineering_score(row, req, app)
        app_score = application_fit(row, app)
        grade_score_value = grade_fit(row, app["name"])
        proc = process_fit(row, req.process)
        matrix = fiber_matrix_fit(row, req.matrix)
        cert = certification_fit(row, req.require_certification)

        final = (
            0.70 * eng +
            0.08 * app_score +
            0.06 * grade_score_value +
            0.08 * proc +
            0.06 * matrix +
            0.02 * cert
        )

        records.append({
            "Fiber_ID": row["fiber_id"],
            "Manufacturer": row["manufacturer"],
            "Product": row["product"],
            "Strength_MPa": row["tensile_strength_mpa"],
            "Modulus_GPa": row["tensile_modulus_gpa"],
            "Density_g_cm3": row["fiber_density_g_cm3"],
            "Elongation_percent": row["ultimate_elongation_percent"],
            "Tow_or_Sizing": row.get("sizing_options", ""),
            "Fiber_Class": row.get("fiber_class", ""),
            "Certification": row.get("certification", ""),
            "Engineering_Score": round(eng, 2),
            "Data_Completeness_percent": round(data_completeness(engineering_components(row, req)), 0),
            "Application_Fit": round(app_score, 2),
            "Grade_Fit": round(grade_score_value, 2),
            "Process_Fit": round(proc, 2),
            "Matrix_Fit": round(matrix, 2),
            "Certification_Fit": round(cert, 2),
            "Final_Score": round(final, 2),
            "Source_File": row.get("source_file", ""),
            "Source_URL": row.get("source_url", ""),
            "Data_Status": row.get("fiber_data_status", ""),
            **lamina_columns(row),
        })

    result = pd.DataFrame(records).sort_values("Final_Score", ascending=False).reset_index(drop=True)

    if not result.empty:
        result["Rank"] = np.arange(1, len(result) + 1)
        result["Relative_Score_percent"] = (
            100.0 * result["Final_Score"] / result["Final_Score"].max()
        ).round(1)

    return result


def print_results(result: pd.DataFrame, req: Requirements, app: dict, all_fibers: pd.DataFrame) -> None:
    print("\n" + "=" * 70)
    print("TOP FIBER RECOMMENDATIONS")
    print("=" * 70)

    print(
        f"\nApplication: {app['name']}\n"
        f"Process: {req.process or 'None'}\n"
        f"Matrix: {req.matrix or 'None'}"
    )

    if result.empty:
        print("\nNO CANDIDATE SATISFIES THE HARD REQUIREMENTS.")
        print_constraint_diagnostics(all_fibers, req)
        return

    for _, r in result.head(5).iterrows():
        print(
            f"\n#{int(r['Rank'])} {r['Manufacturer']} {r['Product']} "
            f"— {r['Relative_Score_percent']:.1f}%"
        )
        print(
            f"  Strength: {r['Strength_MPa']:.0f} MPa | "
            f"Modulus: {r['Modulus_GPa']:.0f} GPa | "
            f"Density: {r['Density_g_cm3']:.2f} g/cm³ | "
            f"Elongation: {r['Elongation_percent']:.1f}%"
        )
        print(
            f"  Engineering: {r['Engineering_Score']:.1f} | "
            f"Application: {r['Application_Fit']:.1f} | "
            f"Process: {r['Process_Fit']:.1f} | "
            f"Matrix: {r['Matrix_Fit']:.1f}"
        )
        if r["Data_Completeness_percent"] < 100:
            print(
                f"  Data completeness: {r['Data_Completeness_percent']:.0f}% — "
                f"unpublished properties score 0"
            )
        print(f"  Fiber class: {r['Fiber_Class']}")
        print(f"  Sizing: {r['Tow_or_Sizing']}")
        print(f"  Certification: {r['Certification'] or 'Not stated'}")
        if pd.notna(r.get("Lamina_Xt_MPa")):
            print(
                f"  UD lamina 0°: Xt {r['Lamina_Xt_MPa']:.0f} MPa | "
                f"E1 {r['Lamina_E1_GPa']:.0f} GPa — {r['Lamina_Basis']}"
            )


def ask_float(prompt: str, minimum: float = 0.0) -> float:
    while True:
        try:
            value = float(input(prompt))
            if not np.isfinite(value) or value < minimum:
                raise ValueError
            return value
        except ValueError:
            print(f"Enter a number >= {minimum}.")


def ask_choice(prompt: str, options: dict) -> str:
    """Repeat until the answer is one of the menu keys."""
    while True:
        choice = input(prompt).strip()
        if choice in options:
            return choice
        print(f"Choose one of: {', '.join(options)}.")


def ask_judgment(a: str, b: str) -> float:
    """Ask one AHP pairwise judgment; accepts 1-9 or reciprocals like 1/3."""
    prompt = (
        f"{a.capitalize()} vs {b.capitalize()} "
        f"[1-9 if {a} is more important, 1/2-1/9 if {b} is]: "
    )
    while True:
        text = input(prompt).strip().replace(" ", "")
        try:
            if "/" in text:
                num, den = text.split("/", 1)
                value = float(num) / float(den)
            else:
                value = float(text)
            if 1 / 9 - 1e-9 <= value <= 9 + 1e-9:
                return value
        except (ValueError, ZeroDivisionError):
            pass
        print("Enter a value from 1 to 9, or a reciprocal such as 1/3.")


def ask_custom_judgments() -> Dict[tuple, float]:
    """Ask all pairwise judgments, repeating until they are consistent."""
    print("\nAHP PAIRWISE COMPARISON (Saaty scale)")
    print("1 = equal, 3 = moderate, 5 = strong, 7 = very strong, 9 = extreme")

    while True:
        values = {(a, b): ask_judgment(a, b) for a, b in CRITERIA_PAIRS}
        result = ahp_weights(values)
        if result.consistent:
            return values

        print(
            f"\nInconsistent judgments: CR = {result.consistency_ratio:.3f} "
            f"(must be < {CR_THRESHOLD:.2f})."
        )
        if not ask_yes_no("Re-enter the comparisons? "):
            print("Proceeding with inconsistent weights — treat results with caution.")
            return values


def print_ahp_weights(app_name: str, result: AhpResult) -> None:
    print("\n" + "=" * 70)
    print(f"AHP IMPORTANCE WEIGHTS — {app_name}")
    print("=" * 70)
    for criterion in CRITERIA:
        weight = result.weights[criterion]
        print(f"  {criterion.capitalize():<12} {weight:6.3f}  {'#' * round(weight * 40)}")
    status = "consistent" if result.consistent else "INCONSISTENT"
    print(
        f"  lambda_max = {result.lambda_max:.3f} | CI = {result.consistency_index:.3f} "
        f"| CR = {result.consistency_ratio:.3f} ({status}, threshold {CR_THRESHOLD:.2f})"
    )


def ask_yes_no(prompt: str) -> bool:
    while True:
        answer = input(prompt).strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Enter yes or no.")


def main() -> None:
    print("\n" + "=" * 70)
    print(" COMPOSITE MATERIAL RECOMMENDATION ENGINE v4")
    print("=" * 70)

    fibers = load_fiber_database()
    prepregs = load_prepreg_database()
    resins = load_resin_database()

    print(f"\nLoaded {len(fibers)} carbon-fiber grades from the fiber database.")
    print(f"Loaded {len(prepregs)} prepreg systems from the prepreg database.")
    print(f"Loaded {len(resins)} resin systems from the resin database.")

    print("\nAPPLICATION")
    for key, value in APPLICATIONS.items():
        print(f"{key}. {value['name']}")

    choice = ask_choice("Choose application: ", APPLICATIONS)

    app = APPLICATIONS[choice].copy()

    if choice == "6":
        app["ahp_judgments"] = ask_custom_judgments()

    ahp = ahp_weights(app["ahp_judgments"])
    app["importance"] = ahp.weights
    print_ahp_weights(app["name"], ahp)

    print("\nENGINEERING REQUIREMENTS")
    req = Requirements(
        strength_mpa=ask_float("Minimum tensile strength (MPa): "),
        modulus_gpa=ask_float("Minimum tensile modulus (GPa): "),
        max_density_g_cm3=ask_float("Maximum density (g/cm³): ", 0.01),
        elongation_percent=ask_float("Minimum elongation (%): "),
        hard_strength=ask_yes_no("Strength is HARD? "),
        hard_modulus=ask_yes_no("Modulus is HARD? "),
        hard_density=ask_yes_no("Density is HARD? "),
        hard_elongation=ask_yes_no("Elongation is HARD? "),
        process=None,
        matrix=None,
        require_certification=False,
    )

    print("\nPROCESS")
    for key, name in PROCESS_OPTIONS.items():
        print(f"{key}. {name or 'No process preference'}")
    req.process = PROCESS_OPTIONS[ask_choice("Choose process: ", PROCESS_OPTIONS)]

    print("\nMATRIX")
    for key, name in MATRIX_OPTIONS.items():
        print(f"{key}. {name or 'No matrix preference'}")
    req.matrix = MATRIX_OPTIONS[ask_choice("Choose matrix: ", MATRIX_OPTIONS)]

    req.require_certification = ask_yes_no(
        "\nRequire an explicitly stated certification? "
    )

    result = build_ranked_results(fibers, req, app)
    print_results(result, req, app, fibers)

    if not result.empty:
        export = ask_yes_no("\nExport complete fiber ranking to CSV? ")
        if export:
            out = BASE_DIR / "recommendation_results_fiber_v4.csv"
            result.to_csv(out, index=False)
            print(f"Saved: {out}")

    # IMPORTANT: These are independent database rankings.
    # No complete fiber+prepreg+resin compatibility is claimed here.
    prepreg_result = build_prepreg_results(prepregs, req, result.head(5))
    resin_result = build_resin_results(resins, req)

    print_system_database_results(prepreg_result, resin_result)

    print(
        "\nNOTE: A prepreg/resin appearing here is a database-level candidate, "
        "not proof of manufacturer-qualified compatibility with the selected fiber."
    )


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled — no input received.")
        raise SystemExit(1)
