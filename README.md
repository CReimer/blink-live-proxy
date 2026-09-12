# Blink Live Proxy for Home Assistant

An unofficial Home Assistant custom integration that adds experimental live
stream and snapshot proxy camera entities for cameras managed by Home
Assistant's official Blink integration.

This project is independent and is not affiliated with, endorsed by or
supported by Blink, Amazon or Home Assistant.

## Features

- creates one proxy camera for every camera in the loaded Blink integration;
- returns the existing cached JPEG immediately for responsive dashboards and
  HomeKit snapshot requests;
- deduplicates and rate-limits background snapshot refreshes;
- delays snapshot commands so an immediately following stream request can take
  priority;
- opens Blink liveview only when a real local stream consumer connects;
- exposes a stable loopback-only TCP relay to Home Assistant;
- reuses one upstream Blink liveview for simultaneous local consumers;
- retries the observed transient Blink response that contains no media server;
- shuts down relays, clients and background tasks with the entity lifecycle;
- stores no additional Blink credentials.

## Experimental status and limitations

Blink Live Proxy uses the internal `blinkpy` camera objects supplied by Home
Assistant's official Blink integration. The proprietary liveview endpoint is
not a stable public API and may change without notice. Blink cloud availability,
camera generation, account state and rate limits can all affect streaming.

The private predecessor of this integration has been exercised with two proxy
cameras on Home Assistant Container 2026.9.0, and its upstream stream contained
H.264 video and AAC audio. A transient missing-server response was also observed
in real operation; version 0.1.0 adds a narrowly bounded retry for that exact
condition. Treat end-to-end behavior with a particular HomeKit client as
experimental until verified on that client and camera model.

This is not a local camera protocol: control and media still traverse Blink's
cloud service. It does not add two-way audio or HomeKit talkback. Home
Assistant's HomeKit `support_audio` option controls inbound stream audio only.

## Requirements

- Home Assistant 2026.8.0 or newer;
- the official Blink integration configured and loaded successfully;
- a Blink camera/account combination supported by `blinkpy` liveview;
- a local stream consumer such as Home Assistant or a HomeKit Bridge.

## Installation with HACS

Until the repository is included in HACS by default, add it as a custom
repository:

1. Open HACS in Home Assistant.
2. Select **Integrations**.
3. Open the menu and select **Custom repositories**.
4. Add `https://github.com/CReimer/blink-live-proxy` as an **Integration**.
5. Install **Blink Live Proxy** and restart Home Assistant.
6. Ensure the official **Blink** integration is loaded.
7. Go to **Settings > Devices & services > Add integration** and select
   **Blink Live Proxy**.

For manual installation, copy `custom_components/blink_live_proxy` into the
`custom_components` directory of the Home Assistant configuration and restart
Home Assistant.

## HomeKit use

Add the proxy camera entities created by this integration to a Home Assistant
HomeKit Bridge. Do not expose both the official snapshot camera and its proxy
under the same HomeKit identity. Stream startup remains subject to Blink cloud
latency and throttling.

The local relay listens only on `127.0.0.1` using an ephemeral port. It becomes
active when Home Assistant's stream pipeline connects and is not a general
network stream endpoint.

## Privacy and bug reports

Blink credentials remain owned by the official integration, but device names,
serial numbers, network IDs, temporary media endpoints and logs can still be
sensitive. Redact them before sharing diagnostics or traces. Never publish
tokens, cookies or Blink API responses containing account data.

## Development

Run the tests against the pinned Home Assistant release:

```bash
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -t .
```

The integration was developed with substantial assistance from generative AI.
All changes are reviewed, tested and released under the responsibility of the
maintainer.

## License

The source code is licensed under the
[Apache License 2.0](LICENSE) (`Apache-2.0`).

Blink and the Blink logo are trademarks of their respective owner. Product
names and the locally included brand artwork are used only to identify
compatibility. The Apache license does not grant trademark rights. This follows
the trademark notice convention used by
[Home Assistant Brands](https://github.com/home-assistant/brands#trademark-legal-notices).

## Tests and coverage

Use Python 3.14 and the pinned Home Assistant test dependencies:

```bash
python -m pip install -r requirements-test.txt
python tools/run_tests.py
```

The suite mocks device and external service access; Blink also exercises a local
TCP relay. Every integration Python module is included in coverage, including
modules not imported by tests. The test command and GitHub Actions both require
at least **91% line coverage and 91% branch coverage**, checked separately without
rounding. HTML, XML and JSON reports are written to `coverage-report/` and uploaded
as the `coverage` artifact by CI.
