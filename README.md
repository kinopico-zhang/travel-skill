# travel-skill

提供给 AI agent 使用的 app H5 API 客户端库。

| 目录 | 说明 |
|---|---|
| `airchina/` | 国航 H5（m.airchina.com.cn）API：奖励客票查询（单程/往返）、现金低价日历、会话管理、短信重登驱动 |
| `ctrip/` | 携程 App 网关 API（纯 HTTP 直连）：航班列表、低价日历、火车票车次查询、城市码解析 |
| `amap/` | 高德 H5 服务代理 API（纯 HTTP）：驾车/公交/步行路线、地理编码、未来用车时预估（v4/etd）、App 同款路线偏好策略 |
| `fliggy/` | 飞猪 H5 mtop 网关 API（纯 HTTP 直连）：单程航班列表（直飞+中转），免登录 |

## 依赖矩阵

四个包的默认链路都是**纯 Python 标准库 HTTP**，零模拟器、零浏览器：

| 包 | 模拟器 | 浏览器 | 登录 |
|---|---|---|---|
| `airchina` | 不需要 | 不需要 | 会员功能需要（短信验证码登录，会话保活守护）；现金低价日历免登录 |
| `ctrip` | 国内查询不需要；国际列表需要（14780 指纹无法离线复刻） | 同左 | 不需要（免登录） |
| `amap` | 不需要 | 不需要 | 不需要 |
| `fliggy` | 不需要 | 不需要 | 不需要（国内单程查询；国际票需登录） |

后备通道（非默认，日常不用开）：`ctrip` 国内列表保留 CDP 页面代理链路、
`amap` 保留 Deep Link 页面代理链路（安卓模拟器 + mitmproxy），
两者仅在默认链路失效时兜底。

例外：`ctrip` 的**国际/港澳台航班列表**（`search_intl`，soa2/14780）没有
直连通道 —— 请求 head 指纹（mystery/vid/sessionId）离线复刻必被 WAF 432，
只能走模拟器浏览器 navigate 通道（免登录），详见 `ctrip/README.md`。

## 快速开始

```bash
uv venv && uv pip install -e ./airchina -e ./ctrip -e ./amap -e ./fliggy   # 依赖 pydantic>=2
python -m airchina calendar CAN PEK 2026-11-01       # 现金日历（无需登录）
python -m ctrip train 上海 北京 2026-11-20           # 火车票车次（免登录）
python -m amap route 22.9208 113.8903 起点 23.1066 113.3245 终点
python -m fliggy flights CAN PEK 2026-11-18 --direct # 单程直飞（免登录）
```

## CLI 一览

每个包的全部子命令、参数与示例见各子目录 README 的「CLI 用法」：

| 包 | 子命令 |
|---|---|
| `airchina` | `award` 奖励客票 / `calendar` 低价日历 / `account` 账户概要 / `session` 会话提取 / `keepalive` 保活守护 |
| `ctrip` | `train` 火车票车次 / `intl` 国际·港澳台单程列表 / `cookies` 登录态体检 |
| `amap` | `route` 驾车 / `etd` 未来用时表 / `bus` 公交 / `walk` 步行 / `geo` 地理编码 / `check` 体检 |
| `fliggy` | `flights` 单程航班列表 |

航班列表 / 低价日历（`CtripClient.search` / `low_price_calendar`）、
飞猪列表（`FliggyClient.search`）与未来用车时（`WebClient.etd_table`）
为 Python API，用法见各子目录 README。

需要登录态的接口，前提与风控节奏见各子目录 README。

## 工具链

pytest 151 tests / mypy 0 errors / pylint 10.00
（airchina 42 + ctrip 46 + amap 42 + fliggy 21；真实抓包夹具驱动，传输层 mock，不触网）。

## 注意

- 本仓库仅用于本人账户的查询自动化；库内置请求节流，请保持人类节奏调用。
- 敏感信息（手机号/会话/身份标识）存于仓库外的 `~/.airchina/`、`~/.ctrip/`，
  登录脚本从 `~/.airchina/profile.json`、`~/.ctrip/profile.json` 读取手机号。
