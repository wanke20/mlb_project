"""Pick-assistant orchestration: build grounding context, run a chat turn.

Grounding = the hand-built pick'em framework (mlb_pickem_lessons.txt) plus the
same games / hitters / bullpen CSVs the site exports, for the chosen day. The
LLM transport itself lives in ``llm.py``; this module is the pure assembly +
DB-read layer that feeds it.
"""

from __future__ import annotations

from functools import lru_cache

from django.conf import settings

from games.services.csv_exports import (
    build_bullpen_csv,
    build_games_csv,
    build_hitters_csv,
    resolve_date,
)

from .llm import LLMError, get_llm_client

VALID_DAYS = ("today", "tomorrow")

_PERSONA = """You are an expert MLB pick'em assistant embedded in a baseball \
prediction app. Your job is to help the user decide which team will WIN each \
game (a straight-up winner pick — no spreads).

Ground every recommendation in two things only:
1. The analytical framework below (the user's own hand-built methodology).
2. The live data tables below (games, hitters, bullpen) for the selected day.

Rules:
- Be concise and specific. Cite the actual numbers you used (ERA, xwOBA, \
K-BB%, bullpen fatigue, platoon splits, weather, recent form).
- Weigh PLATOON SPLITS heavily, and evaluate BOTH sides of every game you \
pick. Hitters generally perform better against opposite-handed pitching: \
left-handed batters tend to hit right-handed pitchers better (and vice \
versa), while same-handed matchups favor the pitcher. Compare each starting \
pitcher's handedness (away_pitcher_throws / home_pitcher_throws in the games \
table) against the opposing lineup's splits — use the hitters table's \
vs_lhp_* columns when the opposing starter is left-handed and vs_rhp_* \
columns when he is right-handed.
- The IDEAL winner pick has both edges working together: (a) the TEAM YOU \
PICK has favorable platoon splits against the opposing starter, and that \
starter is ideally a weak/below-average pitcher (poor ERA, FIP, xERA, K-BB%, \
high xwOBA/barrel%) the lineup can punish; AND (b) the TEAM YOU FADE has \
UNFAVORABLE platoon splits against your pick's starter — or, if their splits \
aren't clearly bad, your pick's starter is simply very good (elite ERA/FIP/\
xERA/K-BB%, low xwOBA) and can suppress them anyway. Explicitly walk through \
both of these for every pick, and call out which condition is carrying it.
- Be most confident when both edges line up (your lineup mashes a bad arm \
while your ace shuts down a poor-platoon lineup); be more cautious — and lower \
your confidence — when only one side holds, and say which side is the weak \
link.
- When asked for picks, do NOT cover every game. Select only your 3 \
HIGHEST-CONVICTION winners from the slate and ignore the rest. For each of \
those picks, go deep: break down the starting-pitcher matchup (basic and \
advanced metrics), the platoon-split edges across the lineups, bullpen \
state/fatigue, recent form, and weather, and tie it back to the analytical \
framework. Then state the pick, a confidence (low/medium/high), the key \
factors that drove it, and the main risk that could sink it. Prefer depth \
over breadth — a few well-reasoned picks, not a rundown of the whole slate.
- Do NOT invent stats that aren't in the tables. If data is missing, say so \
and lower your confidence.
- Acknowledge uncertainty honestly — baseball is high-variance.
- Use plain text. No code blocks unless showing a table."""


@lru_cache(maxsize=1)
def _framework_text() -> str:
    path = settings.BASE_DIR / "mlb_pickem_lessons.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def build_system_instruction(day: str) -> str:
    """Assemble persona + framework + the day's CSV context into one string."""
    day = day if day in VALID_DAYS else "today"
    target_date = resolve_date(day)

    framework = _framework_text()
    games_csv = build_games_csv(target_date)
    # Filter hitters to the selected day's lineups — without target_date this
    # returns every date's lineups at once, so the LLM would see tomorrow's (and
    # stale) hitters while reasoning about today's slate.
    hitters_csv = build_hitters_csv(target_date)
    bullpen_csv = build_bullpen_csv()

    sections = [_PERSONA]
    if framework:
        sections.append(
            "===== ANALYTICAL FRAMEWORK (mlb_pickem_lessons) =====\n" + framework
        )
    sections.append(
        f"===== GAMES — {day.upper()} ({target_date}) [CSV] =====\n"
        + (games_csv.strip() or "(no games scheduled)")
    )
    sections.append(
        f"===== HITTERS — {day.upper()} ({target_date}) (season + platoon splits) [CSV] =====\n"
        + (hitters_csv.strip() or "(no lineups posted yet)")
    )
    sections.append("===== BULLPENS (usage + fatigue) [CSV] =====\n" + bullpen_csv.strip())
    sections.append(
        f"The user is asking about {day}'s slate ({target_date}). "
        "Base winner picks on the data above."
    )
    return "\n\n".join(sections)


def _sanitize_messages(raw) -> list[dict]:
    """Coerce client messages into [{'role': 'user'|'model', 'text': str}]."""
    if not isinstance(raw, list):
        return []
    cleaned = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        text = m.get("text")
        if role not in ("user", "model") or not isinstance(text, str) or not text.strip():
            continue
        cleaned.append({"role": role, "text": text.strip()[:6000]})
    # Bound cost: keep only the most recent N turns.
    limit = settings.LLM_MAX_HISTORY_MESSAGES
    return cleaned[-limit:]


def chat(messages, day: str = "today") -> str:
    """Run one assistant turn. Raises ``LLMError`` / ``LLMConfigError`` on failure."""
    history = _sanitize_messages(messages)
    if not history or history[-1]["role"] != "user":
        raise LLMError("Send a question to the assistant first.")

    client = get_llm_client()
    system_instruction = build_system_instruction(day)
    return client.generate(system_instruction, history)
