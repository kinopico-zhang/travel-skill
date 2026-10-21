"""Session/Identity 持久化与 from_flows 提取测试。"""

# pylint: disable=protected-access,redefined-outer-name,unused-argument,import-outside-toplevel
import json

import pytest

from airchina.errors import AirChinaError
from airchina.session import Identity, Session

LEGACY_JSON = {
    "cookies": "SESSION=old; JSESSIONID=old2",
    "identity": {
        "user_id": "U9", "info_id": "I9", "crm_member_id": "M9",
        "main_vip_card": "VC9", "mobile": None, "tier": "Silver",
        "member_no": "VC9", "unknown_field": "应被忽略",
    },
    "created_at": 123.0,
    "unknown_top_level": 42,
}


def test_save_load_roundtrip(sample_session, tmp_path):
    path = str(tmp_path / "session.json")
    sample_session.save(path)
    loaded = Session.load(path)
    assert loaded == sample_session
    # 与旧版 dataclass 时代一致的 JSON 形状
    with open(path, encoding="utf-8") as fh:
        d = json.loads(fh.read())
    assert set(d) == {"cookies", "identity", "created_at"}
    assert d["identity"]["main_vip_card"] == "VC1"


def test_load_legacy_json(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(LEGACY_JSON, ensure_ascii=False))
    s = Session.load(path)
    assert s.cookies == "SESSION=old; JSESSIONID=old2"
    assert s.identity.user_id == "U9"
    assert s.identity.mobile == ""          # null → 空串
    assert s.created_at == 123.0


def test_cookie_dict(sample_session):
    assert sample_session.cookie_dict == {"SESSION": "abc", "JSESSIONID": "def"}


def test_identity_none_to_empty():
    ident = Identity.model_validate({"user_id": None, "info_id": "I"})
    assert ident.user_id == ""
    assert ident.info_id == "I"


def _make_flow(host, method, path, req_body, cookie=None, resp_body=None):
    """造一条可被 FlowWriter 序列化的完整 HTTPFlow(连接对象来自 tflow 工厂)。"""
    from mitmproxy import http as mhttp
    from mitmproxy.test import tflow
    url = f"https://{host}{path}"
    headers = {"Content-Type": "application/json"}  # type: dict[str | bytes, str | bytes]
    if cookie:
        headers["Cookie"] = cookie
    f = tflow.tflow(resp=resp_body is not None)
    f.request = mhttp.Request.make(method, url, req_body, headers)
    if resp_body is not None:
        f.response = mhttp.Response.make(200, resp_body, {})
    return f


def test_from_flows(tmp_path):
    """按时间序写三条流(杂音/页面/invoke),从最新提取会话。"""
    pytest.importorskip("mitmproxy")
    from mitmproxy import io as mio

    invoke_body = json.dumps({
        "m": {"userID": "U9", "infoID": "I9", "crmMemberId": "M9",
              "req": json.dumps({"mainVipCard": "055000000001"})}})
    page_body = ('window.x = {"phone":"13800138000",'
                 '"primaryTierName":"Silver","ziYinNo":"055000000001"};')
    flows = [
        _make_flow("api.example.com", "GET", "/x", "", cookie="OTHER=1"),
        _make_flow("m.airchina.com.cn", "POST", "/ac/f/invoke.json",
                   invoke_body, cookie="SESSION=s1; JSESSIONID=j1"),
        _make_flow("m.airchina.com.cn", "GET", "/c/ucenter", "",
                   cookie="SESSION=s2; JSESSIONID=j2", resp_body=page_body),
    ]
    path = tmp_path / "flows"
    with open(path, "wb") as fh:
        w = mio.FlowWriter(fh)
        for f in flows:
            w.add(f)

    s = Session.from_flows(str(path))
    # cookie 取最新一条(s2),身份取 invoke.json,可选字段从页面补齐
    assert s.cookies == "SESSION=s2; JSESSIONID=j2"
    assert s.identity.user_id == "U9"
    assert s.identity.info_id == "I9"
    assert s.identity.crm_member_id == "M9"
    assert s.identity.main_vip_card == "055000000001"
    assert s.identity.mobile == "13800138000"
    assert s.identity.tier == "Silver"
    assert s.identity.member_no == "055000000001"


def test_from_flows_no_cookie(tmp_path):
    pytest.importorskip("mitmproxy")
    from mitmproxy import io as mio

    flows = [_make_flow("m.airchina.com.cn", "GET", "/x", "")]
    path = tmp_path / "flows"
    with open(path, "wb") as fh:
        w = mio.FlowWriter(fh)
        for f in flows:
            w.add(f)
    with pytest.raises(AirChinaError, match="Cookie"):
        Session.from_flows(str(path))
