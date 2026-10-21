"""
Generic Analytic Hierarchy Process (AHP) for any number of criteria.

Used by the mold selector's application profiles. The fiber recommender
(updated_database_recommender_v4.py) keeps its own 4-criteria version.

    weights, cr = ahp(["a", "b", "c"], {("a", "b"): 3, ("a", "c"): 5, ("b", "c"): 2})
"""

from __future__ import annotations

from typing import Dict, Sequence, Tuple

import numpy as np

# Saaty's random consistency index by matrix size.
RANDOM_INDEX = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12,
                6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}
CR_THRESHOLD = 0.10


def ahp(criteria: Sequence[str], judgments: Dict[Tuple[str, str], float]) -> Tuple[Dict[str, float], float]:
    """
    Weights (principal eigenvector, summing to 1) and consistency ratio.

    `judgments[(a, b)]` = how much more important a is than b on Saaty's
    1-9 scale (1/x when b is more important). Every unordered pair must be
    given exactly once.
    """
    n = len(criteria)
    index = {c: i for i, c in enumerate(criteria)}
    expected = n * (n - 1) // 2
    if len(judgments) != expected:
        raise ValueError(f"Expected {expected} pairwise judgments, got {len(judgments)}.")

    matrix = np.ones((n, n))
    for (a, b), value in judgments.items():
        if value <= 0:
            raise ValueError(f"Judgment {a} vs {b} must be positive.")
        i, j = index[a], index[b]
        matrix[i, j], matrix[j, i] = value, 1.0 / value

    eigenvalues, eigenvectors = np.linalg.eig(matrix)
    k = int(np.argmax(eigenvalues.real))
    vector = np.abs(eigenvectors[:, k].real)
    weights = vector / vector.sum()

    lambda_max = float(eigenvalues[k].real)
    ci = max(0.0, (lambda_max - n) / (n - 1)) if n > 1 else 0.0
    ri = RANDOM_INDEX.get(n, 1.49)
    cr = ci / ri if ri > 0 else 0.0
    return dict(zip(criteria, (float(w) for w in weights))), cr
