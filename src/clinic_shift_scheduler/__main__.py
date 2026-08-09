"""Allow ``python -m clinic_shift_scheduler`` to run the full application."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
