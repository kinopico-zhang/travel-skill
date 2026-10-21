#!/usr/bin/env python3
# pylint: disable=redefined-outer-name,unused-argument
"""Fill SMS code, enable subbtn, submit, solve captcha, report loginN.
Usage: submit_code.py <code>"""
import base64
import io
import json
import sys
import time
from cdp import CDP, targets
from login_driver import find_notch, state, drag
from PIL import Image
from mitmproxy import io as mio

FLOWS = "/tmp/airchina.flows"
CODE = sys.argv[1]


def login_target():
    ts = [t for t in targets() if t.get("type") == "page" and "airchina" in t.get("url", "")]
    for pref in ("/ac/c/invoke/login", "login@pg"):
        for t in ts:
            if pref in t["url"]:
                return t
    raise SystemExit("no airchina page target")


def read_flows():
    with open(FLOWS, "rb") as f:
        return [x for x in mio.FlowReader(f).stream() if x.type == "http"]


def last_generate(fl):
    for fw in reversed(fl):
        if "captcha/api/generate" in fw.request.path and fw.response:
            return json.loads(fw.response.get_text())["data"]
    return None


def dec_img(u):
    return Image.open(io.BytesIO(base64.b64decode(u.split(",", 1)[1])))


def fix_position(cdp):
    for _ in range(4):
        r = cdp.eval(r"""(() => {
            const t = document.querySelector('#tianai-captcha');
            if (!t) return null;
            t.style.setProperty('animation', 'none', 'important');
            t.style.setProperty('transition', 'none', 'important');
            t.style.setProperty('transform', 'translateX(0px)', 'important');
            t.style.setProperty('margin-left', '0px', 'important');
            ['#tianai-captcha-box', '#tianai-captcha-parent', '#captcha-box'].forEach(sel => {
                const e = document.querySelector(sel);
                if (e) e.style.setProperty('overflow', 'visible', 'important');
            });
            const b = document.querySelector('#tianai-captcha-slider-move-btn');
            if (!b) return null;
            let r = b.getBoundingClientRect();
            const dx = 135 - (r.left + r.width / 2);
            const dy = 160 - (r.top + r.height / 2);
            if (Math.abs(dx) > 10 || Math.abs(dy) > 20) {
                const tr = t.getBoundingClientRect();
                t.style.setProperty('left', (tr.left + dx) + 'px', 'important');
                t.style.setProperty('top', (tr.top + dy) + 'px', 'important');
                r = b.getBoundingClientRect();
            }
            return JSON.stringify({left: r.left, top: r.top, w: r.width, h: r.height,
                innerH: window.innerHeight});
        })()""")
        if r and '"left"' in r:
            d = json.loads(r)
            if abs(d["left"] + d["w"] / 2 - 135) < 15 and abs(d["top"] + d["h"] / 2 - 160) < 30:
                return r
    return r


def dom_synced(cdp, d):
    return cdp.eval("""(() => {
        const mv = document.querySelector('#tianai-captcha-slider-move-img');
        if (!mv) return false;
        const want = %d, src = (mv.src||'').length;
        if (Math.abs(src - want) > 50) return false;
        const bg = document.querySelector('#tianai-captcha-slider-bg-img');
        return !!(bg && (bg.src||'').length > 1000);
    })()""" % len(d["templateImage"]))


def check_result(cdp, cid):
    for fw in reversed(read_flows()):
        if "captcha/api/check" in fw.request.path and fw.response:
            req = json.loads(fw.request.get_text())
            if req.get("id") == cid:
                return json.loads(fw.response.get_text())
            return None
    return None


