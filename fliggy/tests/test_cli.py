"""CLI 测试:mock 客户端,不触网。"""
import pytest

from fliggy import FliggyError
from fliggy.__main__ import main


class FakeClient:
    """替身客户端,记录 search 参数。"""

    def __init__(self):
        self.kwargs = None

    def search(self, dep, arr, date):
        self.kwargs = (dep, arr, date)
        return FakeResult()


class FakeResult:
    """替身结果。"""

    # pylint: disable=too-few-public-methods
    def summary(self, direct_only=False):
        return ("A→B 2026-12-26 共10班(直飞)"
                if direct_only else "A→B 2026-12-26 共31班/直飞10")


def test_cli_flights(monkeypatch, capsys):
    fake = FakeClient()
    monkeypatch.setattr("fliggy.client.FliggyClient", lambda: fake)
    rc = main(["flights", "CAN", "PEK", "2026-12-26"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "共31班/直飞10" in out
    assert fake.kwargs == ("CAN", "PEK", "2026-12-26")


def test_cli_flights_direct(monkeypatch, capsys):
    fake = FakeClient()
    monkeypatch.setattr("fliggy.client.FliggyClient", lambda: fake)
    rc = main(["flights", "CAN", "PEK", "2026-12-26", "--direct"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "共10班(直飞)" in out


def test_cli_error(monkeypatch, capsys):
    class Boom:
        """替身客户端:查询必炸。"""

        # pylint: disable=too-few-public-methods
        def search(self, dep, arr, date):
            raise FliggyError("RGV587 无线保镖拦截")

    monkeypatch.setattr("fliggy.client.FliggyClient", Boom)
    rc = main(["flights", "CAN", "PEK", "2026-12-26"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "RGV587" in err


def test_cli_bad_args():
    """参数不足时 argparse SystemExit(非零)。"""
    with pytest.raises(SystemExit) as e:
        main(["flights", "only-one-arg"])
    assert e.value.code != 0
