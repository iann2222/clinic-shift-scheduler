"""Build, smoke-test, and archive the Windows PyInstaller release."""

from __future__ import annotations

import hashlib
import importlib.metadata
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGING_CONFIG_PATH = REPOSITORY_ROOT / "packaging" / "config_packaging.json"
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")


class PackagingError(RuntimeError):
    """Raised when a release cannot be produced safely."""


def _load_config() -> dict[str, Any]:
    payload = json.loads(PACKAGING_CONFIG_PATH.read_text(encoding="utf-8"))
    if payload.get("config_version") != "1":
        raise PackagingError("config_packaging.json config_version must be '1'")
    application = payload.get("application")
    if not isinstance(application, dict):
        raise PackagingError("config_packaging.json.application must be an object")
    version = application.get("version")
    if not isinstance(version, str) or not VERSION_PATTERN.fullmatch(version):
        raise PackagingError("application.version must be a semantic version")
    if application.get("target") != "win-x64":
        raise PackagingError("the current release layer only supports win-x64")
    scheduler_name = application.get("executable_name")
    if not isinstance(scheduler_name, str) or not scheduler_name:
        raise PackagingError("application.executable_name must be a non-empty string")
    editor = payload.get("editor")
    if not isinstance(editor, dict):
        raise PackagingError("config_packaging.json.editor must be an object")
    if editor.get("name") == scheduler_name:
        raise PackagingError(
            "editor.name must differ from application.executable_name"
        )
    if editor.get("entry_point") != "src/run_gui.py" or editor.get("console") is not False:
        raise PackagingError(
            "editor must use src/run_gui.py with console disabled"
        )
    project = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    project_version = project["project"]["version"]
    if version != project_version:
        raise PackagingError(
            "application.version must match pyproject.toml project.version: "
            f"{version!r} != {project_version!r}"
        )
    return payload


def _repository_path(relative: str) -> Path:
    path = (REPOSITORY_ROOT / relative).resolve()
    if not path.is_relative_to(REPOSITORY_ROOT.resolve()):
        raise PackagingError(f"packaging path escapes repository root: {relative}")
    return path


def _remove_tree(path: Path) -> None:
    resolved = path.resolve()
    if not resolved.is_relative_to(REPOSITORY_ROOT.resolve()):
        raise PackagingError(f"refusing to remove path outside repository: {path}")
    if resolved == REPOSITORY_ROOT.resolve():
        raise PackagingError("refusing to remove repository root")
    if resolved.exists():
        shutil.rmtree(resolved)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _download_verified(url: str, expected_sha256: str, target: Path) -> Path:
    expected = expected_sha256.upper()
    if target.is_file() and _sha256(target) == expected:
        print(f"[發布] 使用已驗證快取：{target.name}")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".download")
    temporary.unlink(missing_ok=True)
    print(f"[發布] 下載固定發布資源：{target.name}")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ClinicShiftScheduler-Packager/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            with temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
        actual = _sha256(temporary)
        if actual != expected:
            raise PackagingError(
                f"SHA-256 mismatch for {target.name}: expected {expected}, got {actual}"
            )
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _require_distribution(name: str, expected_version: str | None = None) -> str:
    try:
        installed = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError as error:
        raise PackagingError(
            f"missing build dependency {name}; run pip install -e .[test,release]"
        ) from error
    if expected_version is not None and installed != expected_version:
        raise PackagingError(
            f"{name} version must be {expected_version}, found {installed}"
        )
    return installed


def _run(
    command: list[str],
    *,
    cwd: Path = REPOSITORY_ROOT,
    environment: dict[str, str] | None = None,
) -> None:
    print("[發布] 執行：" + " ".join(command))
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        env=environment,
    )
    if completed.returncode:
        raise PackagingError(
            f"command failed with exit code {completed.returncode}: {' '.join(command)}"
        )


def _prepare_fonts(config: dict[str, Any], asset_directory: Path) -> Path:
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont

    font_config = config["font"]
    cache = REPOSITORY_ROOT / "runtime" / "packaging-cache"
    source = _download_verified(
        font_config["source_url"],
        font_config["source_sha256"],
        cache / "NotoSansTC-VF.ttf",
    )
    license_path = _download_verified(
        font_config["license_url"],
        font_config["license_sha256"],
        cache / "Noto-OFL.txt",
    )

    font_directory = asset_directory / "fonts"
    font_directory.mkdir(parents=True, exist_ok=True)
    targets = (
        ("NotoSansTC-Regular.ttf", int(font_config["regular_weight"])),
        ("NotoSansTC-Bold.ttf", int(font_config["bold_weight"])),
    )
    for filename, weight in targets:
        target = font_directory / filename
        print(f"[發布] 建立 Noto Sans TC 靜態字重 {weight}：{filename}")
        variable_font = TTFont(source)
        instance = instantiateVariableFont(
            variable_font,
            {"wght": weight},
            inplace=False,
        )
        instance.save(target)
        instance.close()
        variable_font.close()

    shutil.copy2(license_path, asset_directory / "Noto-OFL.txt")
    return license_path


