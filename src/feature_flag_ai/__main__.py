"""Entry point so `python -m feature_flag_ai` runs the CLI."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
