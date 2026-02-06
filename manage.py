#!/usr/bin/env python
import os
import sys


def main() -> None:
    if "test" in sys.argv and "DJANGO_SETTINGS_MODULE" not in os.environ:
        # Default tests to SQLite for portability (e.g., Codex/CI without Postgres).
        os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings_test"
    else:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
