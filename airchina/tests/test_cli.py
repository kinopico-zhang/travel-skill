"""CLI(python -m airchina)测试:load 注入替身,不触网。"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument,import-outside-toplevel
import json

import pytest

import airchina.__main__ as cli
from airchina import AirChinaClient, AirChinaError, CookieExpiredError
from airchina.models import AwardResult, DailyPrice, MileageSummary
from airchina.session import Session


class StubClient(AirChinaClient):
    """按需覆盖接口方法的 CLI 替身。"""

    def __init__(self, sample_session):
        super().__init__(sample_session)


@pytest.fixture
def stub(sample_session):
    return StubClient(sample_session)


def _patch_load(monkeypatch, stub):
    monkeypatch.setattr(AirChinaClient, "load", lambda: stub)


def test_cli_award(award_ow, stub, monkeypatch, capsys):
    monkeypatch.setattr(stub, "award_search",
                        lambda *a, **kw: AwardResult.parse(award_ow))
    _patch_load(monkeypatch, stub)
    rc = cli.main(["award", "CAN", "HAK", "2026-10-27"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "去程 2 班" in out
    assert "5600里程" in out


def test_cli_award_empty(stub, monkeypatch, capsys):
    r = AwardResult(code="00000000", message="抱歉，暂时没有可兑换航班啦。")
    monkeypatch.setattr(stub, "award_search", lambda *a, **kw: r)
    _patch_load(monkeypatch, stub)
    rc = cli.main(["award", "CAN", "KHN", "2026-11-15"])
    assert rc == 0
    assert "无可兑换航班" in capsys.readouterr().out


def test_cli_calendar(stub, monkeypatch, capsys):
    prices = [DailyPrice(date="2026-11-07", price=1500),
              DailyPrice(date="2026-11-08", price=1400)]
    monkeypatch.setattr(stub, "low_price_calendar", lambda *a: prices)
    _patch_load(monkeypatch, stub)
    rc = cli.main(["calendar", "CAN", "PEK", "2026-11-07"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "2026-11-07  ¥1500" in out
    assert "2026-11-08  ¥1400" in out


def test_cli_account(stub, monkeypatch, capsys):
    monkeypatch.setattr(stub, "mileage_summary",
                        lambda: MileageSummary(code="00000000", msg="成功",
                                               mileage=12300, tierName="银卡"))
    _patch_load(monkeypatch, stub)
    rc = cli.main(["account"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "mileage: 12300" in out


def test_cli_keepalive_once_ok(stub, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(stub, "keepalive_ping",
                        lambda deep=False: [DailyPrice(date="2026-10-27", price=1)])
    _patch_load(monkeypatch, stub)
    hb = tmp_path / "hb.json"
    rc = cli.main(["keepalive", "--once", "--heartbeat", str(hb)])
    assert rc == 0
    assert "OK(日历) 返回1天票价" in capsys.readouterr().out
    d = json.loads(hb.read_text())
    assert d["ok"] is True and d["ts"] > 0 and d["err"] == ""


def test_cli_keepalive_once_cookie_expired(stub, monkeypatch, tmp_path):
    def boom(deep=False):
        raise CookieExpiredError("返回了 HTML(登录页)")
    monkeypatch.setattr(stub, "keepalive_ping", boom)
    _patch_load(monkeypatch, stub)
    hb = tmp_path / "hb.json"
    rc = cli.main(["keepalive", "--once", "--heartbeat", str(hb)])
    assert rc == 1
    d = json.loads(hb.read_text())
    assert d["ok"] is False and "HTML" in d["err"]


def test_cli_keepalive_once_transient_error(stub, monkeypatch, tmp_path):
    def boom(deep=False):
        raise AirChinaError("HTTP 502 Bad Gateway")
    monkeypatch.setattr(stub, "keepalive_ping", boom)
    _patch_load(monkeypatch, stub)
    hb = tmp_path / "hb.json"
    rc = cli.main(["keepalive", "--once", "--heartbeat", str(hb)])
    assert rc == 1                     # --once: 瞬时错误也不进退避循环
    assert json.loads(hb.read_text())["ok"] is False


def test_cli_keepalive_deep_ok(stub, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(stub, "keepalive_ping",
                        lambda deep=False: MileageSummary(code="00000000",
                                                          mileage=12300))
    _patch_load(monkeypatch, stub)
    hb = tmp_path / "hb.json"
    rc = cli.main(["keepalive", "--once", "--deep", "--heartbeat", str(hb)])
    assert rc == 0
    assert "OK(账户) 里程≈12300" in capsys.readouterr().out


def test_cli_session(monkeypatch, capsys, tmp_path, sample_session):
    monkeypatch.setattr(Session, "from_flows",
                        classmethod(lambda cls, path: sample_session))
    out_path = tmp_path / "session.json"
    rc = cli.main(["session", "--from-flows", "/tmp/fake.flows",
                   "--save", str(out_path)])
    assert rc == 0
    assert "saved ->" in capsys.readouterr().out
    assert Session.load(str(out_path)) == sample_session


def test_cli_missing_session(monkeypatch, capsys):
    monkeypatch.setattr(AirChinaClient, "load",
                        lambda: (_ for _ in ()).throw(FileNotFoundError()))
    rc = cli.main(["award", "CAN", "PEK", "2026-10-21"])
    assert rc == 2
    assert "会话文件不存在" in capsys.readouterr().err
