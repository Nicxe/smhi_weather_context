#!/usr/bin/env python3
"""Build a deterministic, runtime-only HACS release artifact."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import zipfile

DOMAIN = "smhi_weather_context"
ZIP_TIME = (2026, 1, 1, 0, 0, 0)
ALLOWED_EXTENSIONS = {".json", ".png", ".py", ".yaml", ".yml"}
TEXT_EXTENSIONS = {".json", ".py", ".yaml", ".yml"}
EXCLUDED_DIRECTORIES = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "fixtures",
    "tests",
}
EXCLUDED_FILES = {
    ".DS_Store",
    "AGENTS.md",
    "CLAUDE.md",
    "quality_scale.yaml",
}
SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[opsu]_[A-Za-z0-9]{30,}\b"),
    "assigned secret": re.compile(
        r"(?i)\b(?:access[_-]?token|api[_-]?key|password|client[_-]?secret)"
        r"\b\s*[:=]\s*['\"][^'\"]{8,}"
    ),
}


def _runtime_files(component: Path) -> list[Path]:
    """Return a stable allowlisted set of distributable component files."""
    if not component.is_dir():
        raise ValueError(f"component directory does not exist: {component}")

    files: list[Path] = []
    for path in component.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"release input must not contain symlinks: {path}")
        if not path.is_file():
            continue

        relative = path.relative_to(component)
        if any(part in EXCLUDED_DIRECTORIES for part in relative.parts):
            continue
        if relative.name in EXCLUDED_FILES:
            continue
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        files.append(path)

    files.sort(key=lambda item: item.relative_to(component).as_posix())
    if component / "manifest.json" not in files:
        raise ValueError("release input is missing manifest.json")
    if component / "__init__.py" not in files:
        raise ValueError("release input is missing __init__.py")
    return files


def _scan_text(path: Path, content: bytes) -> None:
    """Reject common credential material before it enters an artifact."""
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return
    text = content.decode("utf-8")
    for name, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            raise ValueError(f"possible {name} in release input: {path}")


def _content(path: Path, component: Path, version: str) -> bytes:
    """Read a file and inject the release version only into archived manifest data."""
    content = path.read_bytes()
    if path == component / "manifest.json":
        manifest = json.loads(content)
        if manifest.get("domain") != DOMAIN:
            raise ValueError(
                f"manifest domain must be {DOMAIN!r}, got {manifest.get('domain')!r}"
            )
        manifest["version"] = version
        content = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()
    _scan_text(path, content)
    return content


def build_release(component: Path, output: Path, version: str) -> dict[str, object]:
    """Build an archive and deterministic checksum/SBOM sidecars."""
    component = component.resolve()
    output = output.resolve()
    files = _runtime_files(component)
    output.parent.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, object]] = []
    file_sha1_values: list[str] = []
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for path in files:
            relative = path.relative_to(component).as_posix()
            content = _content(path, component, version)
            info = zipfile.ZipInfo(relative, ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9
            )

            sha256 = hashlib.sha256(content).hexdigest()
            sha1 = hashlib.sha1(content).hexdigest()
            file_sha1_values.append(sha1)
            entries.append(
                {
                    "fileName": relative,
                    "checksums": [
                        {"algorithm": "SHA256", "checksumValue": sha256},
                        {"algorithm": "SHA1", "checksumValue": sha1},
                    ],
                }
            )

    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum_path = output.with_suffix(output.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {output.name}\n", encoding="utf-8")

    namespace_hash = hashlib.sha256(f"{DOMAIN}:{version}:{digest}".encode()).hexdigest()
    package_verification_code = hashlib.sha1(
        "".join(sorted(file_sha1_values)).encode()
    ).hexdigest()
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"SMHI Weather Context {version}",
        "documentNamespace": (
            f"https://github.com/Nicxe/smhi_weather_context/spdx/{namespace_hash}"
        ),
        "creationInfo": {
            "created": datetime(*ZIP_TIME, tzinfo=UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "creators": ["Tool: scripts/build_release.py"],
        },
        "packages": [
            {
                "name": DOMAIN,
                "SPDXID": "SPDXRef-Package-smhi-weather-context",
                "versionInfo": version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": True,
                "licenseConcluded": "MIT",
                "licenseDeclared": "MIT",
                "copyrightText": "NOASSERTION",
                "packageVerificationCode": {
                    "packageVerificationCodeValue": package_verification_code
                },
            }
        ],
        "files": [
            {
                "SPDXID": f"SPDXRef-File-{index}",
                "licenseConcluded": "NOASSERTION",
                "copyrightText": "NOASSERTION",
                **entry,
            }
            for index, entry in enumerate(entries, 1)
        ],
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-Package-smhi-weather-context",
            },
            *[
                {
                    "spdxElementId": "SPDXRef-Package-smhi-weather-context",
                    "relationshipType": "CONTAINS",
                    "relatedSpdxElement": f"SPDXRef-File-{index}",
                }
                for index in range(1, len(entries) + 1)
            ],
        ],
    }
    sbom_path = output.with_suffix(output.suffix + ".spdx.json")
    sbom_path.write_text(
        json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    result: dict[str, object] = {
        "archive": str(output),
        "checksum": digest,
        "file_count": len(entries),
        "sha256_file": str(checksum_path),
        "spdx_file": str(sbom_path),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--component", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    result = build_release(args.component, args.output, args.version)
    print(
        f"Built {result['archive']} with {result['file_count']} runtime files "
        f"({result['checksum']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
