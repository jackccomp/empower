"""Ingress-only desktop and reader. All API/browser error output is sanitized."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import datetime, timedelta, timezone
import json
import html
import os
from pathlib import Path
import subprocess
import time

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web
from browser import Browser, BrowserFailure

APP_ROOT = Path(__file__).parent
CORE_URL = "http://supervisor/core/api/empower_naperville/readings"
STATE = web.AppKey("state", dict)


def summary(payload):
    try:
        first = datetime.fromisoformat(payload["readsStartDate"].replace("Z", "+00:00"))
        latest = first + timedelta(minutes=15 * (len(payload["deliveredReads"]) - 1))
    except (ValueError, OverflowError):
        raise BrowserFailure("Dashboard timestamp is invalid.") from None
    return {"count": len(payload["deliveredReads"]), "first": first.isoformat(),
            "first_kwh": payload["deliveredReads"][0], "latest": latest.isoformat(),
            "latest_kwh": payload["deliveredReads"][-1]}


@web.middleware
async def ingress_only(request, handler):
    # Supervisor's documented ingress gateway address. Ignore spoofable forwarding headers.
    if request.remote != "172.30.32.2":
        raise web.HTTPForbidden(text="Use Home Assistant to open this app.")
    if request.method == "POST" and request.headers.get("X-Empower-Action") != "1":
        raise web.HTTPForbidden(text="Use the app controls.")
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception:
        return web.json_response({"error": "operation_failed"}, status=500)


async def index(request):
    # Ingress may serve the entry URL without a trailing slash. A validated
    # base preserves its prefix for both ES modules and websocket/API paths.
    prefix = request.headers.get("X-Ingress-Path", "")
    if not prefix.startswith("/api/hassio_ingress/") or any(c in prefix for c in "?#\\"):
        raise web.HTTPBadRequest(text="Open this app through Home Assistant.")
    base = html.escape(prefix.rstrip("/") + "/", quote=True)
    content = await asyncio.to_thread((APP_ROOT / "web" / "index.html").read_text)
    return web.Response(text=content.replace("__INGRESS_BASE__", base), content_type="text/html")


async def status(request):
    state = request.app[STATE]
    return web.json_response({k: state[k] for k in ("message", "summary", "last_attempt")})


async def browser_call(state, function, *args):
    return await asyncio.get_running_loop().run_in_executor(state["pool"], function, *args)


async def collect(state, refresh):
    async with state["lock"]:
        state["last_attempt"] = datetime.now(timezone.utc).isoformat()
        try:
            payload = await browser_call(state, state["browser"].read, refresh)
            state["summary"] = summary(payload)
            state["armed"] = True
            token = os.environ.get("SUPERVISOR_TOKEN")
            if not token:
                state["message"] = "Readings retrieved. Home Assistant API access is unavailable."
                return
            async with ClientSession(timeout=ClientTimeout(total=90)) as session:
                async with session.post(CORE_URL, json=payload,
                                        headers={"Authorization": "Bearer " + token},
                                        allow_redirects=False) as response:
                    if response.status == 200:
                        state["message"] = "Readings sent to Home Assistant. Daily refresh is active while this app runs."
                    elif response.status in (404, 503):
                        state["message"] = "Readings retrieved. Install or enable the Empower Naperville integration, then read again."
                    elif response.status in (401, 403):
                        state["message"] = "Readings retrieved. Home Assistant rejected API authorization; restart the app."
                    elif response.status == 400:
                        state["message"] = "Readings retrieved but rejected by the integration. Check time settings and history range; a changed or shorter range requires reconciliation."
                    else:
                        state["message"] = "Readings retrieved, but Home Assistant could not accept them. Retry later."
        except BrowserFailure as err:
            state["message"] = str(err)
        except Exception:
            state["message"] = "Could not complete the transfer. Check Home Assistant and sign in again if needed."


async def action(request):
    state = request.app[STATE]
    if state["lock"].locked():
        return web.json_response({"error": "busy"}, status=409)
    if request.match_info["action"] == "login":
        async with state["lock"]:
            try:
                await browser_call(state, state["browser"].open_login)
                state["message"] = "Sign in below, open the dashboard, then choose Read dashboard."
            except Exception:
                state["message"] = "Could not open the login page. Restart the app."
    else:
        await collect(state, request.match_info["action"] == "refresh")
    return web.json_response({"ok": True})


async def desktop(request):
    """noVNC's binary websocket frames map directly to the local RFB stream."""
    reader, writer = await asyncio.open_connection("127.0.0.1", 5900)
    ws = web.WebSocketResponse(protocols=("binary",), max_msg_size=2 * 1024 * 1024)
    await ws.prepare(request)

    async def from_browser():
        async for message in ws:
            if message.type == WSMsgType.BINARY:
                writer.write(message.data)
                await writer.drain()
            elif message.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break

    async def to_browser():
        while data := await reader.read(65536):
            await ws.send_bytes(data)

    tasks = [asyncio.create_task(from_browser()), asyncio.create_task(to_browser())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        writer.close()
        with suppress(Exception):
            await writer.wait_closed()
        await ws.close()
    return ws


async def lifecycle(app):
    state = app[STATE]
    async def start_browser():
        async with state["lock"]:
            try:
                await browser_call(state, state["browser"].start)
                state["message"] = "Sign in below, open the electricity dashboard, then choose Read dashboard."
            except BrowserFailure as err:
                state["message"] = str(err)
    async def daily():
        while True:
            await asyncio.sleep(state["refresh_hours"] * 3600)
            if state["armed"]:
                await collect(state, True)
    startup = asyncio.create_task(start_browser())
    timer = asyncio.create_task(daily())
    yield
    timer.cancel()
    await asyncio.gather(timer, return_exceptions=True)
    # Selenium calls have bounded timeouts and execute in one worker thread.
    await asyncio.gather(startup, return_exceptions=True)
    await browser_call(state, state["browser"].close)
    state["pool"].shutdown(wait=False, cancel_futures=True)


def create_app(browser=None, refresh_hours=24):
    app = web.Application(middlewares=[ingress_only], client_max_size=1024)
    app[STATE] = {"browser": browser or Browser(), "pool": ThreadPoolExecutor(max_workers=1),
                  "lock": asyncio.Lock(), "message": "Starting browser…", "summary": None,
                  "last_attempt": None, "armed": False, "refresh_hours": refresh_hours}
    app.router.add_get("/", index)
    app.router.add_get("/status", status)
    app.router.add_get("/desktop", desktop)
    app.router.add_post("/{action:read|refresh|login}", action)
    app.router.add_static("/novnc/", "/opt/novnc", show_index=False)
    app.cleanup_ctx.append(lifecycle)
    return app


def main():
    os.umask(0o077)
    os.chmod("/data", 0o711)
    profile = Path("/data/profile")
    profile.mkdir(parents=True, exist_ok=True)
    os.chown(profile, 1000, 1000)
    options = json.loads(Path("/data/options.json").read_text())
    refresh_hours = int(options.get("refresh_hours", 24))
    if not 6 <= refresh_hours <= 168:
        raise ValueError("Invalid refresh interval")
    # These children never receive the Supervisor token.
    env = {"PATH": "/usr/bin:/bin", "DISPLAY": ":99", "HOME": "/home/browser"}
    children = []
    try:
        children.append(subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x900x24", "-nolisten", "tcp", "-ac"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        for _ in range(100):
            if Path("/tmp/.X11-unix/X99").exists():
                break
            if children[0].poll() is not None:
                raise RuntimeError("Display failed")
            time.sleep(0.1)
        children.append(subprocess.Popen(["x11vnc", "-display", ":99", "-localhost", "-forever", "-shared", "-nopw", "-rfbport", "5900", "-quiet"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        web.run_app(create_app(refresh_hours=refresh_hours), host="0.0.0.0", port=8099, access_log=None, print=None)
    finally:
        for child in children:
            child.terminate()
        for child in children:
            with suppress(subprocess.TimeoutExpired):
                child.wait(timeout=5)
            if child.poll() is None:
                child.kill()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Empower Browser could not start. Restart the app and check free memory.", flush=True)
        raise SystemExit(1)