def _validated_license_directory(config: dict[str, Any], font_license: Path) -> Path:
    """Validate the committed license bundle before it enters a release."""

    source = _repository_path(config["release_content"]["licenses_source"])
    manifest_path = source / "manifest.json"
    if not source.is_dir() or not manifest_path.is_file():
        raise PackagingError("root licenses bundle or manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("license_bundle_version") != "1":
        raise PackagingError("unsupported licenses manifest version")
    file_hashes = manifest.get("files")
    if not isinstance(file_hashes, dict) or not file_hashes:
        raise PackagingError("licenses manifest must contain file hashes")
    actual_files = {
        path.name
        for path in source.iterdir()
        if path.is_file() and path.name != manifest_path.name
    }
    if actual_files != set(file_hashes):
        raise PackagingError("licenses manifest does not match root license files")
    for filename, expected in file_hashes.items():
        path = source / filename
        if not isinstance(expected, str) or _sha256(path) != expected.upper():
            raise PackagingError(f"license checksum mismatch: {filename}")
    if _sha256(source / "NOTO-OFL-1.1.txt") != _sha256(font_license):
        raise PackagingError("committed Noto license differs from font source license")
    return source


def _stage_release(
    config: dict[str, Any],
    pyinstaller_output: Path,
    staging_root: Path,
    artifact_stem: str,
    license_directory: Path,
) -> Path:
    content = config["release_content"]
    release_directory = staging_root / artifact_stem
    _remove_tree(release_directory)
    shutil.copytree(pyinstaller_output, release_directory)

    config_source = _repository_path(content["config_source"])
    config_payload = json.loads(config_source.read_text(encoding="utf-8"))
    configured_input = config_payload["使用者設定"]["輸入檔名"]
    sample_filename = content["sample_input_filename"]
    if configured_input != sample_filename:
        raise PackagingError(
            "release sample_input_filename must match config.json 使用者設定.輸入檔名"
        )
    shutil.copy2(config_source, release_directory / "config.json")

    input_directory = release_directory / "input"
    input_directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        _repository_path(content["anonymous_input_source"]),
        input_directory / sample_filename,
    )
    (release_directory / "output").mkdir(exist_ok=True)
    (release_directory / "runtime").mkdir(exist_ok=True)

    version = config["application"]["version"]
    readme = _repository_path(content["readme_source"]).read_text(encoding="utf-8")
    (release_directory / "README.txt").write_text(
        readme.replace("{{VERSION}}", version),
        encoding="utf-8-sig",
    )
    shutil.copytree(license_directory, release_directory / "licenses")
    return release_directory


def _smoke_test(config: dict[str, Any], release_directory: Path) -> None:
    editor_name = config["editor"]["name"]
    editor_executable = release_directory / f"{editor_name}.exe"
    config_path = release_directory / "config.json"
    original_config = config_path.read_bytes()
    payload = json.loads(original_config.decode("utf-8"))
    diagnostic = payload["使用者設定"]["候選診斷"]
    diagnostic["啟用"] = False
    diagnostic["額外輸出候選班表份數上限"] = 0
    config_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    output_directory = release_directory / "output"
    runtime_directory = release_directory / "runtime"
    _remove_tree(output_directory)
    _remove_tree(runtime_directory)
    output_directory.mkdir()
    runtime_directory.mkdir()
    smoke_environment = _isolated_smoke_environment()
    try:
        _gui_smoke_test(
            config,
            release_directory,
            editor_executable,
            runtime_directory,
            smoke_environment,
        )
    finally:
        config_path.write_bytes(original_config)

    _remove_tree(output_directory)
    _remove_tree(runtime_directory)
    output_directory.mkdir()
    runtime_directory.mkdir()


