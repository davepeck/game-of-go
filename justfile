default: lint_check format_check type_check test

lint_check:
    uv run ruff check

format_check:
    uv run ruff format --check

type_check:
    uv run ty check

test:
    uv run python manage.py test
