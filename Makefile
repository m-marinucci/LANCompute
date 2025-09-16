.PHONY: models chat setup

# Ensure uv is installed locally before running (see README for install instructions).

setup:
	@uv --version >/dev/null 2>&1 || { echo "Please install uv (https://docs.astral.sh/uv/)"; exit 2; }
	@uv venv
	@. .venv/bin/activate && uv pip install --upgrade requests pytest

models:
	@uv run --with requests scripts/lmstudio_chat.py --list-models

# Usage: make chat PROMPT="Say hi" MODEL=mistral:latest
chat:
	@[ -n "$(PROMPT)" ] || (echo "Set PROMPT=\"your text\"" && exit 2)
	@uv run --with requests scripts/lmstudio_chat.py --model "$(MODEL)" --prompt "$(PROMPT)"
