"""Cost forecasting with scikit-learn.

Model: linear regression that predicts the daily total cost from the day of the week
(weekends are cheaper) plus one of two signals, depending on what is known:

  - Sample data: provisioned capacity, i.e. what every resource that exists on that day
    costs at list price. For future days it is held at its latest value, so the forecast
    answers "what will we spend if the inventory stays as it is today?".
  - Real accounts: the provider's bill does not say what was provisioned on each past
    day, so the model uses a time trend fitted to the most recent TREND_DAYS instead.

Either way the model is compared against two baselines that need no machine learning, on
periods it never saw during training (a rolling backtest). Accounts with a short history
get shorter and fewer test periods; with under MIN_HISTORY_DAYS there is no forecast.

Results are cached per set of connected accounts, because each set is a different bill.
"""

from functools import lru_cache

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from . import data

HOLDOUT_DAYS = 60
FOLDS = 3
DEFAULT_HORIZON = 92  # about three calendar months
MIN_HISTORY_DAYS = 14
TREND_DAYS = 180

CAPACITY_MODEL = "Linear regression (capacity + weekday)"
TREND_MODEL = "Linear regression (trend + weekday)"


class NotEnoughHistory(Exception):
    pass


def daily() -> pd.DataFrame:
    return _daily(data.active())


@lru_cache
def _daily(scope) -> pd.DataFrame:
    """Per day: actual total cost, and (sample data only) the list-price cost of everything provisioned."""
    usage = data.load_usage().merge(data.load_resources()[["resource_id", "hourly_rate"]], on="resource_id")
    # Storage is billed at a flat daily rate, so its cost already is its provisioned cost.
    usage["capacity"] = (usage["hourly_rate"] * 24).where(usage["type"] != "storage", usage["cost"])
    days = usage.groupby("date").agg(cost=("cost", "sum"), capacity=("capacity", "sum"))
    if scope.live:
        days["capacity"] = np.nan  # not known for real accounts' past days
    return days.asfreq("D", fill_value=0) if days["capacity"].isna().any() else days.asfreq("D").ffill()


def model_name(series: pd.DataFrame) -> str:
    return TREND_MODEL if series["capacity"].isna().any() else CAPACITY_MODEL


def _weekday(dates: pd.DatetimeIndex) -> np.ndarray:
    """Six 0/1 columns for Tuesday..Sunday (Monday is the reference day)."""
    return np.eye(7)[dates.weekday][:, 1:]


def _model(train: pd.DataFrame, future: pd.DatetimeIndex) -> np.ndarray:
    if model_name(train) == CAPACITY_MODEL:
        features = np.hstack([train["capacity"].to_numpy().reshape(-1, 1), _weekday(train.index)])
        model = LinearRegression().fit(features, train["cost"].to_numpy())
        latest = np.full((len(future), 1), train["capacity"].iloc[-1])
        return model.predict(np.hstack([latest, _weekday(future)]))

    recent = train.iloc[-TREND_DAYS:]
    origin = recent.index[0]
    trend = lambda dates: ((dates - origin).days.to_numpy()).reshape(-1, 1)  # noqa: E731
    model = LinearRegression().fit(np.hstack([trend(recent.index), _weekday(recent.index)]), recent["cost"].to_numpy())
    return np.clip(model.predict(np.hstack([trend(future), _weekday(future)])), 0, None)


def _repeat_last_week(train: pd.DataFrame, future: pd.DatetimeIndex) -> np.ndarray:
    last_week = train["cost"].iloc[-7:]
    return last_week.groupby(last_week.index.weekday).mean().reindex(future.weekday).to_numpy()


def _last_week_average(train: pd.DataFrame, future: pd.DatetimeIndex) -> np.ndarray:
    return np.full(len(future), train["cost"].iloc[-7:].mean())


METHODS = {
    "model": _model,
    "Baseline: repeat last week": _repeat_last_week,
    "Baseline: last 7-day average": _last_week_average,
}


def _errors(actual: np.ndarray, predicted: np.ndarray) -> dict:
    billed = actual != 0  # percentage error is undefined on days that cost nothing
    mape = np.mean(np.abs((actual[billed] - predicted[billed]) / actual[billed])) * 100 if billed.any() else 0.0
    return {"mae": round(float(np.mean(np.abs(actual - predicted))), 2), "mape": round(float(mape), 2)}


def backtest() -> dict | None:
    return _backtest(data.active())


@lru_cache
def _backtest(scope) -> dict | None:
    """Hide a recent period, forecast it from everything before it, measure the error. Repeat.

    Returns None when there is too little history to test fairly.
    """
    series = daily()
    n = len(series)
    holdout = HOLDOUT_DAYS if n >= FOLDS * HOLDOUT_DAYS + 60 else max(7, n // 5)
    fold_count = min(FOLDS, max((n - 28) // holdout, 0))
    if fold_count < 1:
        return None
    name = model_name(series)

    folds, residuals, latest = [], [], []
    scores = {method: [] for method in METHODS}
    for fold in range(fold_count):  # fold 0 is the most recent period
        end = n - fold * holdout
        train, test = series.iloc[: end - holdout], series.iloc[end - holdout : end]
        actual = test["cost"].to_numpy()

        fold_results = {}
        for method, predict in METHODS.items():
            predicted = predict(train, test.index)
            label = name if method == "model" else method
            fold_results[label] = _errors(actual, predicted)
            scores[method].append(fold_results[label])
            if method == "model":
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
        "holdout_days": holdout,
        "folds": folds,
        "train_end": folds[0]["train_end"],
        "test_start": folds[0]["test_start"],
        "test_end": folds[0]["test_end"],
        # Average error of each method across all test periods.
        "results": [
            {
                "method": name if method == "model" else method,
                "is_model": method == "model",
                "mae": round(float(np.mean([s["mae"] for s in fold_scores])), 2),
                "mape": round(float(np.mean([s["mape"] for s in fold_scores])), 2),
            }
            for method, fold_scores in scores.items()
        ],
        "residual_std": round(float(np.std(residuals)), 2),
        "holdout": latest,
    }


def forecast(days: int = DEFAULT_HORIZON) -> dict:
    return _forecast(days, data.active())


@lru_cache
def _forecast(days: int, scope) -> dict:
    series = daily()
    if len(series) < MIN_HISTORY_DAYS:
        raise NotEnoughHistory(f"CloudLens needs at least {MIN_HISTORY_DAYS} days of billing history to predict the next bills.")
    future = pd.date_range(series.index[-1] + pd.Timedelta(days=1), periods=days, freq="D")
    predicted = _model(series, future)
    test = backtest()
    spread = test["residual_std"] if test else float(series["cost"].iloc[-28:].std() or 0)
    margin = 1.96 * spread  # rough 95% range from the backtest errors

    monthly = pd.Series(predicted, index=future).groupby(future.strftime("%Y-%m")).agg(["sum", "count"])
    return {
        "model": model_name(series),
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
