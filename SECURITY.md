# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.2.x   | :white_check_mark: |
| < 1.2   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability, please:

1. **Do NOT** open a public issue
2. Email the maintainers directly or use GitHub's private vulnerability reporting
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

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
