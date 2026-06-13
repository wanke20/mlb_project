"""Pluggable LLM client layer.

The rest of the app talks to ``LLMClient`` — an abstract interface — so the
provider can be swapped without touching views or context-building. Only the
network call lives here; prompt/context assembly is in ``assistant.py``.

Configure via env (see core/settings.py):
    LLM_PROVIDER   default "gemini"
    GEMINI_API_KEY required to enable
    GEMINI_MODEL   default "gemini-2.5-flash"
"""

from __future__ import annotations

import requests
from django.conf import settings


class LLMError(Exception):
    """Upstream/transport failure when talking to the model."""


class LLMConfigError(LLMError):
    """The assistant isn't configured (e.g. missing API key)."""


class LLMClient:
    """Provider-agnostic chat interface.

    ``messages`` is a list of ``{"role": "user"|"model", "text": str}`` turns,
    oldest first. ``system_instruction`` is grounding context prepended out of
    band. Returns the model's reply text.
    """

    def generate(self, system_instruction: str, messages: list[dict]) -> str:
        raise NotImplementedError


class GeminiClient(LLMClient):
    ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, api_key: str, model: str, timeout: int = 60):
        if not api_key:
            raise LLMConfigError(
                "GEMINI_API_KEY is not set. Add it to your .env to enable the assistant."
            )
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def generate(self, system_instruction: str, messages: list[dict]) -> str:
        contents = [
            {"role": m["role"], "parts": [{"text": m["text"]}]}
            for m in messages
            if m.get("text")
        ]
        if not contents:
            raise LLMError("No message to send.")

        payload = {
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 2048},
        }

        try:
            resp = requests.post(
                self.ENDPOINT.format(model=self.model),
                params={"key": self.api_key},
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise LLMError(f"Could not reach Gemini: {exc}") from exc

        if resp.status_code != 200:
            # Surface the API's error message but never the key (it's only in params).
            detail = ""
            try:
                detail = resp.json().get("error", {}).get("message", "")
            except ValueError:
                detail = resp.text[:300]
            raise LLMError(f"Gemini returned {resp.status_code}: {detail}")

        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            feedback = data.get("promptFeedback", {})
            blocked = feedback.get("blockReason")
            if blocked:
                raise LLMError(f"Request was blocked by safety filters ({blocked}).")
            raise LLMError("Gemini returned no response.")

        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            finish = candidates[0].get("finishReason", "")
            raise LLMError(f"Gemini returned an empty reply (finishReason={finish}).")
        return text


def get_llm_client() -> LLMClient:
    """Construct the configured client. Raises ``LLMConfigError`` if unusable."""
    provider = (settings.LLM_PROVIDER or "gemini").lower()
    if provider == "gemini":
        return GeminiClient(api_key=settings.GEMINI_API_KEY, model=settings.GEMINI_MODEL)
    raise LLMConfigError(f"Unknown LLM_PROVIDER: {provider!r}")
