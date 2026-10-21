"""会话与身份持久化(pydantic 模型)。

登录态 = Cookie(SESSION + JSESSIONID,会话级,浏览器进程退出即失效)
+ 身份标识(userId/infoID/crmMemberId/知音卡号,登录后固定不变)。

默认会话文件 ~/.airchina/session.json;也可直接从 mitmproxy 抓包文件
(模拟器流量)提取最新会话 —— 这正是抓包工作流的自然出口。

会话文件的 JSON 形状与旧版(dataclass 时代)保持兼容:
{"cookies": "...", "identity": {...}, "created_at": 123.0}
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator

from .errors import AirChinaError

DEFAULT_SESSION_FILE = os.path.expanduser("~/.airchina/session.json")
DEFAULT_FLOWS = "/tmp/airchina.flows"


class Identity(BaseModel):
    """登录身份标识(从抓包提取,登录后固定)。"""

    user_id: str = ""         # 32位HEX
    info_id: str = ""         # 32位HEX
    crm_member_id: str = ""   # mId,形如 1-XXXXXXX(日历等 g 模块接口)
    main_vip_card: str = ""   # 知音卡号,奖励票查询必填
    mobile: str = ""
    tier: str = ""            # Silver / 白金卡 ...
    member_no: str = ""       # 知音号(同 main_vip_card)

    @field_validator("*", mode="before")
    @classmethod
    def _none_to_empty(cls, v: Any) -> Any:
        """旧会话文件里可能出现 null,统一落成空串。"""
        return "" if v is None else v


class Session(BaseModel):
    """一次登录的完整会话。"""

    cookies: str              # 原始 Cookie 头,整串保存
    identity: Identity = Field(default_factory=Identity)
    created_at: float = Field(default_factory=time.time)

    @property
    def cookie_dict(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for part in self.cookies.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                out[k] = v
        return out

    def save(self, path: str = DEFAULT_SESSION_FILE) -> None:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(), f, ensure_ascii=False, indent=1)

    @classmethod
    def load(cls, path: str = DEFAULT_SESSION_FILE) -> "Session":
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return cls.model_validate(d)

    @classmethod
    def from_flows(cls, flows_path: str = DEFAULT_FLOWS) -> "Session":
        """从 mitmproxy 抓包文件提取最新登录会话。

        Cookie 取 m.airchina.com.cn 最近一条带 Cookie 头的请求;
        身份取最近一条 invoke.json 请求的 m 信封(userID/infoID/crmMemberId,
        奖励票请求的 req 里还有 mainVipCard),并以页面内联的账户 JSON
        (phone/primaryTierName/ziYinNo)补齐可选字段。
        """
        try:
            # 可选依赖,延迟导入:没有 mitmproxy 的环境仍可用查询功能
            from mitmproxy import http as mhttp  # pylint: disable=import-outside-toplevel
            from mitmproxy import io as mio  # pylint: disable=import-outside-toplevel
        except ImportError as e:
            raise AirChinaError(
                "from_flows 需要 mitmproxy(pip install mitmproxy)") from e
        cookies: Optional[str] = None
        ident: Dict[str, str] = {}
        vip = ""
        extra: Dict[str, str] = {}
        with open(flows_path, "rb") as f:
            flows = [x for x in mio.FlowReader(f).stream()
                     if isinstance(x, mhttp.HTTPFlow)]
        for fw in reversed(flows):
            req = fw.request
            if not (req.host or "").endswith("m.airchina.com.cn"):
                continue
            if cookies is None:
                c = req.headers.get("Cookie")
                if c:
                    cookies = c
            if "invoke.json" in (req.path or "") and not ident:
                try:
                    b = json.loads(req.get_text() or "")
                    m = b.get("m") or {}
                    if m.get("userID"):
                        ident = {"user_id": m["userID"],
                                 "info_id": m.get("infoID") or "",
                                 "crm_member_id": m.get("crmMemberId") or ""}
                        try:
                            vip = json.loads(m.get("req") or "{}").get("mainVipCard") or ""
                        # 抓包内容不可信,提取失败就跳过该条流
                        except Exception:  # pylint: disable=broad-exception-caught
                            pass
                except Exception:  # pylint: disable=broad-exception-caught
                    pass
            if not extra and req.method == "GET" and fw.response:
                try:
                    body = fw.response.get_text() or ""
                except Exception:  # pylint: disable=broad-exception-caught
                    body = ""
                if '"ziYinNo"' in body:
                    for key, field_name in (("phone", "mobile"),
                                            ("primaryTierName", "tier"),
                                            ("ziYinNo", "member_no")):
                        mm = re.search(rf'"{key}"\s*:\s*"([^"]+)"', body)
                        if mm:
                            extra[field_name] = mm.group(1)
        if not cookies:
            raise AirChinaError(f"{flows_path} 里找不到 m.airchina.com.cn 的 Cookie,"
                                " 先在模拟器浏览器里登录一次")
        if not ident:
            raise AirChinaError(f"{flows_path} 里找不到含 userID 的 invoke.json 请求")
        identity = Identity(
            main_vip_card=vip or extra.get("member_no") or "",
            mobile=extra.get("mobile", ""),
            tier=extra.get("tier", ""),
            member_no=extra.get("member_no") or vip,
            **ident)
        return cls(cookies=cookies, identity=identity)
