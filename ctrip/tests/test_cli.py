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


class StubTrainClient:
    """train 子命令替身:记录参数,弹回夹具解析结果。"""

    def __init__(self, resp):
        from ctrip.models import TrainSearchResult
        self.result = TrainSearchResult.parse(resp)
        self.calls = []

    def train_search(self, depart, arrive, date, student=False):
        self.calls.append((depart, arrive, date, student))
        return self.result


def test_cli_train(monkeypatch, capsys, train_search_resp):
    import ctrip.client as client_mod
    stub = StubTrainClient(train_search_resp)
    monkeypatch.setattr(client_mod, "CtripClient", lambda: stub)
    rc = cli.main(["train", "上海", "北京", "2026-10-22"])
    out = capsys.readouterr().out
    assert rc == 0
    assert stub.calls == [("上海", "北京", "2026-10-22", False)]
    assert "共54班" in out and "G532" in out
    assert "06:31-12:18" in out and "5小时47分" in out
