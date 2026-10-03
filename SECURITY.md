# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.2.x   | :white_check_mark: |
| < 1.2   | :x:                |

## Reporting a Vulnerability

Private vulnerability reporting is enabled for this repository. Use
[Report a vulnerability](https://github.com/victron-venus/dbus-tasmota-pv/security/advisories/new)
to send a confidential report to the maintainers. Follow
[GitHub's private reporting instructions](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability)
if you need help submitting the report.

Include the affected version or commit, steps to reproduce, expected and actual
behavior, and potential impact. Remove access tokens, credentials and personal
data from examples. Do not disclose exploit details in public issues before
coordinating with the maintainers.

## Security Considerations

This project runs on Venus OS with access to:

- Tasmota devices via HTTP
- D-Bus (Victron system)

### Recommendations

1. **Tasmota**: Enable web authentication on Tasmota devices
2. **Network**: Run on a trusted local network
3. **Firewall**: Restrict access to Tasmota devices

## Known Limitations

- HTTP polling without authentication by default
- Designed for trusted home networks only
