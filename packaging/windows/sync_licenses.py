"""Create the repository-owned third-party license bundle.

This is a maintainer command, not part of a normal release build.  Generated
texts are committed under ``licenses/`` so a release never depends on network
access or an installed package retaining its ``dist-info`` metadata.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import urllib.request
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path, PurePosixPath


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LICENSE_DIRECTORY = REPOSITORY_ROOT / "licenses"
PACKAGE_LICENSE_OUTPUT = LICENSE_DIRECTORY / "PYTHON_PACKAGE_LICENSES.txt"
MANIFEST_PATH = LICENSE_DIRECTORY / "manifest.json"

PACKAGE_DISTRIBUTIONS = (
    "charset-normalizer",
    "et_xmlfile",
    "numpy",
    "openpyxl",
    "ortools",
    "pandas",
    "pillow",
    "protobuf",
    "PySide6-Essentials",
    "python-dateutil",
    "pytz",
    "reportlab",
    "shiboken6",
    "six",
    "pyinstaller",
)

STATIC_LICENSES = {
    "GNU-LGPL-3.0.txt": "https://www.gnu.org/licenses/lgpl-3.0.txt",
    "GNU-GPL-3.0.txt": "https://www.gnu.org/licenses/gpl-3.0.txt",
    "ORTOOLS-ABSEIL-APACHE-2.0.txt": "https://raw.githubusercontent.com/abseil/abseil-cpp/20240722.0/LICENSE",
    "ORTOOLS-HIGHS-MIT.txt": "https://raw.githubusercontent.com/ERGO-Code/HiGHS/v1.9.0/LICENSE.txt",
    "ORTOOLS-PROTOBUF-BSD.txt": "https://raw.githubusercontent.com/protocolbuffers/protobuf/v29.3/LICENSE",
    "ORTOOLS-RE2-BSD.txt": "https://raw.githubusercontent.com/google/re2/2024-04-01/LICENSE",
    "ORTOOLS-ZLIB.txt": "https://raw.githubusercontent.com/madler/zlib/v1.3.1/LICENSE",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _license_paths(package_name: str) -> tuple[Path, ...]:
    dist = distribution(package_name)
    files = tuple(dist.files or ())
    declared = dist.metadata.get_all("License-File") or ()
    selected: list[Path] = []
    for declared_name in declared:
        wanted = PurePosixPath(declared_name).as_posix().lower()
        candidates = [
            item
            for item in files
            if PurePosixPath(str(item).replace("\\", "/"))
            .as_posix()
            .lower()
            .endswith(wanted)
        ]
        if not candidates:
            raise RuntimeError(
                f"{package_name} declares missing license file: {declared_name}"
            )
        # Prefer the PEP 639 dist-info copy over a runtime package duplicate.
        candidates.sort(
            key=lambda item: (
                ".dist-info/" not in str(item).replace("\\", "/"),
                len(str(item)),
            )
        )
        selected.append(Path(dist.locate_file(candidates[0])))
    if not selected:
        fallback = [
            item
            for item in files
            if ".dist-info/" in str(item).replace("\\", "/")
            and item.name.lower() in {
                "license",
                "license.txt",
                "licence",
                "licence.txt",
                "copying",
                "copying.txt",
            }
        ]
        selected.extend(Path(dist.locate_file(item)) for item in fallback)
    if not selected:
        raise RuntimeError(f"cannot locate a license text for {package_name}")
    return tuple(dict.fromkeys(selected))


def _write_package_licenses() -> list[dict[str, object]]:
    sections = [
        "Python package licenses bundled by ClinicShiftScheduler",
        "=" * 59,
        "",
        "The following texts are copied verbatim from the installed",
        "distribution metadata used to build this release.",
        "",
    ]
    components: list[dict[str, object]] = []
    for package_name in PACKAGE_DISTRIBUTIONS:
        try:
            dist = distribution(package_name)
        except PackageNotFoundError as error:
            raise RuntimeError(
                f"required release distribution is not installed: {package_name}"
            ) from error
        paths = _license_paths(package_name)
        components.append(
            {
                "name": dist.metadata.get("Name", package_name),
                "version": dist.version,
                "license_expression": _license_expression(dist),
                "license_files": sorted({path.name for path in paths}),
            }
        )
        heading = f"{dist.metadata.get('Name', package_name)} {dist.version}"
        sections.extend((heading, "-" * len(heading), ""))
        for path in paths:
            sections.extend(
                (
                    f"Source license file: {path.name}",
                    "",
                    path.read_text(encoding="utf-8", errors="replace").rstrip(),
                    "",
                )
            )
    PACKAGE_LICENSE_OUTPUT.write_text(
        "\n".join(sections).rstrip() + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return components


def _license_expression(dist: object) -> str:
    """Keep manifest metadata compact; the complete text remains bundled."""

    value = (
        dist.metadata.get("License-Expression")
        or dist.metadata.get("License")
        or "See bundled text"
    )
    first_line = value.strip().splitlines()[0] if value.strip() else ""
    if not first_line or len(first_line) > 160:
        return "See bundled text"
    return first_line


def _download_static_licenses() -> None:
    for filename, url in STATIC_LICENSES.items():
        target = LICENSE_DIRECTORY / filename
        with urllib.request.urlopen(url, timeout=60) as response:
            content = response.read()
        target.write_bytes(content)


def main() -> int:
    LICENSE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    if "--download-static" in sys.argv:
        _download_static_licenses()
    missing = [
        filename
        for filename in STATIC_LICENSES
        if not (LICENSE_DIRECTORY / filename).is_file()
    ]
    if missing:
        raise RuntimeError(
            "missing static license files; rerun with --download-static: "
            + ", ".join(missing)
        )
    python_license = Path(sys.prefix) / "LICENSE_PYTHON.txt"
    if not python_license.is_file():
        raise RuntimeError(f"Python license not found: {python_license}")
    shutil.copyfile(python_license, LICENSE_DIRECTORY / "PYTHON-3.12.txt")
    font_license = REPOSITORY_ROOT / "build/packaging-assets/Noto-OFL.txt"
    if not font_license.is_file():
        raise RuntimeError(
            "Noto license asset is missing; run the release font preparation first"
        )
    shutil.copyfile(font_license, LICENSE_DIRECTORY / "NOTO-OFL-1.1.txt")
    components = _write_package_licenses()
    tracked_files = sorted(
        path
        for path in LICENSE_DIRECTORY.iterdir()
        if path.is_file() and path.name != MANIFEST_PATH.name
    )
    manifest = {
        "license_bundle_version": "1",
        "python": sys.version.split()[0],
        "components": components,
        "files": {
            path.name: _sha256(path)
            for path in tracked_files
        },
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"License bundle updated: {LICENSE_DIRECTORY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
