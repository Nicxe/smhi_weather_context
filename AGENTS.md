# Repository instructions

## Scope and safety

- This repository contains the SMHI Weather Context custom integration for Home Assistant.
- Do not commit, push, publish, create tags, create releases, or add a Git remote without explicit user approval.
- Do not edit Home Assistant `.storage` files directly.
- Preserve precise-location privacy in logs, diagnostics, fixtures, and issue reports.
- Use only documented SMHI data sources for meteorological and climate data.

## Branch and release model

- Development work targets `dev`.
- Promote `dev` to `beta` with a real merge commit.
- Promote `beta` to `main` with a real merge commit.
- Do not squash or rebase promotion commits; semantic-release must retain the Conventional Commit history.
- `beta` produces prereleases and `main` produces stable releases. `dev` never publishes.
- Back-syncs must be fast-forward only. A diverged target branch is a failed safety check and requires a reviewed merge.

## Release artifacts

- HACS expects `smhi_weather_context.zip` with a flat component layout: `manifest.json` is at the archive root.
- The source manifest version is never changed by release tooling. Only the manifest inside the archive receives the release version.
- Release archives must be deterministic, contain only approved runtime files, and include SHA-256 and SPDX-SBOM sidecars.
- Run `npm run verify:release:config` before a manifest exists, `npm run verify:release:self-test` to exercise the packager in isolation, and `npm run verify:release` once the integration manifest is present.
- Never use `semantic-release --no-ci` locally. A real dry run requires approved Git branches and a remote with push-verification access.

## Commit and release text

- Use English Conventional Commit summaries.
- `feat` is user-facing functionality, `fix` corrects behavior, `docs` is documentation-only, and `chore` is maintenance.
- Release descriptions are concise, professional, and written for Home Assistant users. Avoid internal architecture names unless users need them to understand impact.
- Breaking changes must explain what stops working and what users must do.

## Quality gates

- Run Ruff lint and formatting checks, strict typing, pytest with coverage, hassfest, HACS validation, dependency audit, and release-artifact verification.
- Runtime code and the deployed Home Assistant development copy must be byte-identical apart from explicitly documented runtime cache.
- A phase is not complete until local checks and live Home Assistant evidence both support it.
