#!/usr/bin/env python3
"""Verify HACS metadata, release configuration, and artifact reproducibility."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

from build_release import DOMAIN, ZIP_TIME, build_release

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_ARCHIVE = f"{DOMAIN}.zip"
TEST_VERSION = "0.0.0-local-verification"
FORBIDDEN_PARTS = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "fixtures",
    "tests",
}
FORBIDDEN_FILES = {".DS_Store", "AGENTS.md", "CLAUDE.md", "quality_scale.yaml"}


def _load_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as err:
        raise ValueError(f"required file is missing: {path.relative_to(ROOT)}") from err
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path.relative_to(ROOT)}")
    return value


def verify_configuration() -> None:
    """Verify HACS, npm, and semantic-release contracts without Git."""
    hacs = _load_json(ROOT / "hacs.json")
    if hacs.get("zip_release") is not True:
        raise ValueError("hacs.json must enable zip_release")
    if hacs.get("filename") != EXPECTED_ARCHIVE:
        raise ValueError(f"hacs.json filename must be {EXPECTED_ARCHIVE}")
    if hacs.get("country") != ["SE"]:
        raise ValueError("hacs.json country must be the single-item list ['SE']")

    package = _load_json(ROOT / "package.json")
    if package.get("private") is not True:
        raise ValueError("release-tooling package must remain private")
    scripts = package.get("scripts")
    if not isinstance(scripts, dict) or not {
        "release:dry-run",
        "verify:release",
        "verify:release:config",
        "verify:release:self-test",
    }.issubset(scripts):
        raise ValueError(
            "package.json is missing required release verification scripts"
        )
    dependencies = package.get("devDependencies")
    if (
        not isinstance(dependencies, dict)
        or dependencies.get("@nicxe/semantic-release-config") != "^1.2.3"
    ):
        raise ValueError("package.json must use @nicxe/semantic-release-config ^1.2.3")

    config_path = ROOT / "release.config.cjs"
    try:
        release_config = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as err:
        raise ValueError("release.config.cjs is missing") from err
    required_fragments = {
        'require("@nicxe/semantic-release-config")',
        'repoSlug: "Nicxe/smhi_weather_context"',
        "notifyIssues: false",
        "scripts/build_release.py",
        "custom_components/smhi_weather_context",
        "--output smhi_weather_context.zip",
        "--version ${nextRelease.version}",
        "smhi_weather_context.zip.sha256",
        "smhi_weather_context.zip.spdx.json",
    }
    missing = sorted(
        fragment for fragment in required_fragments if fragment not in release_config
    )
    if missing:
        raise ValueError(f"release.config.cjs is missing required contracts: {missing}")
    if (
        "update-manifest-version" in release_config
        or "@semantic-release/npm" in release_config
    ):
        raise ValueError("release config may not mutate source or publish npm packages")

    wrapper = (ROOT / "release.config.js").read_text(encoding="utf-8")
    if 'require("./release.config.cjs")' not in wrapper:
        raise ValueError("release.config.js must delegate to release.config.cjs")

    print("Shared release configuration is internally consistent and non-publishing")


def _verify_artifact(output: Path, version: str) -> tuple[str, list[str]]:
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum_path = output.with_suffix(output.suffix + ".sha256")
    checksum_line = checksum_path.read_text(encoding="utf-8")
    if checksum_line != f"{digest}  {output.name}\n":
        raise ValueError("SHA-256 sidecar does not match the archive")

    with zipfile.ZipFile(output) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if names != sorted(names):
            raise ValueError("archive entries are not sorted")
        if "manifest.json" not in names or "__init__.py" not in names:
            raise ValueError("archive is missing required flat component files")
        if any(name.startswith(f"{DOMAIN}/") for name in names):
            raise ValueError("archive contains a component-directory prefix")
        for info in infos:
            path = Path(info.filename)
            if any(part in FORBIDDEN_PARTS for part in path.parts):
                raise ValueError(f"archive contains forbidden path: {info.filename}")
            if path.name in FORBIDDEN_FILES:
                raise ValueError(f"archive contains forbidden file: {info.filename}")
            if info.date_time != ZIP_TIME:
                raise ValueError(
                    f"archive timestamp is not normalized: {info.filename}"
                )
            if info.filename.endswith(".py"):
                compile(archive.read(info.filename), info.filename, "exec")

        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("domain") != DOMAIN:
            raise ValueError("archived manifest has the wrong domain")
        if manifest.get("version") != version:
            raise ValueError("archived manifest has the wrong release version")

    sbom_path = output.with_suffix(output.suffix + ".spdx.json")
    sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    if sbom.get("spdxVersion") != "SPDX-2.3":
        raise ValueError("SBOM is not SPDX 2.3")
    if len(sbom.get("files", [])) != len(names):
        raise ValueError("SBOM file inventory does not match the archive")
    return digest, names


def verify_component(component: Path) -> None:
    """Build twice outside the repository and prove byte-for-byte equivalence."""
    manifest_path = component / "manifest.json"
    try:
        manifest_before = manifest_path.read_bytes()
    except FileNotFoundError as err:
        raise ValueError(
            "custom_components/smhi_weather_context/manifest.json is not present; "
            "run --self-test now and rerun the full verifier after the manifest is created"
        ) from err

    with TemporaryDirectory(prefix="smhi-weather-context-release-") as directory:
        root = Path(directory)
        first = root / "first" / EXPECTED_ARCHIVE
        second = root / "second" / EXPECTED_ARCHIVE
        first.parent.mkdir()
        second.parent.mkdir()
        build_release(component, first, TEST_VERSION)
        build_release(component, second, TEST_VERSION)
        first_digest, names = _verify_artifact(first, TEST_VERSION)
        second_digest, _ = _verify_artifact(second, TEST_VERSION)
        if first_digest != second_digest or first.read_bytes() != second.read_bytes():
            raise ValueError("two clean release builds are not byte-identical")

    if manifest_path.read_bytes() != manifest_before:
        raise ValueError("release verification modified the source manifest")
    print(
        f"Release artifact is deterministic: {len(names)} files, SHA-256 {first_digest}"
    )
    print("Source manifest remained byte-identical")


def run_self_test() -> None:
    """Exercise the real builder in a disposable component fixture."""
    with TemporaryDirectory(
        prefix="smhi-weather-context-builder-self-test-"
    ) as directory:
        root = Path(directory)
        component = root / "custom_components" / DOMAIN
        translations = component / "translations"
        translations.mkdir(parents=True)
        (component / "__init__.py").write_text(
            '"""Synthetic release-verifier fixture."""\n', encoding="utf-8"
        )
        (component / "sensor.py").write_text(
            '"""Synthetic sensor fixture."""\n', encoding="utf-8"
        )
        (component / "manifest.json").write_text(
            json.dumps(
                {
                    "domain": DOMAIN,
                    "name": "SMHI Väderperspektiv",
                    "version": "0.0.0",
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        (component / "strings.json").write_text("{}\n", encoding="utf-8")
        (translations / "en.json").write_text("{}\n", encoding="utf-8")
        verify_component(component)
    print("Disposable builder self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--config-only", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    verify_configuration()
    if args.config_only:
        return 0
    if args.self_test:
        run_self_test()
        return 0
    verify_component(ROOT / "custom_components" / DOMAIN)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
