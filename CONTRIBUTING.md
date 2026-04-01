# Contributing to dbus-tasmota-pv

Thank you for your interest in contributing!

## How to Contribute

### Reporting Bugs

1. Check existing [issues](https://github.com/victron-venus/dbus-tasmota-pv/issues) to avoid duplicates
2. Use the bug report template
3. Include:
   - Venus OS version
   - Tasmota firmware version
   - Smart plug model
   - Network configuration
   - Relevant logs

### Suggesting Features

1. Open a feature request issue
2. Describe the use case
3. Explain why it would benefit others

### Pull Requests

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Test on actual Venus OS hardware if possible
5. Run linter: `ruff check .`
6. Commit with clear messages
7. Push and create a Pull Request

### Code Style

- Follow PEP 8
- Use meaningful variable names
- Add comments for complex logic
- Keep functions focused and small

### Testing

- Test with actual Tasmota devices
- Verify HTTP polling works
- Check D-Bus service registration
- Verify PV data appears in VRM Portal / GUI

## Development Setup

```bash
# Clone
git clone https://github.com/victron-venus/dbus-tasmota-pv.git
cd dbus-tasmota-pv

# Test locally
python3 dbus-tasmota-pv.py --devices 192.168.1.100:40
```

## Questions?

- Open a [Discussion](https://github.com/victron-venus/dbus-tasmota-pv/discussions)
- Ask on [Victron Community](https://community.victronenergy.com/)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
