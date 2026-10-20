"""Quantile gradient boosting on log(days) + split-conformal recalibration (CQR)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from kessler.reentry.dataset import FEATURES

QUANTILES = (0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95)
LEVELS = {0.5: (0.25, 0.75), 0.8: (0.1, 0.9), 0.9: (0.05, 0.95)}
MODEL_VERSION = "hgb-quantile-cqr-1"


@dataclass
class QuantileModel:
    models: dict[float, HistGradientBoostingRegressor] = field(default_factory=dict)
    conformal: dict[float, float] = field(default_factory=dict)  # level -> additive margin in log-days

    def fit(self, X: pd.DataFrame, y_days: np.ndarray, seed: int = 0) -> QuantileModel:
        y = np.log(y_days)
        for q in QUANTILES:
            m = HistGradientBoostingRegressor(
                loss="quantile", quantile=q, max_iter=300, learning_rate=0.06, max_leaf_nodes=31,
                min_samples_leaf=20, l2_regularization=1.0, random_state=seed,
            )
            m.fit(X[FEATURES], y)
            self.models[q] = m
        return self

    def predict_log(self, X: pd.DataFrame) -> dict[float, np.ndarray]:
        P = {q: m.predict(X[FEATURES]) for q, m in self.models.items()}
        # enforce monotone quantiles
        qs = sorted(P)
        stack = np.sort(np.vstack([P[q] for q in qs]), axis=0)
        return {q: stack[i] for i, q in enumerate(qs)}

    def calibrate(self, X: pd.DataFrame, y_days: np.ndarray) -> None:
        """Split-conformal: widen each central interval by the finite-sample quantile of its scores."""
        y = np.log(y_days)
        P = self.predict_log(X)
        n = len(y)
        for level, (lo, hi) in LEVELS.items():
            s = np.maximum(P[lo] - y, y - P[hi])
            k = min(1.0, np.ceil((n + 1) * level) / n)
            self.conformal[level] = float(np.quantile(s, k))

    def interval(self, X: pd.DataFrame, level: float, conformal: bool = True) -> tuple[np.ndarray, np.ndarray]:
        P = self.predict_log(X)
        lo, hi = LEVELS[level]
        m = self.conformal.get(level, 0.0) if conformal else 0.0
        return np.exp(P[lo] - m), np.exp(P[hi] + m)

    def median(self, X: pd.DataFrame) -> np.ndarray:
        return np.exp(self.predict_log(X)[0.5])
