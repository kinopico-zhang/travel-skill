#!/usr/bin/env python3
# pylint: disable=redefined-outer-name,unused-argument,too-many-statements
"""Complete Air China H5 login in ONE CDP connection.

Usage: login_flow.py sms|submit|new

  new    -> fresh page load, fill phone, send SMS (captcha solve), report
  submit -> assumes code already filled, submits login (captcha solve)
  sms    -> just send SMS on the current page state
"""
import base64
import io
import json
import sys
import time
from cdp import CDP, targets
from login_driver import find_notch, load_phone, state, drag
from PIL import Image
from mitmproxy import io as mio

FLOWS = "/tmp/airchina.flows"


def login_target():
    """The app's own redirect (/ac/c/invoke/login?comeUrl=...) is a rendered form;
    a bare /c/invoke/login tab can sit wedged in readyState=loading forever."""
    ts = [t for t in targets() if t.get("type") == "page" and "airchina" in t.get("url", "")]
    for pref in ("/ac/c/invoke/login", "login@pg"):
        for t in ts:
            if pref in t["url"]:
                return t
    raise SystemExit("no airchina page target")


cdp = CDP(login_target()["webSocketDebuggerUrl"])
mode = sys.argv[1] if len(sys.argv) > 1 else "sms"

if mode == "new":
    form_here = cdp.eval(r"""document.readyState === 'complete' &&
                             document.querySelector('#phone') instanceof HTMLInputElement""")
    if form_here:
        print("login form already rendered, using it")
    else:
        print("loading fresh login page...")
        cdp.call("Page.navigate", {"url": "https://m.airchina.com.cn/c/invoke/login@pg"})
        time.sleep(3)
        for _ in range(25):
            time.sleep(1)
            if cdp.eval(r"""document.readyState === 'complete' &&
                           document.querySelector('#phone') instanceof HTMLInputElement"""):
                break
        if not cdp.eval(r"""document.querySelector('#phone') instanceof HTMLInputElement"""):
            st = cdp.eval(r"""location.href + ' | ' + document.readyState + ' | inputs=' +
                              document.querySelectorAll('input').length""")
            print("login form never appeared:", st)
            sys.exit(2)
        print("form ready")
    cdp.eval(r"""(() => {
        const inp = document.querySelector('#phone');
        if (!(inp instanceof HTMLInputElement)) return 'NO #phone input';
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(inp, '%s');
        inp.dispatchEvent(new Event('input', {bubbles: true}));
        inp.dispatchEvent(new Event('change', {bubbles: true}));
        return document.querySelector('#phone').value;
    })()""" % load_phone())
    print("phone filled:", cdp.eval("document.querySelector('#phone').value"))
    time.sleep(1)


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
    # viewport on these pages is only ~204px tall; drag the whole popup so the
    # handle center lands at (135, 160) - inside the visible area
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
    """Refresh until a SLIDER shows, then solve it. Returns check response."""
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
            print("no new generate; prev:", (prev_id or "")[:20])
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
        h = fix_position(cdp)
        print("  handle:", h)
        st = state(cdp)
        if not (st["captcha"] and st["handle"]):
            return None, "popup closed before drag"
        bg = dec_img(d["backgroundImage"])
        piece = dec_img(d["templateImage"])
        x, score, _gw = find_notch(bg, piece)
        delta = x * (300.0 / d["backgroundImageWidth"])
        hd = st["handle"]
        sx, sy = hd["x"] + hd["width"] / 2, hd["y"] + hd["height"] / 2
        print(f"  notch={x} score={score:.0f} delta={delta:.1f} from ({sx:.0f},{sy:.0f})")
        if hd["x"] > 400 or hd["x"] < 0:
            fix_position(cdp)
            time.sleep(0.4)
            st = state(cdp)
            hd = st["handle"]
            sx, sy = hd["x"] + hd["width"] / 2, hd["y"] + hd["height"] / 2
        drag(cdp, sx, sy, delta)
        time.sleep(2.5)
        out = check_result(cdp, d["id"])
        if out is None:
            print("  no check fired; retry drag")
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


st = state(cdp)
print(f"state: captcha={st['captcha']} sms={st['smsText']}")
if not (st["captcha"] and st["handle"]):
    # clean any stale captcha DOM, then trigger
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
    TRIGGER = "#subbtn" if mode == "submit" else "#getSmsCode1"
    cdp.eval(f"$('{TRIGGER}').click(); 1")
    for _ in range(15):
        time.sleep(1)
        st = state(cdp)
        if st["captcha"] and st["handle"]:
            break
    print(f"popup: captcha={st['captcha']}")

out, err = solve_slider(cdp)
if out and out.get("success"):
    print("CAPTCHA PASSED", time.strftime("%H:%M:%S"))
    if mode == "submit":
        # watch for loginN
        t0 = time.time()
        for i in range(16):
            time.sleep(1.5)
            for fw in read_flows():
                if "loginN" in fw.request.path and fw.response and fw.timestamp_start > t0:
                    print("=== loginN", fw.request.host + fw.request.path)
                    print("RSP:", (fw.response.get_text() or "")[:500])
                    sys.exit(0)
    else:
        for i in range(16):
            time.sleep(1.5)
            st = state(cdp)
            if st["smsText"] and ("s" in st["smsText"] or "重新" in st["smsText"]):
                print("SMS SENT, countdown:", st["smsText"])
                sys.exit(0)
        print("captcha passed but no countdown; sms:", st["smsText"])
else:
    print("FAILED:", err)
