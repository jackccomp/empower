# Empower Naperville for Home Assistant

Experimental electricity reader for Home Assistant OS, including ARM64 ODROID-N2/N2+ and amd64. Runs on the Home Assistant device with no Mac dependency.

**Not yet verified end to end on Home Assistant hardware.** Container build, browser startup, Ingress and Empower login require an installation test. Website protection may reject Chromium; this project does not bypass it.

## Install the browser app first

1. Open **Settings → Apps → App store → ⋮ → Repositories** in Home Assistant.
2. Add `https://github.com/jackccomp/empower`.
3. Find **Empower Browser**, install it, start it and select **Open Web UI**.
4. Sign in to Empower inside the displayed browser, open the electricity dashboard and select **Read dashboard**.
5. Confirm the safe summary before installing the integration. A message asking to install the integration is expected at this stage.

The initial install builds a Debian/Chromium container locally and can take several minutes. Keep protection mode enabled and check memory usage during the test.

## Custom integration

Copy `custom_components/empower_naperville` into Home Assistant's `/config/custom_components/empower_naperville`. Restart Core and add **Empower Naperville** through **Settings → Devices & services**. Target API version: Core 2026.9.3.

Configure the meter timezone and whether timestamps mark interval starts or ends. Return to the app and read again. It sends only the start timestamp and interval values through Supervisor's authenticated internal API. No pasted access token is required.

Sensors show reading count, latest interval energy, available-history energy, first/latest reading times and last upload. A successful upload may still contain old meter data; compare latest reading and last upload.

## Updates and Energy history

The browser app refreshes daily after the first successful read in each app run. It reuses its saved session; expired sessions or challenges require manual sign-in. After restarting the app, read once to re-arm the timer. Automatic credential-based reauthentication is not implemented.

Historical import is disabled by default. Enable it in the integration options only after confirming kWh units, timezone, interval start/end labels, and continuous elapsed 15-minute spacing across DST. Re-upload, then select **Empower Naperville electricity consumption** in Energy settings after Recorder processes the upload. Snapshot energy sensors intentionally do not accumulate live statistics.

Only complete hourly groups are imported. Repeated uploads replace the same hours; corrections recalculate cumulative sums. Shortened histories or changed start dates are rejected. One consistently selected electricity meter is supported; rolling history and timestamp migration are not implemented. The stripped payload cannot independently verify meter identity.

The first complete statistic establishes the cumulative baseline. Disabling import does not erase old history. Do not change timing interpretation or recreate the integration after importing without planning a statistics migration.

## Privacy and security

Enter credentials only in Empower's browser login form. Browser cookies stay in the app profile on Home Assistant and are included in cold app backups. The integration persists sanitized readings in `.storage` and optional hourly statistics in Recorder. Protect backups.

The desktop is available only through Supervisor Ingress. No host ports, host networking or privileged capabilities are requested. Chromium runs unprivileged without the Supervisor token in its environment. Chromium's additional process sandbox is disabled inside the protected app container; use this dedicated browser only for Empower. The app has authenticated Core API access through Supervisor. Logs omit credentials, cookies, identifiers and raw portal responses.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
```

The 22 offline tests cover parsing, DST interpretation, hourly statistics, duplicate/corrected uploads, invalid histories, error redaction and ingress restrictions. HA services and Selenium are mocked; these tests do not prove a container build, live login or Recorder compatibility.

See [app documentation](empower_browser/DOCS.md) for details. Unofficial personal integration, not affiliated with Empower or Home Assistant.
