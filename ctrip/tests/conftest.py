"""测试公共夹具:真实抓包响应。"""
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def search_resp():
    """真实响应:SZX→HAK 2026-10-27,17 班。"""
    return load_fixture("search.json")


@pytest.fixture
def calendar_resp():
    """真实响应:低价日历 377 天。"""
    return load_fixture("calendar.json")


@pytest.fixture
def fuzzy_resp():
    """真实响应:airportFuzzySearch(丽江 cityId=37)。"""
    return load_fixture("fuzzy.json")
