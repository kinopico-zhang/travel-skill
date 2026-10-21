"""国航 H5 API 客户端库的错误类型。"""
from typing import Optional


class AirChinaError(Exception):
    """库内所有异常的基类。"""


class CookieExpiredError(AirChinaError):
    """Cookie 失效(服务端回了登录 HTML 页)。

    SESSION/JSESSIONID 是会话级 Cookie,浏览器进程退出即失效。
    需要重新走浏览器登录(login_flow.py),再用 airchina session 更新。
    """


class WafBlockedError(AirChinaError):
    """请求被网宿 WAF 拦截(302 → /500.html)。

    本库用 python urllib(已知可过 WAF 的 TLS 指纹);若仍被拦,
    通常是短时间内请求过多,等几分钟再试。
    """


class CaptchaRequiredError(AirChinaError):
    """服务端要求滑块验证(resp.risky == true)。

    独立 HTTP 调用通常不触发;一旦触发需要浏览器上下文过码,
    拿到 checkToken 后可通过 award_search(check_token=...) 传入。
    """


class ApiError(AirChinaError):
    """服务端返回的业务错误(resp.code 非 00000000 且非"无航班"类)。"""

    def __init__(self, code: Optional[str], msg: Optional[str]):
        self.code = code or ""
        self.msg = msg or ""
        super().__init__(f"[{self.code}] {self.msg}")
