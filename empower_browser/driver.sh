#!/bin/sh
# ChromeDriver and Chromium run without the Supervisor token, as a separate user.
exec runuser -u browser -- /usr/bin/chromedriver "$@"