def _gui_smoke_test(
    config: dict[str, Any],
    release_directory: Path,
    editor_executable: Path,
    runtime_directory: Path,
    smoke_environment: dict[str, str],
) -> None:
    sample_input = (
        release_directory
        / "input"
        / config["release_content"]["sample_input_filename"]
    )
    gui_smoke_directory = runtime_directory / "gui-smoke"
    gui_smoke_directory.mkdir(parents=True)
    gui_output = gui_smoke_directory / "round-trip.json"
    print("[發布] 執行封裝後 GUI 輸入 round-trip smoke test")
    completed = subprocess.run(
        [
            str(editor_executable),
            "--smoke-test",
            "--smoke-run-schedule",
            f"--smoke-input={sample_input}",
            f"--smoke-output={gui_output}",
        ],
        cwd=release_directory,
        check=False,
        timeout=float(config["build"]["smoke_test_timeout_seconds"]),
        env=smoke_environment,
    )
    if completed.returncode:
        error_path = gui_output.with_suffix(gui_output.suffix + ".error.txt")
        details = (
            error_path.read_text(encoding="utf-8")
            if error_path.is_file()
            else "no GUI error report was produced"
        )
        raise PackagingError(
            "packaged GUI smoke test failed with exit code "
            f"{completed.returncode}: {details}"
        )
    if not gui_output.is_file():
        raise PackagingError("packaged GUI smoke test did not save its output")
    if json.loads(gui_output.read_text(encoding="utf-8")) != json.loads(
        sample_input.read_text(encoding="utf-8")
    ):
        raise PackagingError("packaged GUI smoke round-trip changed the input")
    _verify_schedule_smoke_outputs(release_directory / "output")
    print(
        "[發布] GUI smoke test："
        "開啟／驗證／儲存／重開／背景排班 PASS"
    )

def _verify_schedule_smoke_outputs(output_directory: Path) -> None:
    json_paths = tuple(output_directory.glob("*.result-v1.json"))
    excel_paths = tuple(output_directory.glob("*.result-v1.xlsx"))
    pdf_paths = tuple(output_directory.glob("*.result-v1.pdf"))
    if not (len(json_paths) == len(excel_paths) == len(pdf_paths) == 1):
        raise PackagingError("smoke test did not create exactly one JSON/Excel/PDF")
    result = json.loads(json_paths[0].read_text(encoding="utf-8"))
    if result.get("status") != "OPTIMAL":
        raise PackagingError("smoke test result status is not OPTIMAL")
    if result.get("validation", {}).get("status") != "PASS":
        raise PackagingError("smoke test validation status is not PASS")
    if not zipfile.is_zipfile(excel_paths[0]):
        raise PackagingError("smoke test Excel is not a valid XLSX archive")
    if not pdf_paths[0].read_bytes().startswith(b"%PDF-"):
        raise PackagingError("smoke test PDF does not have a PDF header")


def _isolated_smoke_environment() -> dict[str, str]:
    smoke_environment = os.environ.copy()
    for name in (
        "CONDA_DEFAULT_ENV",
        "CONDA_PREFIX",
        "CONDA_PROMPT_MODIFIER",
        "PYTHONHOME",
        "PYTHONPATH",
        "VIRTUAL_ENV",
    ):
        smoke_environment.pop(name, None)
    windows_directory = Path(os.environ.get("WINDIR", "C:/Windows"))
    smoke_environment["PATH"] = os.pathsep.join(
        (str(windows_directory / "System32"), str(windows_directory))
    )
    smoke_environment["CLINIC_SCHEDULER_NO_PAUSE"] = "1"
    return smoke_environment


def _git_value(*arguments: str) -> str | None:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _write_manifest(
    config: dict[str, Any],
    release_directory: Path,
    *,
    smoke_test_status: str,
) -> dict[str, Any]:
    manifest = {
        "application": config["application"],
        "editor": config["editor"],
        "built_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "git_commit": _git_value("rev-parse", "HEAD"),
        "git_dirty": bool(_git_value("status", "--porcelain")),
        "python_version": platform.python_version(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in (
                "ortools",
                "openpyxl",
                "reportlab",
                "PySide6_Essentials",
                "pyinstaller",
            )
        },
        "font": {
            "family": config["font"]["family"],
            "version": config["font"]["version"],
            "source_sha256": config["font"]["source_sha256"],
            "regular_weight": config["font"]["regular_weight"],
            "bold_weight": config["font"]["bold_weight"],
        },
        "tests": {
            "unit_tests": "PASS" if config["build"]["run_tests"] else "SKIPPED",
            "packaged_smoke_test": smoke_test_status,
        },
    }
    (release_directory / "BUILD-MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _archive_release(
    release_root: Path,
    release_directory: Path,
    artifact_stem: str,
    manifest: dict[str, Any],
) -> tuple[Path, Path, Path]:
    delivery_directory = release_root / artifact_stem
    _remove_tree(delivery_directory)
    delivery_directory.mkdir(parents=True)
    zip_path = delivery_directory / f"{artifact_stem}.zip"
    checksum_path = delivery_directory / f"{artifact_stem}.zip.sha256"
    external_manifest = (
        delivery_directory / f"{artifact_stem}.build-manifest.json"
    )

    # Remove the former flat release layout for this exact version.
    for legacy in (
        release_root / zip_path.name,
        release_root / checksum_path.name,
        release_root / external_manifest.name,
    ):
        legacy.unlink(missing_ok=True)
    shutil.make_archive(
        str(zip_path.with_suffix("")),
        "zip",
        root_dir=release_directory.parent,
        base_dir=release_directory.name,
    )
    checksum = _sha256(zip_path)
    checksum_path.write_text(
        f"{checksum}  {zip_path.name}\n",
        encoding="ascii",
    )
    external_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return delivery_directory, zip_path, checksum_path


