set shell := ["bash", "-uc"]
# Keeps a quoted value such as --frequency "as needed" one argument.
set positional-arguments

default:
    @just --list

setup:
    uv sync

lint:
    uv run ruff check --fix .
    uv run ruff format .
    uv run ty check .

test:
    uv run pytest tests/

# Serve the documentation site locally with live reload.
docs:
    uv run --isolated --only-group docs zensical serve

# Run a single country end-to-end with the current config, without pushing to HDX.
one ISO3:
    uv run oex-cli osm --config configs/base.yaml --iso3 {{ISO3}} --no-hdx-push

# Run scripts/schedule.yaml. Pushes to HDX. Takes --group, --frequency, --dry-run.
sweep *ARGS:
    ./scripts/sweep.py "$@"

# Regenerate Tasking Manager configs from the active-projects API, writing no exports.
tm-configs *ARGS:
    ./scripts/tm_configs.py "$@"

# Regenerate the production configs, cut their PBF extracts, then sweep them.
tm:
    ./scripts/tm_configs.py --extract
    ./scripts/sweep.py --group tasking_manager --frequency daily

# The same for sandbox projects.
tm-sandbox:
    ./scripts/tm_configs.py --sandbox --extract
    ./scripts/sweep.py --group tasking_manager_sandbox --frequency daily

# Publish every campaign in configs/tm_campaigns.yaml to HDX. Takes --dry-run.
tm-boundaries *ARGS:
    ./scripts/tm_campaign_boundaries.py --campaigns-file configs/tm_campaigns.yaml "$@"

# Publish the geometry a buffered extraction boundary was derived from.
source-geometry CONFIG NAME *ARGS:
    ./scripts/publish_source_geometry.py --config "$1" --name "$2" "${@:3}"
