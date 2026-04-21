default: lint_check html_lint_check format_check html_format_check type_check test

lint_check:
    uv run ruff check

html_lint_check:
    uv run djlint go --lint --profile=django

format_check:
    uv run ruff format --check

html_format_check:
    uv run djlint go --check --profile=django

type_check:
    uv run ty check

test:
    uv run python manage.py test