def _smoke_test_path(config: dict[str, Any], source: Path) -> None:
    if source.is_dir():
        _smoke_test(config, source)
        return
    if not source.is_file() or source.suffix.lower() != ".zip":
        raise PackagingError("smoke test source must be an onedir folder or ZIP")

    extraction_root = REPOSITORY_ROOT / "runtime" / "packaging-smoke"
    _remove_tree(extraction_root)
    extraction_root.mkdir(parents=True)
    try:
        with zipfile.ZipFile(source) as archive:
            archive.extractall(extraction_root)
        executable_name = f"{config['editor']['name']}.exe"
        executables = tuple(extraction_root.glob(f"*/{executable_name}"))
        if len(executables) != 1:
            raise PackagingError(
                "release ZIP must contain exactly one top-level application folder"
            )
        _smoke_test(config, executables[0].parent)
    finally:
        _remove_tree(extraction_root)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke-only",
        type=Path,
        help="only smoke-test one existing onedir folder or release ZIP",
    )
    options = parser.parse_args(arguments)
    config = _load_config()
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise PackagingError("Windows release must be built on 64-bit Windows")

    if options.smoke_only is not None:
        smoke_source = options.smoke_only.resolve()
        if not smoke_source.is_relative_to(REPOSITORY_ROOT.resolve()):
            raise PackagingError("smoke-test source must stay inside the repository")
        _smoke_test_path(config, smoke_source)
        return 0

    pyinstaller_version = _require_distribution(
        "pyinstaller",
        config["build"]["pyinstaller_version"],
    )
    _require_distribution("fonttools")
    print(
        f"[發布] 建置 {config['application']['display_name']} "
        f"{config['application']['version']}（PyInstaller {pyinstaller_version}）"
    )

    if config["build"]["run_tests"]:
        _run([sys.executable, "-m", "pytest", "-q"])

    work_directory = _repository_path(config["build"]["work_directory"])
    pyinstaller_dist = _repository_path(
        config["build"]["pyinstaller_dist_directory"]
    )
    asset_directory = _repository_path(config["build"]["asset_directory"])
    staging_root = _repository_path(
        config["build"]["release_staging_directory"]
    )
    for directory in (
        work_directory,
        pyinstaller_dist,
        asset_directory,
        staging_root,
    ):
        _remove_tree(directory)
        directory.mkdir(parents=True, exist_ok=True)

    font_license = _prepare_fonts(config, asset_directory)
    license_directory = _validated_license_directory(config, font_license)
    spec_path = REPOSITORY_ROOT / "packaging" / "windows" / "ClinicShiftScheduler.spec"
    pyinstaller_environment = os.environ.copy()
    conda_library_bin = Path(sys.prefix) / "Library" / "bin"
    if conda_library_bin.is_dir():
        pyinstaller_environment["PATH"] = (
            str(conda_library_bin)
            + os.pathsep
            + pyinstaller_environment.get("PATH", "")
        )
    _run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--workpath",
            str(work_directory),
            "--distpath",
            str(pyinstaller_dist),
            str(spec_path),
        ],
        environment=pyinstaller_environment,
    )

    application = config["application"]
    pyinstaller_output = pyinstaller_dist / application["name"]
    scheduler_name = application["executable_name"]
    if not (pyinstaller_output / f"{scheduler_name}.exe").is_file():
        raise PackagingError("PyInstaller did not create the expected executable")
    editor_name = config["editor"]["name"]
    if not (pyinstaller_output / f"{editor_name}.exe").is_file():
        raise PackagingError("PyInstaller did not create the expected GUI executable")
    artifact_stem = (
        f"{application['name']}-{application['version']}-{application['target']}"
    )
    release_root = _repository_path(config["build"]["release_directory"])
    release_root.mkdir(parents=True, exist_ok=True)
    release_directory = _stage_release(
        config,
        pyinstaller_output,
        staging_root,
        artifact_stem,
        license_directory,
    )

    smoke_status = "SKIPPED"
    if config["build"]["run_smoke_test"]:
        _smoke_test(config, release_directory)
        smoke_status = "PASS"
    manifest = _write_manifest(
        config,
        release_directory,
        smoke_test_status=smoke_status,
    )
    delivery_directory, zip_path, checksum_path = _archive_release(
        release_root,
        release_directory,
        artifact_stem,
        manifest,
    )
    _remove_tree(staging_root)
    print(f"[發布] 版本資料夾：{delivery_directory}")
    print(f"[發布] ZIP：{zip_path}")
    print(f"[發布] SHA-256：{checksum_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PackagingError as error:
        print(f"[發布失敗] {error}", file=sys.stderr)
        raise SystemExit(1) from error
