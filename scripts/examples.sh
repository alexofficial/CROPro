#!/bin/sh
set -e

export UV_CACHE_DIR="${UV_CACHE_DIR:-.uv-cache}"
export UV_LINK_MODE="${UV_LINK_MODE:-copy}"

run_uv() {
  if command -v uv >/dev/null 2>&1; then
    uv run "$@"
  elif python -m uv --version >/dev/null 2>&1; then
    python -m uv run "$@"
  else
    echo "uv is required. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
  fi
}

run_uv python examples/PI-CAI_positive_crop.py
run_uv python examples/PI-CAI_negative_crop.py
