"""CLI(python -m ctrip)测试:CDPProxy 注入替身,不连模拟器。"""

# pylint: disable=unused-argument,import-outside-toplevel
import time

import ctrip.__main__ as cli


class FakeCDP:
    """CDP 替身:Network.getAllCookies 直接回构造时给的 cookie 表。"""

    def __init__(self, cookies):
        self.cookies = cookies
        self.calls = []

    def call(self, method, params=None):
        self.calls.append(method)
        return {"cookies": self.cookies}


def test_cli_cookies(monkeypatch, capsys):
    future = time.time() + 60 * 86400
    cookies = [
        {"name": "cticket", "value": "x", "expires": future},
        {"name": "DUID", "value": "y", "expires": -1},
        {"name": "ibulanguage", "value": "zh", "expires": future + 999},
    ]
    import ctrip.client as client_mod
    monkeypatch.setattr(client_mod, "CDPProxy", lambda: FakeCDP(cookies))
    rc = cli.main(["cookies"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "cticket" in out
    assert "60天" in out
    assert "会话级" in out          # expires<=0 显示会话级
    assert "剩余 60 天" in out


def test_cli_cookies_expired(monkeypatch, capsys):
    past = time.time() - 86400
    cookies = [{"name": "cticket", "value": "x", "expires": past}]
    import ctrip.client as client_mod
    monkeypatch.setattr(client_mod, "CDPProxy", lambda: FakeCDP(cookies))
    rc = cli.main(["cookies"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "已过期" in out


def test_cli_cookies_no_ticket(monkeypatch, capsys):
    cookies = [{"name": "GUID", "value": "g", "expires": -1}]
    import ctrip.client as client_mod
    monkeypatch.setattr(client_mod, "CDPProxy", lambda: FakeCDP(cookies))
    rc = cli.main(["cookies"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "未发现 cticket" in out
    assert "机票查询不受影响" in out
