#!/usr/bin/env python3
"""携程 H5 登录驱动。
用法: ctrip_login.py sms|submit <code>"""
import json
from pathlib import Path
import sys
import time
import urllib.request

from cdp import CDP

PHONE_PROFILE = Path.home() / ".ctrip" / "profile.json"


def load_phone() -> str:
    """手机号属敏感信息不入库:读 ~/.ctrip/profile.json 的 phone 字段。"""
    try:
        return str(json.loads(PHONE_PROFILE.read_text(encoding="utf-8"))["phone"])
    except (OSError, KeyError, ValueError) as e:
        raise SystemExit(
            f"缺手机号:请创建 {PHONE_PROFILE},内容如 {{\"phone\": \"1xxxxxxxxxx\"}}") from e


def get_cdp():
    with urllib.request.urlopen("http://127.0.0.1:9222/json") as r:
        targets = json.loads(r.read())
    t = [x for x in targets if x["type"] == "page"][0]
    return CDP(t["webSocketDebuggerUrl"])


def tap(cdp, x, y):
    cdp.call("Input.dispatchTouchEvent", {"type": "touchStart",
                                          "touchPoints": [{"x": x, "y": y, "id": 1}]})
    time.sleep(0.08)
    cdp.call("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})


def page_state(cdp):
    return cdp.eval(r'''(() => {
    const inp = document.querySelector('input[type=tel]');
    const code = [...document.querySelectorAll('input[type=text]')].find(i =>
        (i.placeholder||'').includes('验证码'));
    const btn = [...document.querySelectorAll('button, div, span, a')].find(e =>
        (e.innerText||'').trim() === '获取验证码');
    const log = [...document.querySelectorAll('button, div, span, a')].find(e =>
        (e.innerText||'').trim() === '登录');
    const r = e => e ? (() => { const b = e.getBoundingClientRect();
        return {x: Math.round(b.x + b.width/2), y: Math.round(b.y + b.height/2),
                t: (e.innerText||'').trim().slice(0,12)}; })() : null;
    return JSON.stringify({
        url: location.href.slice(-40),
        phone: inp ? inp.value : null,
        code: code ? code.value : null,
        smsBtn: r(btn), loginBtn: r(log),
        body: (document.body.innerText||'').replace(/\s+/g,' ').slice(0,120)
    });
})()''')


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "sms"
    code = sys.argv[2] if len(sys.argv) > 2 else ""
    cdp = get_cdp()

    if mode == "sms":
        # 填手机号
        r = cdp.eval(r'''(() => {
    const inp = document.querySelector('input[type=tel]');
    if (!inp) return 'NO phone input';
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(inp, '%s');
    inp.dispatchEvent(new Event('input', {bubbles: true}));
    inp.dispatchEvent(new Event('change', {bubbles: true}));
    return inp.value;
})()''' % load_phone())
        print("phone:", r)
        time.sleep(1)
        st = json.loads(page_state(cdp))
        print("state:", st)
        if st["smsBtn"]:
            tap(cdp, st["smsBtn"]["x"], st["smsBtn"]["y"])
            print("tapped 获取验证码")
        # 观察结果:倒计时/弹窗/报错
        for i in range(15):
            time.sleep(1)
            s = json.loads(page_state(cdp))
            if i % 3 == 0 or "重新" in json.dumps(s, ensure_ascii=False):
                print(i, s["smsBtn"], s["body"][:60] if i % 6 == 0 else "")
            if s["smsBtn"] and ("重新" in s["smsBtn"]["t"] or "s" in s["smsBtn"]["t"][-3:]):
                print("SMS SENT?", s["smsBtn"])
                break
    elif mode == "submit":
        r = cdp.eval(r'''(() => {
    const code = [...document.querySelectorAll('input[type=text]')].find(i =>
        (i.placeholder||'').includes('验证码'));
    if (!code) return 'NO code input';
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(code, '%s');
    code.dispatchEvent(new Event('input', {bubbles: true}));
    code.dispatchEvent(new Event('change', {bubbles: true}));
    return code.value;
})()''' % code)
        print("code:", r)
        time.sleep(1)
        st = json.loads(page_state(cdp))
        print("state:", st)
        if st["loginBtn"]:
            tap(cdp, st["loginBtn"]["x"], st["loginBtn"]["y"])
            print("tapped 登录")
        for i in range(15):
            time.sleep(1)
            try:
                u = cdp.eval("location.href")
                s = json.loads(page_state(cdp))
                if "login" not in u.lower():
                    print("NAVIGATED ->", u)
                    break
                if i % 4 == 0:
                    print(i, s["body"][:80])
            except Exception:  # pylint: disable=broad-exception-caught
                pass


if __name__ == "__main__":
    main()
