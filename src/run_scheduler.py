INPUT_FILENAME = "排班輸入_2026-08.json"

# Edit only the filename above for a normal monthly scheduling run.

from pathlib import Path

from clinic_shift_scheduler.cli import main as run_cli


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIRECTORY = PROJECT_ROOT / "input"
OUTPUT_DIRECTORY = PROJECT_ROOT / "output"
INTERMEDIATE_DIRECTORY = PROJECT_ROOT / "runtime" / "expanded-input"


def main() -> int:
    input_path = INPUT_DIRECTORY / INPUT_FILENAME
    return run_cli(
        (
            str(input_path),
            "--output-dir",
            str(OUTPUT_DIRECTORY),
            "--intermediate-dir",
            str(INTERMEDIATE_DIRECTORY),
            "--overwrite",
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
