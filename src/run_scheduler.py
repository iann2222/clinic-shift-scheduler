CONFIG_FILENAME = "config.json"

# Edit the root config.json and monthly input JSON for a normal scheduling run.

import sys

from clinic_shift_scheduler.app_config import load_scheduler_config
from clinic_shift_scheduler.application import request_from_app_config
from clinic_shift_scheduler.application_paths import application_root
from clinic_shift_scheduler.console_app import run_schedule_request_with_console
from clinic_shift_scheduler.console_lifecycle import pause_after_run_if_needed


PROJECT_ROOT = application_root(__file__)
INPUT_DIRECTORY = PROJECT_ROOT / "input"
OUTPUT_DIRECTORY = PROJECT_ROOT / "output"
INTERMEDIATE_DIRECTORY = PROJECT_ROOT / "runtime" / "expanded-input"


def main(arguments: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if arguments and arguments[0] == "--gui-worker":
        from clinic_shift_scheduler.execution_worker import main as worker_main

        return worker_main(arguments[1:])
    config_path = PROJECT_ROOT / CONFIG_FILENAME
    try:
        config = load_scheduler_config(config_path)
    except (OSError, ValueError) as error:
        print(f"[設定] 無法讀取 {config_path}：{error}", file=sys.stderr)
        return 1
    request = request_from_app_config(
        config,
        input_directory=INPUT_DIRECTORY,
        output_directory=OUTPUT_DIRECTORY,
        intermediate_directory=INTERMEDIATE_DIRECTORY,
    )
    return run_schedule_request_with_console(request)


if __name__ == "__main__":
    worker_mode = len(sys.argv) > 1 and sys.argv[1] == "--gui-worker"
    try:
        exit_code = main()
    finally:
        if not worker_mode:
            pause_after_run_if_needed()
    raise SystemExit(exit_code)
