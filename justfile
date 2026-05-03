default: lint_check html_lint_check format_check html_format_check type_check django_check test

lint_check:
    uv run ruff check

html_lint_check:
    uv run djlint go --lint --profile=django

format_check:
    uv run ruff format --check

format:
    uv run ruff format

html_format_check:
    uv run djlint go --check --profile=django

html_format:
    uv run djlint go --reformat --profile=django

type_check:
    uv run ty check

django_check:
    uv run python manage.py check

test:
    uv run python manage.py test

export:
    uv run --group export scripts/export_from_datastore.py --project davepeck-go-hrd --out ./export

import:
    uv run python manage.py import_from_datastore export/games.jsonl export/players.jsonl --skip-orphan-games
