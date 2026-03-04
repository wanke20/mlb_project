import numpy as np
from scipy.stats import beta, norm


# -------------------
# Config constants
# -------------------
INTERCEPT = 0.10
B_SEASON = 2.0
B_LAST10 = 1.0
B_ERA = 0.30
PRIOR_STRENGTH = 25

HOME_FIELD_RUNS = 0.25
W_SEASON = 4.0
W_LAST10 = 1.5
W_ERA = 0.6
SIGMA_RUNS = 2.5

DEFAULT_ERA = 4.60


def parse_record(record_str):
    wins, losses = map(int, record_str.split("-"))
    return wins / (wins + losses)


def parse_last10(last10_str):
    wins, losses = map(int, last10_str.split("-"))
    return wins / 10


def safe_float(val):
    return float(val) if val is not None else DEFAULT_ERA


def predict_game(home_team, away_team, home_pitcher, away_pitcher):
    """
    Accepts Django model instances.
    Returns dictionary of predictions.
    """

    home_season = home_team.wins / (home_team.wins + home_team.losses)
    away_season = away_team.wins / (away_team.wins + away_team.losses)

    home_last10 = home_team.last10_wins / 10
    away_last10 = away_team.last10_wins / 10

    home_era = safe_float(getattr(home_pitcher, "era", None))
    away_era = safe_float(getattr(away_pitcher, "era", None))

    season_diff = home_season - away_season
    last10_diff = home_last10 - away_last10
    era_diff = away_era - home_era

    # ---- Win probability ----
    logit_p = (
        INTERCEPT
        + B_SEASON * season_diff
        + B_LAST10 * last10_diff
        + B_ERA * era_diff
    )

    prior_p = 1 / (1 + np.exp(-logit_p))
    alpha = prior_p * PRIOR_STRENGTH
    beta_param = (1 - prior_p) * PRIOR_STRENGTH

    mean = alpha / (alpha + beta_param)
    ci_low, ci_high = beta.ppf([0.05, 0.95], alpha, beta_param)

    # ---- Run differential ----
    mu = (
        HOME_FIELD_RUNS
        + W_SEASON * season_diff
        + W_LAST10 * last10_diff
        + W_ERA * era_diff
    )

    run_ci_low, run_ci_high = norm.ppf([0.025, 0.975], mu, SIGMA_RUNS)

    return {
        "win_probability": round(mean, 3),
        "win_ci": [round(ci_low, 3), round(ci_high, 3)],
        "expected_run_diff": round(mu, 2),
        "run_ci": [round(run_ci_low, 2), round(run_ci_high, 2)],
    }