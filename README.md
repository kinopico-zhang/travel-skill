# travel-skill

提供给 AI agent 使用的 app H5 API 客户端库。

| 目录 | 说明 |
|---|---|
| `airchina/` | 国航 H5(m.airchina.com.cn)API:奖励客票查询(单程/往返)、现金低价日历、会话管理、短信重登驱动 |
| `ctrip/` | 携程 H5 API(CDP 页面代理):航班列表、低价日历、火车票车次查询(免登录)、城市码解析 |

## 快速开始

```bash
uv venv && uv pip install -e ./airchina -e ./ctrip   # 依赖 pydantic>=2
python -m airchina calendar CAN PEK 2026-11-01       # 现金日历(无需登录)
```

需要登录态/模拟器环境的接口,前提与风控节奏见各子目录 README。

## 工具链

pytest 74 tests / mypy 0 errors / pylint 10.00
(airchina 42 + ctrip 32;真实抓包夹具驱动,传输层 mock,不触网)。

## 注意

- 本仓库仅用于本人账户的查询自动化;库内置请求节流,请保持人类节奏调用。
- 敏感信息(手机号/会话/身份标识)存于仓库外的 `~/.airchina/`、`~/.ctrip/`,
  登录脚本从 `~/.airchina/profile.json`、`~/.ctrip/profile.json` 读取手机号。
