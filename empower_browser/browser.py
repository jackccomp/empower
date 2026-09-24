"""Visible browser on the HA machine. No stealth or site-protection bypasses."""
import math
import subprocess

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

BASE = "https://www.empowernaperville.com/"
EXTRACT = """
if (!['https://www.empowernaperville.com','https://empowernaperville.com'].includes(location.origin))
    return {error: 'wrong_page'};
if (typeof customerSDPPackage === 'undefined' || !customerSDPPackage?.meterReads)
    return {error: 'sign_in_required'};
const m = customerSDPPackage.meterReads;
return {version: 1, readsStartDate: m.readsStartDate, deliveredReads: m.deliveredReads};
"""


class BrowserFailure(Exception):
    pass


def safe_payload(raw):
    if not isinstance(raw, dict) or raw.get("error"):
        raise BrowserFailure("Sign in and open your electricity dashboard, then choose Read dashboard.")
    start = raw.get("readsStartDate")
    values = raw.get("deliveredReads")
    if not isinstance(start, str) or len(start) > 64:
        raise BrowserFailure("Dashboard timestamp was missing or invalid.")
    if isinstance(values, str):
        if len(values) > 7_000_000:
            raise BrowserFailure("Dashboard data is too large.")
        try:
            values = [float(value.strip()) for value in values.split(",")]
        except ValueError:
            raise BrowserFailure("Dashboard contains an invalid or empty interval.") from None
    if not isinstance(values, list) or not 1 <= len(values) <= 300_000:
        raise BrowserFailure("Dashboard readings were missing or too large.")
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise BrowserFailure("Dashboard contains non-numeric readings.")
        try:
            if not math.isfinite(value) or value < 0 or value > 1_000_000:
                raise BrowserFailure("Dashboard contains invalid energy readings.")
        except OverflowError:
            raise BrowserFailure("Dashboard contains invalid energy readings.") from None
    return {"version": 1, "readsStartDate": start, "deliveredReads": values}


class Browser:
    def __init__(self):
        self.driver = None

    def start(self):
        options = Options()
        options.binary_location = "/usr/bin/chromium"
        for arg in ("--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                    "--no-first-run", "--no-default-browser-check", "--window-size=1180,760",
                    "--user-data-dir=/data/profile", "--disable-breakpad",
                    "--disable-logging"):
            options.add_argument(arg)
        options.add_experimental_option("prefs", {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "profile.default_content_setting_values.notifications": 2,
        })
        # No cookies, authentication headers, logs, traces or screenshots are exported.
        env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
               "DISPLAY": ":99", "HOME": "/home/browser", "LANG": "C.UTF-8"}
        service = Service(executable_path="/app/driver.sh", log_output=subprocess.DEVNULL, env=env)
        try:
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver.set_page_load_timeout(60)
            self.driver.set_script_timeout(15)
            self.driver.get(BASE)
        except Exception:
            # Do not forward Selenium exceptions: they may include page/session details.
            self.close()
            raise BrowserFailure("Browser startup failed. Restart the app and check free memory.") from None

    def read(self, refresh=False):
        if self.driver is None:
            raise BrowserFailure("Browser is not ready. Restart the app.")
        try:
            if refresh:
                # Navigate to a known, non-secret URL rather than replaying a query.
                self.driver.get(BASE + "Dashboard")
            raw = self.driver.execute_script(EXTRACT)
            return safe_payload(raw)
        except BrowserFailure:
            raise
        except Exception:
            raise BrowserFailure("Could not read the dashboard. Sign in again or restart the app.") from None

    def open_login(self):
        if self.driver is None:
            self.start()
        else:
            self.driver.get(BASE)

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
