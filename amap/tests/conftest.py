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
