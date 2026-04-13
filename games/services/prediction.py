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

# Bayesian ERA constants
LEAGUE_AVG_ERA = 4.50   # Prior mean: regress unknown pitchers to league average
IP_PRIOR = 30           # Pseudo-innings for prior; confidence = 0.5 at this many IP


def parse_record(record_str):
    wins, losses = map(int, record_str.split("-"))
    return wins / (wins + losses)


def parse_last10(last10_str):
    wins, losses = map(int, last10_str.split("-"))
    return wins / 10


def parse_innings_pitched(ip_str):
    """Convert baseball innings string (e.g. '123.2') to fractional innings.
    The digit after the decimal represents outs, not tenths: '123.2' = 123 + 2/3.
    Returns 0.0 when ip_str is None or unparseable.
    """
    if ip_str is None:
        return 0.0
    try:
        ip = float(ip_str)
        whole = int(ip)
        outs = round((ip - whole) * 10)
        return whole + outs / 3.0
    except (ValueError, TypeError):
        return 0.0


def era_confidence(ip_float):
    """Bayesian confidence weight for an ERA estimate based on innings pitched.
    Returns 0 when ip_float == 0 (no data) and approaches 1 as innings grow.
    Reaches 0.5 at IP_PRIOR innings pitched.
    """
    return ip_float / (ip_float + IP_PRIOR)


def effective_pitcher_era(pitcher):
    """Return a confidence-weighted ERA for use in the Bayesian model.

    Blends the pitcher's actual ERA toward LEAGUE_AVG_ERA proportionally to
    innings pitched.  When a pitcher has no stats (ERA stored as None/0 and
    IP = 0), confidence is 0 and the effective ERA is the league average —
    i.e. the pitcher contributes no advantage or disadvantage to the model.
    As innings pitched grows, the estimate shifts from the prior toward the
    observed ERA.

    Also returns the raw confidence so the caller can adjust PRIOR_STRENGTH.
    """
    if pitcher is None:
        return LEAGUE_AVG_ERA, 0.0

    raw_era = float(pitcher.era) if pitcher.era is not None else 0.0
    ip = parse_innings_pitched(getattr(pitcher, "innings_pitched", None))
    conf = era_confidence(ip)

    # Bayesian blend: observed ERA weighted by innings, prior weighted by (1 - conf)
    blended_era = conf * raw_era + (1 - conf) * LEAGUE_AVG_ERA
    return blended_era, conf


def predict_game(home_team, away_team, home_pitcher, away_pitcher):
    """
    Accepts Django model instances.
    Returns dictionary of predictions.
    """

    home_season = home_team.wins / (home_team.wins + home_team.losses)
    away_season = away_team.wins / (away_team.wins + away_team.losses)

    home_last10 = home_team.last10_wins / 10
    away_last10 = away_team.last10_wins / 10

    home_era, home_era_conf = effective_pitcher_era(home_pitcher)
    away_era, away_era_conf = effective_pitcher_era(away_pitcher)

    # Scale PRIOR_STRENGTH down when pitcher data is sparse so the confidence
    # interval widens to reflect genuine uncertainty.
    avg_era_conf = (home_era_conf + away_era_conf) / 2
    effective_prior = PRIOR_STRENGTH * (0.5 + 0.5 * avg_era_conf)

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
    alpha = prior_p * effective_prior
    beta_param = (1 - prior_p) * effective_prior

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