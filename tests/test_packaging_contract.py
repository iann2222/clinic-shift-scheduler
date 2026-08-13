from __future__ import annotations

import json
import hashlib
import tomllib
import unittest
from pathlib import Path

from clinic_shift_scheduler.exporters import pdf_exporter


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class PackagingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(
            (REPOSITORY_ROOT / "packaging/config_packaging.json").read_text(
                encoding="utf-8"
            )
        )

    def test_packaging_config_owns_release_version_and_windows_target(self) -> None:
        self.assertEqual(self.config["config_version"], "1")
        self.assertRegex(
            self.config["application"]["version"],
            r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$",
        )
        self.assertEqual(self.config["application"]["target"], "win-x64")
        self.assertEqual(
            self.config["application"]["entry_point"],
            "src/run_scheduler.py",
        )
        self.assertEqual(
            self.config["editor"]["entry_point"],
            "src/run_gui.py",
        )
        self.assertFalse(self.config["editor"]["console"])
        self.assertNotEqual(
            self.config["application"]["name"],
            self.config["editor"]["name"],
        )

    def test_pyinstaller_pin_matches_release_optional_dependency(self) -> None:
        project = tomllib.loads(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        expected = (
            f"pyinstaller=={self.config['build']['pyinstaller_version']}"
        )
        self.assertIn(
            expected,
            project["project"]["optional-dependencies"]["release"],
        )

    def test_project_and_packaging_versions_match(self) -> None:
        project = tomllib.loads(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        self.assertEqual(
            project["project"]["version"],
            self.config["application"]["version"],
        )

    def test_runtime_dependencies_do_not_include_unused_pandas(self) -> None:
        project = tomllib.loads(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        dependencies = project["project"]["dependencies"]
        self.assertFalse(
            any(item.lower().startswith("pandas") for item in dependencies)
        )
        build_source = (
            REPOSITORY_ROOT / "packaging/windows/build_release.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn('"pandas"', build_source)

    def test_release_only_uses_anonymous_sample_input(self) -> None:
        source = self.config["release_content"]["anonymous_input_source"]
        self.assertIn("匿名範本", source)
        self.assertTrue((REPOSITORY_ROOT / source).is_file())

    def test_font_downloads_are_integrity_pinned(self) -> None:
        font = self.config["font"]
        self.assertRegex(font["source_sha256"], r"^[A-F0-9]{64}$")
        self.assertRegex(font["license_sha256"], r"^[A-F0-9]{64}$")
        self.assertEqual(font["regular_weight"], 400)
        self.assertEqual(font["bold_weight"], 700)

    def test_pdf_has_bundled_font_and_common_windows_fallbacks(self) -> None:
        self.assertEqual(
            pdf_exporter._BUNDLED_FONT_FILENAMES,
            ("NotoSansTC-Regular.ttf", "NotoSansTC-Bold.ttf"),
        )
        windows_regular = {
            pair[0].name.lower()
            for pair in pdf_exporter._SYSTEM_CJK_FONT_PAIRS
            if pair[0].drive
        }
        self.assertTrue({"msjh.ttc", "msyh.ttc", "mingliu.ttc"} <= windows_regular)

    def test_release_files_exist(self) -> None:
        for relative in (
            "packaging/windows/ClinicShiftScheduler.spec",
            "packaging/windows/build.ps1",
            "packaging/windows/build_release.py",
            "packaging/windows/smoke-test.ps1",
            "packaging/windows/hooks/hook-ortools.py",
            "packaging/windows/resources/README.txt",
            "packaging/windows/sync_licenses.py",
            "licenses/THIRD_PARTY_NOTICES.txt",
            "licenses/PYTHON_PACKAGE_LICENSES.txt",
            "licenses/QT_SOURCE_OFFER.txt",
            "licenses/manifest.json",
        ):
            self.assertTrue((REPOSITORY_ROOT / relative).is_file(), relative)

    def test_pyinstaller_spec_collects_editor_and_gui_styles(self) -> None:
        source = (
            REPOSITORY_ROOT / "packaging/windows/ClinicShiftScheduler.spec"
        ).read_text(encoding="utf-8")

        self.assertIn('packaging_config["editor"]', source)
        self.assertIn('"gui/styles/*.qss"', source)
        self.assertIn("editor_exe", source)
        self.assertIn('"pytest"', source)
        self.assertIn("excludes=packaging_only_excludes", source)

    def test_release_smoke_runs_scheduler_through_editor_worker(self) -> None:
        source = (
            REPOSITORY_ROOT / "packaging/windows/build_release.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"--smoke-run-schedule"', source)
        self.assertIn("_verify_schedule_smoke_outputs", source)

    def test_root_license_bundle_is_the_only_release_license_source(self) -> None:
        content = self.config["release_content"]
        self.assertEqual(content["licenses_source"], "licenses")
        self.assertNotIn("third_party_notices_source", content)
        self.assertFalse(
            (
                REPOSITORY_ROOT
                / "packaging/windows/resources/THIRD_PARTY_NOTICES.txt"
            ).exists()
        )

    def test_license_manifest_covers_every_committed_license_file(self) -> None:
        directory = REPOSITORY_ROOT / "licenses"
        manifest = json.loads(
            (directory / "manifest.json").read_text(encoding="utf-8")
        )
        expected = {
            path.name
            for path in directory.iterdir()
            if path.is_file() and path.name != "manifest.json"
        }
        self.assertEqual(set(manifest["files"]), expected)
        for filename, expected_hash in manifest["files"].items():
            actual = hashlib.sha256((directory / filename).read_bytes()).hexdigest()
            self.assertEqual(actual.upper(), expected_hash)

    def test_release_uses_separate_staging_and_versioned_delivery_directories(self) -> None:
        build = self.config["build"]
        self.assertTrue(build["release_staging_directory"].startswith("build/"))
        self.assertEqual(build["release_directory"], "release")


if __name__ == "__main__":
    unittest.main()
