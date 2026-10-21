"""测试公共夹具:真实抓包响应 + 会话样本。"""
import json
from pathlib import Path

import pytest

from airchina.session import Identity, Session

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def award_ow():
    """真实响应:CAN→HAK 2026-10-27,2 班经济舱可兑。"""
    return load_fixture("award_ow.json")


@pytest.fixture
def calendar_resp():
    """真实响应:现金低价日历(resp.RT)。"""
    return load_fixture("calendar.json")


@pytest.fixture
def account_resp():
    """真实响应:账户端点被服务端拒绝(01010012)。"""
    return load_fixture("account.json")


@pytest.fixture
def sample_session() -> Session:
    return Session(
        cookies="SESSION=abc; JSESSIONID=def",
        identity=Identity(user_id="U1", info_id="I1", crm_member_id="M1",
                          main_vip_card="VC1", mobile="13800000000",
                          tier="Silver", member_no="VC1"),
    )
