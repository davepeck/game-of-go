Tooling

- We use Astral's UV for package management and building.
- Always run commands with `uv run ...`
- We use Astral's `ruff` for linting and formatting. (`uv run ruff ...`)
- We use Astral's `ty` for type checking. (`uv run ty ...`)
- After making code changes, be sure to run `ruff` and `ty`.

Testing

- We use Django's built-in testing framework. Run `uv run python manage.py test` to run tests.

Type Hints

- When using `typing`, always `import typing as t` and use `t.Callable`, etc.
- Use modern type annotations on all functions
- Use `list[int]` instead of `t.List[int]`, `dict[str, int]`, etc.
- Use `str | None` instead of `t.Optional[str]`
- Never use `from __future__ import annotations`
- Provide docstrings for all functions, classes, and modules. If they fit on a short line, use a one-liner. Otherwise, use a multi-line docstring with a summary line, a blank line, and then a more detailed description. The summary line should appear on a separate line after the opening triple quotes.
- Use `"""` for docstrings, not `'''`
- Do not use `#type: ignore` comments. Instead, fix the underlying type issues using `isinstance()`, including `assert isinstance()`, `t.cast()`, via code refactor, or via other special forms in `typing` such as `t.TypeGuard`.
