#!/usr/bin/env python3
"""Deep Link 传输层:让模拟器里的高德 App 替我们发起导航查询。

为什么走 Deep Link:高德请求体是 shield 加密的(阿里 securityguard),
自主构造不现实;amapuri:// URI 让 App 以真实用户身份生成请求,
与真人操作完全同栈,无风控差异。
"""
from __future__ import annotations

import shlex
import subprocess
import time
import urllib.parse
from pathlib import Path
from typing import Optional

from .models import MODES

ADB_DEFAULT = Path.home() / "android-sdk" / "platform-tools" / "adb"
DEVICE = "127.0.0.1:16384"          # MuMu 实例 0
PKG = "com.autonavi.minimap"

AMAP_ON = "amapuri"


class TransportError(Exception):
    """传输层异常的基类。"""


class DeepLinkTransport:
    """通过 adb 向模拟器内的高德发 amapuri:// 路线规划 URI。"""

    def __init__(self, adb: Optional[str] = None, device: str = DEVICE,
                 connect: bool = True):
        self.adb = str(adb or ADB_DEFAULT)
        self.device = device
        if connect:
            self._run("connect", self.device)

    def _run(self, *args: str, timeout: float = 30.0) -> str:
        cmd = [self.adb, *args]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        except FileNotFoundError as e:
            raise TransportError(f"adb 不存在: {self.adb}") from e
        except subprocess.TimeoutExpired as e:
            raise TransportError(f"adb 超时: {' '.join(args[:3])}") from e
        return (r.stdout + r.stderr).strip()

    def _shell(self, cmd: str, timeout: float = 60.0) -> str:
        # 多条命令拼一个 shell 调,减少 adb 往返
        return self._run("-s", self.device, "shell", cmd, timeout=timeout)

    # ---------- 体检 ----------

    def check(self) -> None:
        """链路体检,不通过则抛 TransportError。"""
        if not Path(self.adb).exists():
            raise TransportError(f"adb 不存在: {self.adb}")
        out = self._run("-s", self.device, "get-state")
        if "device" not in out:
            raise TransportError(f"模拟器 {self.device} 不在线: {out}")
        out = self._shell(f"pm list packages | grep -c '{PKG}'")
        if out.strip() != "1":
            raise TransportError(f"高德({PKG})未安装")

    # ---------- 触发 ----------

    def launch_route(self, slat: float, slon: float, dlat: float, dlon: float,
                     sname: str = "", dname: str = "",
                     mode: str = "drive") -> float:
        """发 amapuri://route/plan/,返回发出时刻的 unix 时间戳。

        mode: drive(驾车)/bus(公交)/walk(步行)/bike(骑行)。
        起终点坐标为 GCJ-02(高德坐标系)。
        """
        if mode not in MODES:
            raise TransportError(f"未知出行方式 {mode!r},可选: {sorted(MODES)}")
        q = {"dlat": f"{dlat}", "dlon": f"{dlon}", "dev": "0",
             "t": str(MODES[mode])}
        if sname:
            q["sname"] = sname
        if dname:
            q["dname"] = dname
        if slat and slon:
            q["slat"] = f"{slat}"
            q["slon"] = f"{slon}"
        uri = f"{AMAP_ON}://route/plan/?{urllib.parse.urlencode(q)}"
        # adb shell 会把参数拼接后在设备端 shell 执行,& 必须引号护住
        out = self._shell(
            f"am start -W -a android.intent.action.VIEW "
            f"-d {shlex.quote(uri)} {PKG}", timeout=45)
        if "Complete" not in out and "Error" not in out:
            raise TransportError(f"am start 输出异常: {out[:200]}")
        if "Error" in out:
            raise TransportError(f"am start 失败: {out[:200]}")
        return time.time()
