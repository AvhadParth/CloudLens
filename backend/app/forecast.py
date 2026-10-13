"""Cost forecasting with scikit-learn.

Model: linear regression that predicts the daily total cost from
  - provisioned capacity: what the resources that exist on that day cost per day at list price
  - the day of the week (weekends are cheaper because traffic and dev usage drop)

For future days the capacity is held at its latest value, i.e. the forecast answers
"what will we spend if the inventory stays as it is today?".

The model is compared against two baselines that need no machine learning, on periods it
never saw during training (a rolling backtest over the last FOLDS x HOLDOUT_DAYS days).

Results are cached per set of connected cloud providers, because each set is a different bill.
"""

from functools import lru_cache

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from . import data

HOLDOUT_DAYS = 60
FOLDS = 3
DEFAULT_HORIZON = 92  # 1 Oct to 31 Dec 2026: three whole calendar months

MODEL_NAME = "Linear regression (capacity + weekday)"


def daily() -> pd.DataFrame:
    return _daily(data.active())


@lru_cache
def _daily(providers: frozenset) -> pd.DataFrame:
    """Per day: actual total cost, and the list-price cost of everything provisioned that day."""
    usage = data.load_usage().merge(data.load_resources()[["resource_id", "hourly_rate"]], on="resource_id")
    # Storage is billed at a flat daily rate, so its cost already is its provisioned cost.
    usage["capacity"] = (usage["hourly_rate"] * 24).where(usage["type"] != "storage", usage["cost"])
    return usage.groupby("date").agg(cost=("cost", "sum"), capacity=("capacity", "sum"))


def _features(dates: pd.DatetimeIndex, capacity) -> np.ndarray:
    """Capacity, plus six 0/1 columns for Tuesday..Sunday (Monday is the reference day)."""
    weekday = np.eye(7)[dates.weekday][:, 1:]
    return np.hstack([np.asarray(capacity, dtype=float).reshape(-1, 1), weekday])


def _model(train: pd.DataFrame, future: pd.DatetimeIndex) -> np.ndarray:
    model = LinearRegression().fit(_features(train.index, train["capacity"]), train["cost"].to_numpy())
    latest_capacity = np.full(len(future), train["capacity"].iloc[-1])
    return model.predict(_features(future, latest_capacity))


def _repeat_last_week(train: pd.DataFrame, future: pd.DatetimeIndex) -> np.ndarray:
    last_week = train["cost"].iloc[-7:]
    return last_week.groupby(last_week.index.weekday).mean().reindex(future.weekday).to_numpy()


def _last_week_average(train: pd.DataFrame, future: pd.DatetimeIndex) -> np.ndarray:
    return np.full(len(future), train["cost"].iloc[-7:].mean())


METHODS = {
    MODEL_NAME: _model,
    "Baseline: repeat last week": _repeat_last_week,
    "Baseline: last 7-day average": _last_week_average,
}


def _errors(actual: np.ndarray, predicted: np.ndarray) -> dict:
    return {
        "mae": round(float(np.mean(np.abs(actual - predicted))), 2),
        "mape": round(float(np.mean(np.abs((actual - predicted) / actual)) * 100), 2),
    }


def backtest() -> dict:
    return _backtest(data.active())


@lru_cache
def _backtest(providers: frozenset) -> dict:
    """Hide a 60-day period, forecast it from everything before it, measure the error. Repeat."""
    series = daily()
    folds, residuals = [], []
    scores = {name: [] for name in METHODS}

    for fold in range(FOLDS):  # fold 0 is the most recent period
        end = len(series) - fold * HOLDOUT_DAYS
        train, test = series.iloc[: end - HOLDOUT_DAYS], series.iloc[end - HOLDOUT_DAYS : end]
        actual = test["cost"].to_numpy()

        fold_results = {}
        for name, method in METHODS.items():
            predicted = method(train, test.index)
            fold_results[name] = _errors(actual, predicted)
            scores[name].append(fold_results[name])
            if name == MODEL_NAME:
                residuals.extend(actual - predicted)
                if fold == 0:
                    latest = [
                        {"date": d.strftime("%Y-%m-%d"), "actual": round(float(a), 2), "predicted": round(float(p), 2)}
                        for d, a, p in zip(test.index, actual, predicted)
                    ]
        folds.append(
            {
                "train_start": train.index[0].strftime("%Y-%m-%d"),
                "train_end": train.index[-1].strftime("%Y-%m-%d"),
                "test_start": test.index[0].strftime("%Y-%m-%d"),
                "test_end": test.index[-1].strftime("%Y-%m-%d"),
                "results": fold_results,
            }
        )

    return {
        "holdout_days": HOLDOUT_DAYS,
        "folds": folds,
        "train_end": folds[0]["train_end"],
        "test_start": folds[0]["test_start"],
        "test_end": folds[0]["test_end"],
        # Average error of each method across all test periods.
        "results": [
            {
                "method": name,
                "is_model": name == MODEL_NAME,
                "mae": round(float(np.mean([s["mae"] for s in fold_scores])), 2),
                "mape": round(float(np.mean([s["mape"] for s in fold_scores])), 2),
            }
            for name, fold_scores in scores.items()
        ],
        "residual_std": round(float(np.std(residuals)), 2),
        "holdout": latest,
    }


def forecast(days: int = DEFAULT_HORIZON) -> dict:
    return _forecast(days, data.active())


@lru_cache
def _forecast(days: int, providers: frozenset) -> dict:
    series = daily()
    future = pd.date_range(series.index[-1] + pd.Timedelta(days=1), periods=days, freq="D")
    predicted = _model(series, future)
    margin = 1.96 * backtest()["residual_std"]  # rough 95% range from the backtest errors

    monthly = pd.Series(predicted, index=future).groupby(future.strftime("%Y-%m")).agg(["sum", "count"])
    return {
        "model": MODEL_NAME,
        "trained_on_days": len(series),
        "history": [{"date": d.strftime("%Y-%m-%d"), "cost": round(float(c), 2)} for d, c in series["cost"].items()],
        "forecast": [
            {
                "date": d.strftime("%Y-%m-%d"),
                "cost": round(float(p), 2),
                "low": round(float(max(p - margin, 0)), 2),
                "high": round(float(p + margin), 2),
            }
            for d, p in zip(future, predicted)
        ],
        "monthly": [
            {"month": month, "cost": round(float(row["sum"]), 2), "days": int(row["count"])}
            for month, row in monthly.iterrows()
        ],
        "next_30_days_cost": round(float(predicted[:30].sum()), 2),
    }
