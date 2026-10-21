#!/usr/bin/env python3
"""CDP helper for driving the emulator WebView. Usage: python3 cdp.py [eval_js_file]"""
import json
import sys
import time
import urllib.request

import websocket

DEBUGGER = "http://127.0.0.1:9222"


def targets():
    return json.load(urllib.request.urlopen(f"{DEBUGGER}/json"))


def page_target(sub="airchina"):
    for tg in targets():
        if tg.get("type") == "page" and sub in tg.get("url", ""):
            return tg
    urls = ", ".join(tg.get("url", "") for tg in targets())
    raise SystemExit(f"no page target matching {sub}: {urls}")


class CDP:
    """Minimal CDP client: call(method, params) and eval(js)."""

    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=20)
        self.n = 0

    def call(self, method, params=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method,
                                 "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            # swallow events

    def eval(self, expr, await_promise=False):
        r = self.call("Runtime.evaluate", {
            "expression": expr, "returnByValue": True,
            "awaitPromise": await_promise, "userGesture": True})
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            desc = str(d.get("exception", {}).get("description", d))[:400]
            raise RuntimeError("JS error: " + desc)
        return r.get("result", {}).get("value")


if __name__ == "__main__":
    # default: attach to airchina page; argv: [js] [url to navigate to]
    url = next((a for a in sys.argv[1:] if a.startswith("http")), None)
    t = page_target("airchina")
    cdp = CDP(t["webSocketDebuggerUrl"])
    print("target:", t["url"][:80], file=sys.stderr)
    if url:
        cdp.call("Page.navigate", {"url": url})
        time.sleep(7)
    js = next((a for a in sys.argv[1:] if not a.startswith("http")), None) \
        or "location.href"
    print(json.dumps(cdp.eval(js, await_promise=True),
                     ensure_ascii=False, indent=1)[:6000])
