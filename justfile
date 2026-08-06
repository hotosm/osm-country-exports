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

# Test
test:
    uv run pytest tests/

# Run a single country end-to-end with current config (no HDX push).
# Usage: just one NPL
one ISO3:
    uv run oex-cli osm --config configs/base.yaml --iso3 {{ISO3}} --no-hdx-push

# Run the sweep over scripts/schedule.yaml. Pushes to HDX by default.
# Usage:
#   just sweep                        # every enabled job
#   just sweep --group priority       # one group
#   just sweep --frequency monthly    # one frequency
#   just sweep --dry-run              # print the commands, run nothing
sweep *ARGS:
    ./scripts/sweep.py {{ARGS}}

# Regenerate Tasking Manager configs from the active-projects API, then sweep them.
# Usage:
#   just tm                 # production projects
#   just tm --sandbox       # sandbox projects
tm-configs *ARGS:
    ./scripts/tm_configs.py {{ARGS}}

tm:
    ./scripts/tm_configs.py --extract
    ./scripts/sweep.py --group tasking_manager --frequency daily

tm-sandbox:
    ./scripts/tm_configs.py --sandbox --extract
    ./scripts/sweep.py --group tasking_manager_sandbox --frequency daily
