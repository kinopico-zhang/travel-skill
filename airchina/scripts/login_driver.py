#!/usr/bin/env python3
# pylint: disable=too-many-statements
"""One-session Air China H5 login driver.

Holds a portrait viewport override, re-triggers the captcha, solves the
slider with trusted CDP input events, reports the outcome.
Run with -u for live output.
"""
import base64
import io
import json
import math
import re
import time
from pathlib import Path
from cdp import CDP, page_target
from PIL import Image

STEPS = 40

PHONE_PROFILE = Path.home() / ".airchina" / "profile.json"


def load_phone() -> str:
    """手机号属敏感信息不入库:读 ~/.airchina/profile.json 的 phone 字段。"""
    try:
        return str(json.loads(PHONE_PROFILE.read_text(encoding="utf-8"))["phone"])
    except (OSError, KeyError, ValueError) as e:
        raise SystemExit(
            f"缺手机号:请创建 {PHONE_PROFILE},内容如 {{\"phone\": \"1xxxxxxxxxx\"}}") from e


def imgs(cdp):
    src = cdp.eval("""(() => {
        const bg = document.querySelector('#tianai-captcha-slider-bg-img');
        const mv = document.querySelector('#tianai-captcha-slider-move-img');
        return bg && mv ? JSON.stringify({bg: bg.src, mv: mv.src}) : null;
    })()""")
    if not src:
        return None, None
    d = json.loads(src)
    def dec(u):
        return Image.open(io.BytesIO(base64.b64decode(u.split(",", 1)[1])))
    return dec(d["bg"]), dec(d["mv"])


def find_notch(bg, piece):
    pa = piece.split()[-1]
    pw, ph = piece.size
    mask = [[1 if pa.getpixel((x, y)) > 128 else 0 for x in range(pw)] for y in range(ph)]
    n_op = sum(map(sum, mask))
    g = bg.convert("L")
    gw, _gh = g.size
    best, best_x = -1.0, 0
    for x0 in range(0, gw - pw, 2):
        s = 0
        for y in range(0, ph, 2):
            row = mask[y]
            for x in range(0, pw, 2):
                if row[x]:
                    s += 255 - g.getpixel((min(x0 + x, gw - 1), y))
        sc = s / (n_op / 4)
        if sc > best:
            best, best_x = sc, x0
    return best_x, best, gw


def captcha_type(cdp):
    return cdp.eval("""(() => {
        const loading = document.querySelector('#tianai-captcha-loading');
        if (loading && loading.style.display !== 'none' && loading.offsetParent !== null) return 'LOADING';
        const mv = document.querySelector('#tianai-captcha-slider-move-img');
        if (mv && (mv.src||'').length > 100) return 'SLIDER';
        const cat = document.querySelector('#tianai-captcha-slider-concat-slider-img');
        if (cat) return 'CONCAT';
        const rot = document.querySelector('[id*=rotate]');
        if (rot) return 'ROTATE';
        const bg = document.querySelector('#tianai-captcha-slider-bg-img');
        return (bg && (bg.src||'').length > 100) ? 'SLIDER_NOPIECE' : 'UNKNOWN';
    })()""")


def refresh_captcha(cdp):
    cdp.eval("document.querySelector('#tianai-captcha-slider-refresh-btn').click(); 1")


def state(cdp):
    return json.loads(cdp.eval("""(() => {
        const box = document.querySelector('#captcha-box');
        const btn = document.querySelector('#tianai-captcha-slider-move-btn');
        const sms = document.querySelector('#getSmsCode1');
        const toasts = [...document.querySelectorAll('.am-toast, .vant-toast, [class*=toast]')].map(t => (t.innerText||'').trim()).filter(Boolean);
        return JSON.stringify({captcha: !!(box && box.offsetParent !== null),
            handle: btn ? btn.getBoundingClientRect().toJSON() : null,
            smsText: sms ? sms.innerText.trim() : null, toasts,
            vw: innerWidth});
    })()"""))


