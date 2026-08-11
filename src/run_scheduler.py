CONFIG_FILENAME = "config.json"

# Edit the root config.json and monthly input JSON for a normal scheduling run.

import sys

from clinic_shift_scheduler.app_config import load_scheduler_config
from clinic_shift_scheduler.application_paths import application_root
from clinic_shift_scheduler.cli import main as run_cli


PROJECT_ROOT = application_root(__file__)
INPUT_DIRECTORY = PROJECT_ROOT / "input"
OUTPUT_DIRECTORY = PROJECT_ROOT / "output"
INTERMEDIATE_DIRECTORY = PROJECT_ROOT / "runtime" / "expanded-input"


def main() -> int:
    config_path = PROJECT_ROOT / CONFIG_FILENAME
    try:
        config = load_scheduler_config(config_path)
    except (OSError, ValueError) as error:
        print(f"[設定] 無法讀取 {config_path}：{error}", file=sys.stderr)
        return 1
    input_path = INPUT_DIRECTORY / config.input_file
    arguments = [
        str(input_path),
        "--output-dir",
        str(OUTPUT_DIRECTORY),
        "--intermediate-dir",
        str(INTERMEDIATE_DIRECTORY),
        "--progress-interval",
        str(config.progress_update_seconds),
        "--candidate-export-count",
        str(config.candidate_diagnostic.export_count),
    ]
    if config.candidate_diagnostic.export_formats:
        arguments.extend(
            (
                "--candidate-export-formats",
                *config.candidate_diagnostic.export_formats,
            )
        )
    if config.overwrite:
        arguments.append("--overwrite")
    if config.candidate_diagnostic.enabled:
        arguments.extend(
            (
                "--equivalent-limit",
                str(config.candidate_diagnostic.search_limit),
            )
        )
        diagnostic_time = config.candidate_diagnostic.time
        if diagnostic_time.mode == "定值":
            assert diagnostic_time.fixed_seconds is not None
            arguments.extend(
                (
                    "--equivalent-time-limit",
                    str(diagnostic_time.fixed_seconds),
                )
            )
        else:
            assert diagnostic_time.scheduling_time_ratio is not None
            arguments.extend(
                (
                    "--equivalent-time-ratio",
                    str(diagnostic_time.scheduling_time_ratio),
                )
            )
    else:
        arguments.append("--skip-equivalent-diagnostic")
    return run_cli(tuple(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
