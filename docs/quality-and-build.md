# Quality, build and assessment evidence

The [machine-readable review](evidence/assessment-2026-10-13.json) records checks on application source `fdc08c4683f75b4795822ed2267d2ef8edf2aedb` on 2026-10-13. Documentation additions do not substitute for these checks.

## Reproduction and results

Use the locked Python 3.12.13 environment described in [CONTRIBUTING.md](../CONTRIBUTING.md). The application pytest suite passed **151 tests**, with **2 skipped**; the receipt explains the optional-environment skips. A separate release-contract run passed **342 tests**. Ruff lint and formatting passed. Local wheel construction passed; it does not install or validate Venus OS native libraries.

Runtime-only statement coverage, excluding tests, measured **424/479 (88.52%)** in the listed Python files. The generic `--cov=.` total includes tests and is not a defensible whole-project percentage. This review therefore does **not** claim OpenSSF Silver 80% whole-project coverage: release helpers, shell code, optional integrations and native dependencies need an explicit accounting. Do not silently remove these components from the denominator.

The separate pinned Bandit 1.9.4 environment ran real scanner discovery regressions and scanned source/tooling/tests: zero findings and zero scan errors. Existing precise suppressions are retained; complete scan validation fails closed.

## Dependencies, installation and delivery

`pyproject.toml` and `uv.lock` record Python dependencies and the build group; the README identifies Venus OS D-Bus/GLib prerequisites. Dependabot and scheduled security checks monitor dependencies. Resolve findings and re-test lockfile updates; do not modify installed third-party source without a reviewed, recorded patch.

The native installer intentionally uses Venus OS `/data` and supervisor locations and is not a generic prefix/DESTDIR installer. Editable Python development installation provides fast application iteration, but does not provision all native/optional hardware dependencies. A full standard-variable installation claim remains open.

Source and release downloads use GitHub HTTPS. Existing release assets include SHA-256 inventories; this review does not claim signed releases, signed tags, full artifact reproducibility or target acceptance. A real cryptographic signature must be checked against the expected publishing identity, and exact RC bytes must pass the target acceptance required by [RELEASING.md](../RELEASING.md) before stable promotion.

## Review limits and next work

The public GitHub review found enabled private vulnerability reporting and no open Dependabot or secret alerts. Code-scanning observations are listed individually in the receipt. The historical release-note review confirmed source-based human-readable change summaries and upgrade guidance; older notes are explicitly labelled retrospective. No public project vulnerability advisory or ordinary issue was found, and the owner reported no external reports in the preceding twelve months.

The Markdown uses headings and descriptive links, but this review is not an accessibility certification or a tested translation system. Full release reproducibility, cryptographic signing, comprehensive coverage, optional-runtime accessibility and actual [access continuity](../GOVERNANCE.md) remain work in [the roadmap](../ROADMAP.md). Unsupported criteria must stay unmet in the public assessment.