def solve_slider(cdp):
    prev_id = None
    for attempt in range(9):
        st = state(cdp)
        if not (st["captcha"] and st["handle"]):
            return None, "popup closed"
        cdp.eval("document.querySelector('#tianai-captcha-slider-refresh-btn').click(); 1")
        d = None
        for _ in range(12):
            time.sleep(0.6)
            d = last_generate(read_flows())
            if d and d["id"] != prev_id:
                break
        if not (d and d["id"] != prev_id):
            continue
        prev_id = d["id"]
        print(f"  [{attempt}] {d['type']} t={time.strftime('%H:%M:%S')}")
        if d["type"] != "SLIDER":
            time.sleep(1.2)
            continue
        ready = False
        for _ in range(10):
            time.sleep(0.5)
            if dom_synced(cdp, d):
                ready = True
                break
        if not ready:
            print("  DOM never synced")
            continue
        fix_position(cdp)
        st = state(cdp)
        if not (st["captcha"] and st["handle"]):
            return None, "popup closed before drag"
        bg = dec_img(d["backgroundImage"])
        piece = dec_img(d["templateImage"])
        x, score, _gw = find_notch(bg, piece)
        delta = x * (300.0 / d["backgroundImageWidth"])
        hd = st["handle"]
        sx, sy = hd["x"] + hd["width"] / 2, hd["y"] + hd["height"] / 2
        print(f"  notch={x} score={score:.0f} delta={delta:.1f}")
        drag(cdp, sx, sy, delta)
        time.sleep(2.5)
        out = check_result(cdp, d["id"])
        if out is None:
            st = state(cdp)
            if st["captcha"] and st["handle"]:
                hd = st["handle"]
                drag(cdp, hd["x"] + hd["width"] / 2, hd["y"] + hd["height"] / 2, delta)
                time.sleep(2.5)
                out = check_result(cdp, d["id"])
        if out is None:
            return None, "check never fired"
        print("  check:", out.get("code"), out.get("msg"))
        if out.get("success"):
            return out, None
        time.sleep(1.0)
    return None, "exhausted refreshes"


cdp = CDP(login_target()["webSocketDebuggerUrl"])

# 1. fill code
r = cdp.eval(r"""(() => {
    const inp = document.querySelector('#loginCode');
    if (!(inp instanceof HTMLInputElement)) return 'NO loginCode';
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(inp, '%s');
    inp.dispatchEvent(new Event('input', {bubbles: true}));
    inp.dispatchEvent(new Event('change', {bubbles: true}));
    window.readdangerFlag = true;
    checkFrom();
    const b = document.querySelector('#subbtn');
    return JSON.stringify({code: inp.value, btnEnabled: !b.className.includes('am-disabled')});
})()""" % CODE)
print("fill:", r)
if '"btnEnabled":true' not in r:
    print("BUTTON NOT ENABLED - abort")
    sys.exit(2)

# 2. clean stale captcha DOM, click submit
cdp.eval(r"""(() => {
    document.querySelectorAll('#captcha-box, #tianai-captcha-parent, #tianai-captcha').forEach(e => e.remove());
    const box = document.createElement('div');
    box.id = 'captcha-box';
    box.className = 'captcha-container';
    box.style.zIndex = '10005';
    document.body.appendChild(box);
    return 1;
})()""")
time.sleep(0.3)
cdp.eval("$('#subbtn').click(); 1")
print("clicked submit", time.strftime("%H:%M:%S"))

# 3. wait for real popup
popup = False
for _ in range(15):
    time.sleep(1)
    st = state(cdp)
    if st["captcha"] and st["handle"]:
        popup = True
        break
print("popup:", popup)

out, err = solve_slider(cdp)
if out and out.get("success"):
    print("CAPTCHA PASSED", time.strftime("%H:%M:%S"))
else:
    print("CAPTCHA FAILED:", err)
    sys.exit(3)

# 4. watch for loginN
t0 = time.time()
for i in range(20):
    time.sleep(1.5)
    for fw in read_flows():
        if "loginN" in fw.request.path and fw.response and fw.timestamp_start > t0:
            print("=== loginN", time.strftime("%H:%M:%S", time.localtime(fw.timestamp_start)))
            print("RSP:", (fw.response.get_text() or "")[:400])
            sys.exit(0)
print("no loginN seen in 30s")
