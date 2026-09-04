# Contributing

Bug reports and pull requests are welcome. Include the Home Assistant version,
Blink camera type, relevant sanitized logs and the exact consumer used to open
the stream. Redact Blink account data, camera names, serial numbers, network
identifiers, media URLs, tokens and unrelated Home Assistant configuration.

Blink liveview is an undocumented cloud interface. Keep changes defensive,
rate-limited and compatible with the official Home Assistant Blink integration.
Protocol and lifecycle changes should include deterministic tests that require
neither a Blink account nor network access.

Run the validation suite before submitting a pull request:

```bash
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -t .
```

Contributions submitted for inclusion are licensed under Apache-2.0.
