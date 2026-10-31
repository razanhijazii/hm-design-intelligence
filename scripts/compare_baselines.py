"""Check that the demand model beats simple baselines on the same holdout.

Uses the same time-based split as training (the latest 20% of launches).
Run from the repo root:  python scripts/compare_baselines.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_percentage_error, r2_score

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.services import demand  # noqa: E402


def score(name: str, y_true: np.ndarray, pred: np.ndarray) -> dict:
    return {
        "model": name,
        "r2": round(float(r2_score(y_true, pred)), 3),
        "mape": round(float(mean_absolute_percentage_error(y_true, pred)), 3),
    }


def main() -> list[dict]:
    X, y, launch = demand.training_frame()
    cutoff = np.quantile(launch, 0.8)
    train, test = launch <= cutoff, launch > cutoff
    names = list(demand.FEATURES)
    garment_cols = [names.index(f"garment_{g}") for g in demand.GARMENTS]
    week_col = names.index("weeks_since_launch")

    results = []

    # 1. Predict the average weekly units of every training row.
    results.append(score("Overall average", y[test], np.full(test.sum(), y[train].mean())))

    # 2. Average by garment type and weeks since launch (a naive sales curve).
    garment = X[:, garment_cols].argmax(axis=1)
    weeks = X[:, week_col].astype(int)
    table: dict[tuple[int, int], float] = {}
    for g in range(len(garment_cols)):
        for w in np.unique(weeks):
            m = train & (garment == g) & (weeks == w)
            if m.any():
                table[(g, w)] = y[m].mean()
    fallback = y[train].mean()
    curve = np.array([table.get((g, w), fallback) for g, w in zip(garment[test], weeks[test])])
    results.append(score("Average by garment and week", y[test], curve))

    # 3. Linear regression on the same features as the forest.
    lin = LinearRegression().fit(X[train], y[train])
    results.append(score("Linear regression", y[test], lin.predict(X[test])))

    # 4. The model the project uses.
    params = dict(n_estimators=300, min_samples_leaf=3, random_state=config.RANDOM_SEED, n_jobs=-1)
    rf = RandomForestRegressor(**params).fit(X[train], y[train])
    results.append(score("Random forest (used)", y[test], rf.predict(X[test])))
    return results


if __name__ == "__main__":
    print(f"{'Model':<32}{'R2':>8}{'MAPE':>8}")
    for r in main():
        print(f"{r['model']:<32}{r['r2']:>8}{r['mape']:>8}")
