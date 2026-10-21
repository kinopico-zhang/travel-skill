"""测试公共夹具:真实抓包响应。"""
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def listing_resp():
    """真实响应:单程列表页,7 个卡片共 31 个行程(10 直飞 + 21 中转)。"""
    return load_fixture("listing.json")
