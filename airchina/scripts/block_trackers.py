"""mitmproxy 插件:拦掉在国内挂起、拖死国航 H5 页面加载的跟踪域。"""
from mitmproxy import http

BLOCK_HOSTS = (
    "googletagmanager.com",
    "google-analytics.com",
    "googletagmanager.com",
    "googleadservices.com",
    "doubleclick.net",
    "google.cn",
    "googleapis.com",
    "gstatic.com",
)


def request(flow):
    h = flow.request.pretty_host
    if any(h == b or h.endswith("." + b) for b in BLOCK_HOSTS):
        flow.response = http.Response.make(204, b"", {"Content-Type": "text/plain"})
