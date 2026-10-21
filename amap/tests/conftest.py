# pylint: disable=protected-access,redefined-outer-name,unused-argument,import-outside-toplevel
"""共享夹具:两条真实导航响应(短途/长途)。"""
import pytest


def _fixture(name: str) -> bytes:
    from pathlib import Path
    return (Path(__file__).parent / "fixtures" / name).read_bytes()


@pytest.fixture
def short_raw() -> bytes:
    """松山湖→广州塔 驾车,3 方案(2026-10-21 抓包)。"""
    return _fixture("nav_auto_short.gz")


@pytest.fixture
def long_raw() -> bytes:
    """广州→北京西站 驾车,2 方案(2026-10-21 抓包)。"""
    return _fixture("nav_auto_long.gz")


@pytest.fixture
def bus_raw() -> bytes:
    """松山湖→广州塔 公交,7 推荐方案(2026-10-21 抓包)。"""
    return _fixture("bus_integrate.gz")


def _json_fixture(name: str) -> dict:
    import json  # pylint: disable=import-outside-toplevel
    data: dict = json.loads(_fixture(name).decode("utf-8"))
    return data


@pytest.fixture
def web_drive() -> dict:
    """Web v3 驾车 松山湖→广州塔(2026-10-21,速度最快 87km)。"""
    return _json_fixture("web_drive.json")


@pytest.fixture
def web_transit() -> dict:
    """Web v3 公交 松山湖→广州塔,2 方案(2026-10-21)。"""
    return _json_fixture("web_transit.json")


@pytest.fixture
def web_walk() -> dict:
    """Web v3 步行 松山湖→松山湖北,2068m(2026-10-21)。"""
    return _json_fixture("web_walk.json")


@pytest.fixture
def web_geo() -> dict:
    """Web v3 地理编码 广州塔(2026-10-21)。"""
    return _json_fixture("web_geo.json")
