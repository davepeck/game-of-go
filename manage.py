#!/usr/bin/env python
"""Django management CLI entry point."""

import os
import sys


def main() -> None:
    """Delegate to Django's ``execute_from_command_line`` with our settings."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "go.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
