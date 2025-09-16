#!/usr/bin/env python3
"""
Minimal CLI for interacting with an OpenAI-compatible LM Studio/Ollama endpoint.

Usage examples:
  - List models:
      python scripts/lmstudio_chat.py --list-models

  - Send a quick prompt (defaults shown):
      python scripts/lmstudio_chat.py \
        --model mistral:latest \
        --prompt "Give me one fun fact."

Environment:
  LM_STUDIO_BASE_URL  Base URL to the API (default: http://192.168.1.138:1234)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict

import requests


DEFAULT_BASE_URL = os.environ.get("LM_STUDIO_BASE_URL", "http://192.168.1.138:1234")


def list_models(base_url: str) -> int:
    try:
        r = requests.get(f"{base_url}/v1/models", timeout=15)
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"Error: failed to fetch models from {base_url}: {exc}", file=sys.stderr)
        return 2
    try:
        payload = r.json()
    except Exception:
        print(r.text)
        return 0
    print(json.dumps(payload, indent=2))
    return 0


def chat(
    base_url: str,
    model: str,
    prompt: str,
    system_prompt: str = "You are a concise assistant.",
    max_tokens: int = 128,
    temperature: float = 0.2,
) -> int:
    body: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    try:
        r = requests.post(
            f"{base_url}/v1/chat/completions",
            json=body,
            timeout=(15, 60),
        )
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"Error: chat request failed: {exc}", file=sys.stderr)
        return 2

    try:
        data = r.json()
    except Exception:
        print(r.text)
        return 0

    # Print the assistant's message content if present; otherwise the raw JSON
    try:
        content = data["choices"][0]["message"]["content"].strip()
    except Exception:
        print(json.dumps(data, indent=2))
        return 0

    print(content)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="LM Studio LAN Chat Helper")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"API base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List available models and exit",
    )
    parser.add_argument(
        "--model",
        default="mistral:latest",
        help="Model id to use (e.g., mistral:latest)",
    )
    parser.add_argument(
        "--prompt",
        help="User prompt text; if omitted, read from stdin",
    )
    parser.add_argument(
        "--system",
        default="You are a concise assistant.",
        help="System prompt",
    )
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--temperature", type=float, default=0.2)

    args = parser.parse_args()

    if args.list_models:
        return list_models(args.base_url)

    prompt = args.prompt
    if not prompt:
        prompt = sys.stdin.read().strip()
        if not prompt:
            print("Error: no prompt provided (use --prompt or pipe input)", file=sys.stderr)
            return 2

    return chat(
        base_url=args.base_url,
        model=args.model,
        prompt=prompt,
        system_prompt=args.system,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )


if __name__ == "__main__":
    raise SystemExit(main())

