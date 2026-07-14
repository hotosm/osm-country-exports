set shell := ["bash", "-uc"]

# Default: list recipes
default:
    @just --list

# Install deps into .venv via uv
setup:
    uv sync

# Lint
lint:
    uv run ruff check .

# Run a single country end-to-end with current config (no HDX push).
# Usage: just one NPL
one ISO3:
    uv run oex-cli osm --config configs/base.yaml --iso3 {{ISO3}} --no-hdx-push

# Run the sweep over scripts/countries.yaml. Pushes to HDX by default.
# Usage:
#   just sweep              # all groups in order
#   just sweep priority     # just one group
sweep GROUP="all":
    ./scripts/sweep.sh {{GROUP}}
