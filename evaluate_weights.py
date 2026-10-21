"""
Robust evaluation + weight learning for the v4 recommender.

What it does
------------
For each application (Aerospace, Industrial) it runs N independent trials
(default 100). Every trial:

  1. Samples a random requirement scenario (strength / modulus / density /
     elongation targets drawn from the database's own 25th-75th percentiles),
     so results don't hinge on one hand-picked set of targets.
  2. Builds the four v4 engineering component scores (ratio_score, 0-100)
     for every fiber that has all four properties.
  3. Splits fibers 70/30 into train/test, stratified by label.
  4. Compares three weight sets on the held-out test fibers:
       - hand:    the original v4 importance numbers (e.g. 9/10/10/6)
       - ahp:     the AHP-derived weights now used by v4
       - learned: AHP weights updated by gradient descent on the train split
     Each weight set's score is calibrated to a probability with a 1-D
     logistic fit on the train split, so MSE/RMSE compare fairly.

Ground truth
------------
There is no measured performance data yet (Simulation_Results_v1.csv is
empty), so the label is the MANUFACTURER-STATED intended use: a fiber is
"positive" for an application when its recommended_uses / market_or_grade /
fiber_class text names that application. This is a weak label (marketing
positioning, not test results) — treat learned weights as a data-informed
adjustment of the AHP prior, not as validated engineering truth.

Outputs
-------
  evaluation_results_v4.csv   per-trial metrics for every weight set
  learned_weights_v4.json     mean +/- std learned weights per application
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import updated_database_recommender_v4 as v4  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
N_TRIALS = 100
TRAIN_FRACTION = 0.70
SEED = 42
# Pull of learned weights back toward the AHP prior. Higher = trust AHP more.
# With ~20 training rows per application, 0.05 keeps weights stable; lower it
# (e.g. 0.01) once there are more rated scenarios. Properties that barely vary
# in the data (density: every carbon fiber is ~1.8 g/cm3) carry almost no
# signal, so their learned weight stays near the AHP value by design.
LEARN_L2 = 0.05
# Gradient step size. A 100-trial sweep (0.3 / 1 / 3 × L2 0.05 / 0.01 / 0.001,
# confirmed on fresh trials) gave identical results for every rate; 3.0
# converges in ~100 iterations instead of ~1600 (6× faster run).
LEARN_RATE = 3.0

PROPERTY_COLUMNS = {
    "strength": "tensile_strength_mpa",
    "modulus": "tensile_modulus_gpa",
    "density": "fiber_density_g_cm3",
    "elongation": "ultimate_elongation_percent",
}

# Original hand-typed v4 importances, kept for comparison.
HAND_WEIGHTS = {
    "Aerospace": {"strength": 9, "modulus": 10, "density": 10, "elongation": 6},
    "Industrial": {"strength": 8, "modulus": 7, "density": 7, "elongation": 6},
    "Automotive / Motorsport": {"strength": 8, "modulus": 8, "density": 9, "elongation": 7},
    "Pressure Vessel / Energy": {"strength": 10, "modulus": 8, "density": 8, "elongation": 8},
    "Sporting Goods": {"strength": 7, "modulus": 9, "density": 9, "elongation": 7},
}

APPLICATION_KEYS = {"Aerospace": "1", "Industrial": "5"}
LABEL_TERMS = {"Aerospace": ["aerospace"], "Industrial": ["industrial"]}


# ------------------------------------------------------------
# Data
# ------------------------------------------------------------

def load_fibers() -> pd.DataFrame:
    fibers = v4.load_fiber_database()
    return fibers.dropna(subset=list(PROPERTY_COLUMNS.values())).reset_index(drop=True)


def labels_for(fibers: pd.DataFrame, application: str) -> np.ndarray:
    text = (
        fibers["recommended_uses"].fillna("") + " "
        + fibers["market_or_grade"].fillna("") + " "
        + fibers["fiber_class"].fillna("")
    ).str.lower()
    terms = LABEL_TERMS[application]
    return text.apply(lambda t: any(term in t for term in terms)).astype(int).to_numpy()


def sample_targets(fibers: pd.DataFrame, rng: np.random.Generator) -> dict:
    targets = {}
    for name, col in PROPERTY_COLUMNS.items():
        lo, hi = np.percentile(fibers[col], [25, 75])
        targets[name] = float(rng.uniform(lo, hi))
    return targets


def component_matrix(fibers: pd.DataFrame, targets: dict) -> np.ndarray:
    """v4 ratio_score for each property, scaled to 0-1. Columns follow CRITERIA."""
    cols = []
    for name in v4.CRITERIA:
        higher_is_better = name != "density"
        cols.append([
            v4.ratio_score(x, targets[name], higher_is_better) / 100.0
            for x in fibers[PROPERTY_COLUMNS[name]]
        ])
    return np.array(cols).T


def stratified_split(y: np.ndarray, rng: np.random.Generator):
    train = []
    for cls in np.unique(y):
        idx = rng.permutation(np.flatnonzero(y == cls))
        train.extend(idx[: max(1, round(TRAIN_FRACTION * len(idx)))])
    train = np.array(sorted(train))
    test = np.setdiff1d(np.arange(len(y)), train)
    return train, test


# ------------------------------------------------------------
# Models
# ------------------------------------------------------------

def sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -50, 50)))


CALIBRATION_RIDGE = 1e-3   # keeps the slope finite when train labels are separable


def fit_calibration(s: np.ndarray, y: np.ndarray, iters: int = 50, tol: float = 1e-10):
    """
    Fit p = sigmoid(a * z + b) on standardized score z (weights fixed).

    Two-parameter logistic regression solved by Newton's method: converges in
    ~5-10 iterations instead of thousands of gradient steps.
    """
    mu, sd = s.mean(), s.std() or 1.0
    Z = np.column_stack([(s - mu) / sd, np.ones_like(s)])
    params = np.zeros(2)
    ridge = np.diag([CALIBRATION_RIDGE, 0.0])
    for _ in range(iters):
        p = sigmoid(Z @ params)
        grad = Z.T @ (p - y) / len(y) + ridge @ params
        hess = (Z * (p * (1 - p))[:, None]).T @ Z / len(y) + ridge + 1e-12 * np.eye(2)
        step = np.linalg.solve(hess, grad)
        params -= step
        if np.max(np.abs(step)) < tol:
            break
    a, b = params
    return lambda s_new: sigmoid(a * (s_new - mu) / sd + b)


def learn_weights(X: np.ndarray, y: np.ndarray, prior: np.ndarray,
                  iters: int = 6000, lr: float = LEARN_RATE, l2: float = LEARN_L2,
                  tol: float = 1e-7) -> np.ndarray:
    """
    Update AHP weights by minimizing log-loss.

    Weights stay positive and sum to 1 via a softmax over theta; theta is
    initialized at log(prior) and L2-pulled back toward it, so the result
    is "AHP prior, adjusted by data" rather than an unconstrained fit.
    """
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1.0
    Xs = (X - mu) / sd                                # comparable scales
    # Start exactly at the AHP prior: raw weight w_raw ∝ w_std / sd.
    start = prior * sd
    theta0 = np.log(start / start.sum())
    theta = theta0.copy()
    a, b = 1.0, 0.0
    # Hot loop (~1000+ steps per call): use ndarray methods and precomputed
    # constants instead of np.mean/np.clip wrappers, which dominated runtime.
    inv_n = 1.0 / len(y)
    XsT = np.ascontiguousarray(Xs.T)
    for _ in range(iters):
        e = np.exp(theta - theta.max())
        w = e / e.sum()
        s = Xs @ w
        z = a * s + b
        np.clip(z, -50.0, 50.0, out=z)
        g = 1.0 / (1.0 + np.exp(-z)) - y              # dLoss/dz
        grad_w = (a * inv_n) * (XsT @ g)
        grad_theta = w * (grad_w - w @ grad_w) + l2 * (theta - theta0)
        grad_a = (g @ s) * inv_n
        grad_b = g.sum() * inv_n
        theta -= lr * grad_theta
        a -= lr * grad_a
        b -= lr * grad_b
        # Stop once converged instead of always running every iteration.
        if abs(grad_a) < tol and abs(grad_b) < tol and np.abs(grad_theta).max() < tol:
            break
    # Convert back to weights on the ORIGINAL 0-1 component scale, which is
    # what v4's weighted_mean uses: standardization divides by sd.
    w = np.exp(theta) / np.exp(theta).sum()
    w_raw = w / sd
    return w_raw / w_raw.sum()


# ------------------------------------------------------------
# Metrics
# ------------------------------------------------------------

def auc(y: np.ndarray, p: np.ndarray) -> float:
    pos, neg = y.sum(), len(y) - y.sum()
    if pos == 0 or neg == 0:
        return np.nan
    ranks = pd.Series(p).rank().to_numpy()
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg))


def precision_at_k(y: np.ndarray, p: np.ndarray, k: int = 5) -> float:
    top = np.argsort(-p, kind="stable")[:k]
    return float(y[top].mean())


def ndcg_at_k(y: np.ndarray, p: np.ndarray, k: int = 10) -> float:
    order = np.argsort(-p, kind="stable")[:k]
    disc = 1.0 / np.log2(np.arange(2, len(order) + 2))
    dcg = float((y[order] * disc).sum())
    ideal = float((np.sort(y)[::-1][: len(order)] * disc).sum())
    return dcg / ideal if ideal > 0 else np.nan


def metrics(y: np.ndarray, p: np.ndarray) -> dict:
    err = p - y
    eps = 1e-12
    return {
        "MSE": float(np.mean(err ** 2)),
        "RMSE": float(np.sqrt(np.mean(err ** 2))),
        "MAE": float(np.mean(np.abs(err))),
        "LogLoss": float(-np.mean(y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))),
        "Accuracy": float(np.mean((p >= 0.5) == y)),
        "AUC": auc(y, p),
        "P@5": precision_at_k(y, p, 5),
        "NDCG@10": ndcg_at_k(y, p, 10),
    }


# ------------------------------------------------------------
# Experiment
# ------------------------------------------------------------

def weight_vector(weights: dict) -> np.ndarray:
    w = np.array([weights[c] for c in v4.CRITERIA], dtype=float)
    return w / w.sum()


def run(n_trials: int = N_TRIALS, lr: float = LEARN_RATE, l2: float = LEARN_L2,
        seed: int = SEED) -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(seed)
    fibers = load_fibers()
    rows, learned_summary = [], {}

    for application, key in APPLICATION_KEYS.items():
        y = labels_for(fibers, application)
        ahp = v4.ahp_weights(v4.APPLICATIONS[key]["ahp_judgments"])
        ahp_w = weight_vector(ahp.weights)
        hand_w = weight_vector(HAND_WEIGHTS[application])
        learned_all = []

        for trial in range(1, n_trials + 1):
            targets = sample_targets(fibers, rng)
            X = component_matrix(fibers, targets)
            train, test = stratified_split(y, rng)

            learned_w = learn_weights(X[train], y[train], ahp_w, lr=lr, l2=l2)
            learned_all.append(learned_w)

            # Reference: ignore the fibers, always predict the train base rate.
            base = np.full(len(test), y[train].mean())
            rows.append({"application": application, "trial": trial,
                         "weights": "baseline", **metrics(y[test], base)})

            for name, w in [("hand", hand_w), ("ahp", ahp_w), ("learned", learned_w)]:
                score = X @ w                                  # v4 engineering score / 100
                calibrate = fit_calibration(score[train], y[train])
                m = metrics(y[test], calibrate(score[test]))
                rows.append({"application": application, "trial": trial,
                             "weights": name, **m})

        learned_all = np.array(learned_all)
        learned_summary[application] = {
            "labels": {"positive": int(y.sum()), "total": int(len(y))},
            "ahp_weights": dict(zip(v4.CRITERIA, np.round(ahp_w, 4).tolist())),
            "learned_weights_mean": dict(zip(v4.CRITERIA, np.round(learned_all.mean(0), 4).tolist())),
            "learned_weights_std": dict(zip(v4.CRITERIA, np.round(learned_all.std(0), 4).tolist())),
        }

    return pd.DataFrame(rows), learned_summary


def print_report(results: pd.DataFrame, learned: dict, n_trials: int) -> None:
    metric_cols = ["MSE", "RMSE", "MAE", "LogLoss", "Accuracy", "AUC", "P@5", "NDCG@10"]
    for application, info in learned.items():
        print("\n" + "=" * 78)
        print(f"{application.upper()} — {n_trials} trials, test split, "
              f"labels {info['labels']['positive']}/{info['labels']['total']} positive")
        print("=" * 78)
        sub = results[results["application"] == application]
        mean = sub.groupby("weights")[metric_cols].mean().loc[["baseline", "hand", "ahp", "learned"]]
        std = sub.groupby("weights")[metric_cols].std().loc[["baseline", "hand", "ahp", "learned"]]
        table = mean.round(3).astype(str) + " ± " + std.round(3).astype(str)
        print(table.to_string())

        print("\nWeights        " + "  ".join(f"{c:>12}" for c in v4.CRITERIA))
        print("AHP            " + "  ".join(f"{info['ahp_weights'][c]:>12.3f}" for c in v4.CRITERIA))
        print("Learned (mean) " + "  ".join(
            f"{info['learned_weights_mean'][c]:>6.3f}±{info['learned_weights_std'][c]:.3f}"
            for c in v4.CRITERIA))

    print("\nNOTE: labels are manufacturer-stated intended uses (weak labels), not "
          "measured performance. Simulation_Results_v1.csv is empty.")


# ------------------------------------------------------------
# Expert-rating mode (labels from expert_ratings.csv, 1-5 scale)
# ------------------------------------------------------------

TARGET_COLUMNS = {
    "strength": "target_min_strength_mpa",
    "modulus": "target_min_modulus_gpa",
    "density": "target_max_density_g_cm3",
    "elongation": "target_min_elongation_percent",
}
FIBER_COLUMNS = {
    "strength": "strength_mpa",
    "modulus": "modulus_gpa",
    "density": "density_g_cm3",
    "elongation": "elongation_percent",
}
GOOD_RATING = 4  # rating >= 4 counts as a "good pick" for P@3


def load_expert_ratings(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["expert_rating"] = pd.to_numeric(df["expert_rating"], errors="coerce")
    rated = df.dropna(subset=["expert_rating"]).copy()
    bad = rated[~rated["expert_rating"].between(1, 5)]
    if not bad.empty:
        raise ValueError(f"expert_rating must be 1-5; bad rows: {bad.index.tolist()}")
    if rated.empty:
        raise ValueError(f"No ratings filled in {path.name} — see EXPERT_RATING_GUIDE.md.")
    return rated.reset_index(drop=True)


def expert_components(df: pd.DataFrame) -> np.ndarray:
    """v4 component scores (0-1), each row against its own scenario targets."""
    cols = []
    for name in v4.CRITERIA:
        higher_is_better = name != "density"
        cols.append([
            v4.ratio_score(x, t, higher_is_better) / 100.0
            for x, t in zip(df[FIBER_COLUMNS[name]], df[TARGET_COLUMNS[name]])
        ])
    return np.array(cols).T


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 2:
        return np.nan
    ra, rb = pd.Series(a).rank(), pd.Series(b).rank()
    if ra.std() == 0 or rb.std() == 0:
        return np.nan
    return float(ra.corr(rb))


def expert_metrics(rating: np.ndarray, predicted: np.ndarray, scenarios: np.ndarray) -> dict:
    err = predicted - rating
    rho, ndcg, p3 = [], [], []
    for s in np.unique(scenarios):
        m = scenarios == s
        rho.append(spearman(rating[m], predicted[m]))
        ndcg.append(ndcg_at_k(rating[m] - 1, predicted[m], 3))    # graded gain 0-4
        p3.append(precision_at_k((rating[m] >= GOOD_RATING).astype(int), predicted[m], 3))
    return {
        "MSE": float(np.mean(err ** 2)),
        "RMSE": float(np.sqrt(np.mean(err ** 2))),
        "MAE": float(np.mean(np.abs(err))),
        "Spearman": float(np.nanmean(rho)) if not np.all(np.isnan(rho)) else np.nan,
        "NDCG@3": float(np.nanmean(ndcg)) if not np.all(np.isnan(ndcg)) else np.nan,
        "P@3": float(np.nanmean(p3)),
    }


def run_expert(path: Path, n_trials: int = N_TRIALS) -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(SEED)
    ratings = load_expert_ratings(path)
    key_by_name = {app["name"]: k for k, app in v4.APPLICATIONS.items() if app["ahp_judgments"]}
    rows, learned_summary = [], {}

    for application, sub in ratings.groupby("application", sort=False):
        if application not in key_by_name:
            print(f"Skipping unknown application '{application}'.")
            continue
        sub = sub.reset_index(drop=True)
        X = expert_components(sub)
        rating = sub["expert_rating"].to_numpy(float)
        y = (rating - 1) / 4                                 # 1-5 -> 0-1
        scenarios = sub["scenario_id"].to_numpy()

        ahp_w = weight_vector(v4.ahp_weights(v4.APPLICATIONS[key_by_name[application]]["ahp_judgments"]).weights)
        hand_w = weight_vector(HAND_WEIGHTS[application])
        learned_all = []

        for trial in range(1, n_trials + 1):
            idx = rng.permutation(len(sub))
            n_train = max(2, round(TRAIN_FRACTION * len(sub)))
            train, test = np.sort(idx[:n_train]), np.sort(idx[n_train:])
            if len(test) == 0:
                continue

            learned_w = learn_weights(X[train], y[train], ahp_w)
            learned_all.append(learned_w)

            base = np.full(len(test), rating[train].mean())
            rows.append({"application": application, "trial": trial, "weights": "baseline",
                         **expert_metrics(rating[test], base, scenarios[test])})

            for name, w in [("hand", hand_w), ("ahp", ahp_w), ("learned", learned_w)]:
                score = X @ w
                calibrate = fit_calibration(score[train], y[train])
                predicted = 1 + 4 * calibrate(score[test])   # back to 1-5
                rows.append({"application": application, "trial": trial, "weights": name,
                             **expert_metrics(rating[test], predicted, scenarios[test])})

        learned_all = np.array(learned_all)
        learned_summary[application] = {
            "rated_rows": int(len(sub)),
            "scenarios": int(sub["scenario_id"].nunique()),
            "ahp_weights": dict(zip(v4.CRITERIA, np.round(ahp_w, 4).tolist())),
            "learned_weights_mean": dict(zip(v4.CRITERIA, np.round(learned_all.mean(0), 4).tolist())),
            "learned_weights_std": dict(zip(v4.CRITERIA, np.round(learned_all.std(0), 4).tolist())),
        }

    return pd.DataFrame(rows), learned_summary


def print_expert_report(results: pd.DataFrame, learned: dict, n_trials: int) -> None:
    metric_cols = ["MSE", "RMSE", "MAE", "Spearman", "NDCG@3", "P@3"]
    order = ["baseline", "hand", "ahp", "learned"]
    for application, info in learned.items():
        print("\n" + "=" * 78)
        print(f"{application.upper()} — {n_trials} trials, {info['rated_rows']} rated rows "
              f"in {info['scenarios']} scenarios (errors in rating points, 1-5 scale)")
        print("=" * 78)
        sub = results[results["application"] == application]
        mean = sub.groupby("weights")[metric_cols].mean().loc[order]
        std = sub.groupby("weights")[metric_cols].std().loc[order]
        print((mean.round(3).astype(str) + " ± " + std.round(3).astype(str)).to_string())

        print("\nWeights        " + "  ".join(f"{c:>12}" for c in v4.CRITERIA))
        print("AHP            " + "  ".join(f"{info['ahp_weights'][c]:>12.3f}" for c in v4.CRITERIA))
        print("Learned (mean) " + "  ".join(
            f"{info['learned_weights_mean'][c]:>6.3f}±{info['learned_weights_std'][c]:.3f}"
            for c in v4.CRITERIA))


def main() -> None:
    args = sys.argv[1:]
    expert_path = None
    if "--expert" in args:
        i = args.index("--expert")
        expert_path = Path(args[i + 1]) if i + 1 < len(args) else BASE_DIR / "expert_ratings.csv"
        del args[i:i + 2]
    n_trials = int(args[0]) if args else N_TRIALS

    if expert_path:
        results, learned = run_expert(expert_path, n_trials)
        print_expert_report(results, learned, n_trials)
        stem = "expert"
    else:
        results, learned = run(n_trials)
        print_report(results, learned, n_trials)
        stem = "v4"

    results.to_csv(BASE_DIR / f"evaluation_results_{stem}.csv", index=False)
    with open(BASE_DIR / f"learned_weights_{stem}.json", "w", encoding="utf-8") as fh:
        json.dump(learned, fh, indent=2)
    print(f"\nSaved: evaluation_results_{stem}.csv, learned_weights_{stem}.json")


if __name__ == "__main__":
    main()
