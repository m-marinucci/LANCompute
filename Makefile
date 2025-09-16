PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || which python3)

.PHONY: models chat setup

setup:
	@echo "Using Python: $(PY)"
	@$(PY) -m pip install --upgrade --quiet pip requests

models:
	@$(PY) scripts/lmstudio_chat.py --list-models

# Usage: make chat PROMPT="Say hi" MODEL=mistral:latest
chat:
	@[ -n "$(PROMPT)" ] || (echo "Set PROMPT=\"your text\"" && exit 2)
	@$(PY) scripts/lmstudio_chat.py --model "$(MODEL)" --prompt "$(PROMPT)"

