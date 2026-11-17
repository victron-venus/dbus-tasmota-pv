# Documentation index

These documents cover the assurance, build and release evidence for the
Tasmota plug-to-D-Bus PV integration.

## Verify the build

| Document | Description |
| --- | --- |
| [Quality, build and assessment evidence](quality-and-build.md) | The machine-readable review record and the checks it covers. |
| [Security assurance case](security-assurance.md) | The intended telemetry guarantee and what the program does not do. |
| [OpenSSF Best Practices evidence](openssf-evidence.md) | Evidence index reviewed against the OpenSSF criteria. |

## Release

| Document | Description |
| --- | --- |
| [Release operations](release-packaging.md) | Validation workflows run by beta and RC candidates before building. |
| [Release version inputs](release-versioning.md) | The `versioning` fields that identify a release. |
| [CI orchestration](CI-ORCHESTRATION.md) | How the quality gate and release pipeline divide validation. |

Shared repository policy: [release-workflow.md](release-workflow.md), [runner-preflight.md](runner-preflight.md), [release-read-safety.md](release-read-safety.md), [VERSIONING.md](VERSIONING.md), [rc-fuzzing.md](rc-fuzzing.md) and [fuzzing.md](fuzzing.md) are generated or shared boilerplate maintained in [victron-venus/venus-os-ci-toolkit](https://github.com/victron-venus/venus-os-ci-toolkit).
