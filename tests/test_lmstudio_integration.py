"""Integration test for LM Studio resources running on the local network."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional

import pytest
import requests

def _load_dotenv_into_environ() -> None:
    """Load simple KEY=VALUE pairs from project .env into os.environ if present.

    Keeps things dependency-free (no python-dotenv) and only sets keys that
    are not already defined in the environment.
    """
    # repo root assumed to be one directory up from tests/
    env_path = (Path(__file__).resolve().parent.parent / ".env").resolve()
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv_into_environ()

BASE_URL = os.environ.get("LM_STUDIO_BASE_URL", "http://127.0.0.1:1234")
SMALL_MODEL_OVERRIDE = os.environ.get("LM_STUDIO_TEST_MODEL")
PROMPT = os.environ.get(
    "LM_STUDIO_TEST_PROMPT",
    "Reply with a short acknowledgement that the LM Studio test prompt was received.",
)
SMALL_MODEL_HINTS = (
    "tinyllama",
    "phi-2",
    "orca-mini",
    "mistral",
    "qwen2.5-0.5b",
    "llama-3-8b",
    "gemma",
)


def _choose_model(models: Iterable[dict]) -> Optional[str]:
    """Pick a lightweight model id from the list of LM Studio models."""
    normalized = {model.get("id", ""): model for model in models if model.get("id")}
    if not normalized:
        return None

    if SMALL_MODEL_OVERRIDE:
        for model_id in normalized:
            if model_id == SMALL_MODEL_OVERRIDE or model_id.endswith(SMALL_MODEL_OVERRIDE):
                return model_id
        return None

    for hint in SMALL_MODEL_HINTS:
        for model_id in normalized:
            if hint in model_id.lower():
                return model_id

    # Fall back to the first available model if no hint matched.
    return next(iter(normalized))


@pytest.mark.integration
def test_lmstudio_small_model_chat_completion():
    """Ensure LM Studio can run a quick chat completion on a small model."""
    try:
        models_response = requests.get(f"{BASE_URL}/v1/models", timeout=10)
    except requests.exceptions.RequestException as exc:
        pytest.skip(f"Unable to reach LM Studio at {BASE_URL}: {exc}")

    assert (
        models_response.status_code == 200
    ), f"Fetching LM Studio models failed: {models_response.status_code} {models_response.text}"

    payload = models_response.json() if models_response.content else {}
    models = payload.get("data", []) if isinstance(payload, dict) else []
    if not models:
        pytest.skip("LM Studio reported no models; ensure at least one model is available.")

    model_id = _choose_model(models)
    if not model_id:
        pytest.skip(
            "No suitable small model found. Set LM_STUDIO_TEST_MODEL to the desired model id."
        )

    completion_body = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": "You are a test harness verifying LM Studio."},
            {"role": "user", "content": PROMPT},
        ],
        "max_tokens": 32,
        "temperature": 0.1,
    }

    try:
        completion_response = requests.post(
            f"{BASE_URL}/v1/chat/completions", json=completion_body, timeout=30
        )
    except requests.exceptions.RequestException as exc:
        pytest.fail(f"Chat completion request failed for model {model_id}: {exc}")

    assert (
        completion_response.status_code == 200
    ), (
        "Chat completion HTTP error: "
        f"{completion_response.status_code} {completion_response.text}"
    )

    data = completion_response.json() if completion_response.content else {}
    assert isinstance(data, dict), "LM Studio completion response must be a JSON object."
    assert data.get("choices"), "LM Studio completion response is missing choices."

    first_choice = data["choices"][0]
    message = first_choice.get("message", {}) if isinstance(first_choice, dict) else {}
    content = message.get("content", "").strip() if isinstance(message, dict) else ""

    assert content, "LM Studio completion returned an empty message."
    assert len(content) < 200, "LM Studio completion returned unexpectedly long output."