def drag(cdp, sx, sy, delta):
    cdp.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": sx, "y": sy,
                 "button": "left", "buttons": 1, "clickCount": 1})
    for i in range(1, STEPS + 1):
        frac = i / STEPS
        e = 1 - math.pow(1 - frac, 2.2)
        jx = sx + delta * e + (0.5 - (i % 3) / 3.0) * 1.6
        jy = sy + (0.5 - ((i * 7) % 5) / 5.0) * 1.4
        cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": jx, "y": jy,
                     "button": "left", "buttons": 1})
        time.sleep(0.014)
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": sx + delta, "y": sy,
                 "button": "left", "buttons": 1})
    time.sleep(0.08)
    cdp.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": sx + delta, "y": sy,
                 "button": "left", "buttons": 0, "clickCount": 1})


def main():
    phone = load_phone()
    cdp = CDP(page_target("airchina")["webSocketDebuggerUrl"])
    # page should already be loaded fresh; wait for the form
    for _ in range(20):
        if cdp.eval("!!document.querySelector('#getSmsCode1')"):
            break
        time.sleep(1)
    print("form ready:", cdp.eval("!!document.querySelector('#getSmsCode1')"))

    # fill phone
    cdp.eval("""(() => {
        const inp = document.querySelector('#phone');
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(inp, '%s');
        inp.dispatchEvent(new Event('input', {bubbles: true}));
        inp.dispatchEvent(new Event('change', {bubbles: true}));
        return inp.value;
    })()""" % phone)
    print("phone:", cdp.eval("document.querySelector('#phone').value"))

    for attempt in range(4):
        time.sleep(1)
        st = state(cdp)
        print(f"[{attempt}] state: captcha={st['captcha']} vw={st['vw']} sms={st['smsText']}")
        if st["smsText"] and re.search(r"\d+\s*s|重新发送", st["smsText"]):
            print("SUCCESS: countdown started, SMS sent!")
            return
        if not (st["captcha"] and st["handle"]):
            # trigger captcha (recreate empty box first if missing)
            cdp.eval("""(() => {
                let box = document.querySelector('#captcha-box');
                if (!box) {
                    box = document.createElement('div');
                    box.id = 'captcha-box';
                    box.className = 'captcha-container';
                    box.style.zIndex = '10005';
                    document.body.appendChild(box);
                }
                $('#getSmsCode1').click();
                return 1;
            })()""")
            for _ in range(15):
                time.sleep(1)
                s2 = state(cdp)
                if s2["captcha"] and s2["handle"]:
                    break
            st = state(cdp)
        if not (st["captcha"] and st["handle"]):
            print("captcha did not appear; toasts:", st["toasts"])
            continue
        # cycle captcha type until we get a solvable SLIDER puzzle
        ctype = captcha_type(cdp)
        tries = 0
        while ctype != "SLIDER" and tries < 6:
            print(f"[{attempt}] captcha type={ctype}, refreshing ({tries+1}/6)")
            refresh_captcha(cdp)
            time.sleep(2.5)
            ctype = captcha_type(cdp)
            tries += 1
            st = state(cdp)
            if st["smsText"] and re.search(r"\d+\s*s|重新发送", st["smsText"]):
                print("SUCCESS during refresh? countdown started")
                return
        if ctype != "SLIDER":
            print(f"[{attempt}] could not get SLIDER type (last={ctype})")
            continue
        bg, piece = imgs(cdp)
        if not bg:
            print("no images yet")
            continue
        x, score, gw = find_notch(bg, piece)
        delta = x * (300.0 / gw)
        h = st["handle"]
        sx, sy = h["x"] + h["width"] / 2, h["y"] + h["height"] / 2
        print(f"[{attempt}] notch img-x={x} score={score:.0f}"
              f" delta={delta:.1f}px handle=({sx:.0f},{sy:.0f}) vw={st['vw']}")
        drag(cdp, sx, sy, delta)
        time.sleep(3.5)
        st2 = state(cdp)
        print(f"[{attempt}] after: captcha={st2['captcha']}"
              f" sms={st2['smsText']} toasts={st2['toasts']}")
        if st2["smsText"] and re.search(r"\d+\s*s|重新发送", st2["smsText"]):
            print("SUCCESS: countdown started, SMS sent!")
            return
        # failure -> captcha usually auto-refreshes; loop will re-solve
        time.sleep(1.5)
    print("gave up after 4 attempts")


if __name__ == "__main__":
    main()
