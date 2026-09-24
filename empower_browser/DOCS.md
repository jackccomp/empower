# Operation

1. Add `https://github.com/jackccomp/empower` through the app store repository menu, then find **Empower Browser** and install it. The ARM64 container builds on your Blue and downloads Chromium and its dependencies; allow several minutes.
2. Start it and select **Open Web UI**. Use a desktop-sized browser window for the initial sign-in.
3. A browser running on the Blue appears inside Home Assistant. Sign in to Empower directly in that window. No credentials go into the app's configuration or logs. If Empower blocks this browser, stop and report the safe message; successful Safari login does not prove this browser will work.
4. Open the electricity dashboard. Select **Read dashboard** above the browser. A safe count and first/latest summary appears. This works for the compatibility test even before installing the integration.
5. Install the accompanying **Empower Naperville** custom integration to receive the data. Then select **Read dashboard** again. The app sends only the start timestamp and electricity interval values through Supervisor's authenticated internal API.

## Daily refresh

After your first successful read, the app refreshes the dashboard at `refresh_hours` intervals (24 hours by default, minimum 6) while running. It reuses the browser session kept in `/data/profile`. Credentials are not stored by the reader; Chromium password saving is disabled. Cookies remain in that profile, including across app restarts. Session expiry, MFA or a security challenge requires signing in again through the web UI. There is no guaranteed unattended reauthentication.

After an app restart, open the UI and read once to re-enable the daily timer. Set **Start on boot** only after the compatibility test succeeds. The timer does not survive an app stop; Home Assistant's last-upload and latest-reading sensors make missed/stale uploads visible. Closing the web UI does not stop the browser or timer.

**Read dashboard** reads the currently loaded snapshot. **Refresh and read** loads a fresh dashboard before extracting it. The summary displayed in this app uses the original POC's naive 15-minute clock arithmetic; the integration separately applies your chosen timezone and elapsed-time convention. Compare both against Empower before enabling Energy history.

## Local access and storage

No host ports, host network, privileged capabilities, or HA configuration mounts are requested. The browser desktop is available only through HA Ingress; the server accepts only Supervisor's documented gateway address. VNC and ChromeDriver bind locally inside the container. The browser is run as a separate unprivileged user without the Supervisor API token in its environment. The Python service alone uses that token for the internal Home Assistant API.

Chromium runs with `--no-sandbox` inside the protected app container because its additional sandbox is not assumed to work under Supervisor. Container isolation and AppArmor remain enabled. Use this dedicated browser only for Empower. The app requests Home Assistant API access and can therefore make authenticated Core API calls; install only reviewed code.

The browser profile contains session cookies. Treat app backups as sensitive. Backups are cold so the profile is copied with the app stopped. Raw interval arrays are sent in memory, not written to app logs/files. The integration separately persists readings under HA `.storage` and, when enabled, historical statistics in Recorder.

The app cannot verify that you selected the correct electricity meter when an account has multiple meters; this release supports one meter. Confirm the graph before the first read and keep that selection consistent.

## Status

This package was authored for Home Assistant OS 18.3 / Core 2026.9.3 on Home Assistant Blue. It has not been container-built or run on an ODROID in the development environment. ARM64 browser startup, Ingress, login acceptance and resource use require the installation test. Keep it experimental until those checks pass.

## Typing in the login form

Click the username field inside the remote browser before typing. On phones/tablets, open the noVNC toolbar using the handle at the left edge of the remote desktop, then tap its keyboard icon. Type the password directly into the portal. Version 0.1.1 adds the full remote desktop controls and a window manager for keyboard focus. After updating, close and reopen the app web UI to reload it. This fix still needs confirmation on the real device.
