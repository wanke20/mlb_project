import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from games.models import Game

from .models import Pick
from .services.assistant import chat as assistant_chat
from .services.llm import LLMConfigError, LLMError


@login_required
@require_POST
def make_pick(request, game_id):
    game = get_object_or_404(
        Game.objects.select_related("home_team", "away_team"), game_id=game_id
    )

    if game.home_score is not None and game.away_score is not None:
        messages.error(request, "That game is already final — picks are locked.")
        return redirect("game_prediction", game_id=game_id)

    side = request.POST.get("side")
    if side == "home":
        team = game.home_team
    elif side == "away":
        team = game.away_team
    else:
        messages.error(request, "Please choose a team.")
        return redirect("game_prediction", game_id=game_id)

    pick, created = Pick.objects.update_or_create(
        user=request.user, game=game, defaults={"picked_team": team}
    )
    messages.success(
        request,
        f"Pick {'saved' if created else 'updated'}: {team.name} to win.",
    )

    nxt = request.POST.get("next")
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(nxt)
    return redirect("game_prediction", game_id=game_id)


@login_required
def dashboard(request):
    picks = list(
        request.user.picks.select_related(
            "game", "game__home_team", "game__away_team", "picked_team"
        )
    )

    pending, graded = [], []
    correct = 0
    for pick in picks:
        status = pick.status
        if status == "pending":
            pending.append(pick)
        else:
            graded.append(pick)
            if status == "correct":
                correct += 1

    graded_count = len(graded)
    win_rate = round(100 * correct / graded_count) if graded_count else None

    context = {
        "pending": pending,
        "graded": graded,
        "total": len(picks),
        "graded_count": graded_count,
        "correct": correct,
        "incorrect": graded_count - correct,
        "win_rate": win_rate,
        "pending_count": len(pending),
        "assistant_enabled": getattr(settings, "ASSISTANT_ENABLED", False),
    }
    return render(request, "picks/dashboard.html", context)


@login_required
@require_POST
def assistant_api(request):
    """Free-form chat endpoint. Accepts JSON {messages: [...], day: "today"|"tomorrow"}.

    Grounding (framework + day's CSVs) is rebuilt server-side each call, so the
    client only sends the conversation turns.
    """
    if not getattr(settings, "ASSISTANT_ENABLED", False):
        return JsonResponse(
            {"error": "The AI assistant is temporarily disabled."}, status=503
        )

    try:
        body = json.loads(request.body or "{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid request."}, status=400)

    day = body.get("day", "today")
    try:
        reply = assistant_chat(body.get("messages", []), day=day)
    except LLMConfigError as exc:
        return JsonResponse({"error": str(exc)}, status=503)
    except LLMError as exc:
        return JsonResponse({"error": str(exc)}, status=502)

    return JsonResponse({"reply": reply})
