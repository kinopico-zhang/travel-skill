# airchina

国航 H5（m.airchina.com.cn）查询接口的 Python 客户端。

## CLI 用法

```bash
# 里程奖励客票（需登录会话）
python -m airchina award ORG DST DATE [--return-date 日期] [--cabin X|0] \
        [--adults N] [--children N] [--flag D|I] [--check-token TOK]
# 现金票低价日历（无需登录）
python -m airchina calendar ORG DST DATE
# 里程/账户概要（需登录会话）
python -m airchina account
# 从 mitmproxy 抓包提取/保存会话
python -m airchina session [--from-flows 文件] [--save 文件]
# 会话保活守护（默认每 15 分钟轻量 ping 续期）
python -m airchina keepalive [--interval 900] [--backoff 1800] [--once] \
        [--deep] [--heartbeat 文件]
```

| 子命令 | 参数说明 |
|---|---|
| `award` | `ORG`/`DST` 三字码，`DATE` 为 `YYYY-MM-DD`；`--return-date` 给即查往返（一次调用自动查双向）；`--cabin X` 经济舱奖励票（默认）/`0` 不限；`--adults`/`--children` 人数（默认 1/0）；`--flag D` 国内（默认）/`I` 国际；`--check-token` 过滑块后的 token（一般不需要） |
| `calendar` | 位置参数同 `award`；无需登录 |
| `session` | `--from-flows` 抓包文件（默认 `/tmp/airchina.flows`）；`--save` 会话输出（默认 `~/.airchina/session.json`） |
| `keepalive` | `--interval` 间隔秒（默认 900，须小于约 25 分钟闲置超时）；`--backoff` 瞬时错误退避秒（默认 1800）；`--once` 只 ping 一次；`--deep` 账户接口深检（能看里程，端点较敏感）；`--heartbeat` 心跳文件（默认 `~/.airchina/keepalive.json`） |

```bash
python -m airchina award CAN PEK 2026-10-21
python -m airchina award CAN PEK 2026-10-21 --return-date 2026-10-24   # 往返
python -m airchina calendar CAN PEK 2026-10-21                          # 免登录
python -m airchina keepalive --once --deep
```

## Python 用法

```python
from airchina import AirChinaClient

ac = AirChinaClient.load()                        # 读 ~/.airchina/session.json
r = ac.award_search("CAN", "PEK", "2026-10-21")   # 里程奖励客票
for f in r.flights:
    print(f.flight_no, f.dep_time, f.arr_time, f.mileage_price, f.seats,
          [c for c in f.cabins if c.bookable])

cal = ac.low_price_calendar("CAN", "PEK", "2026-10-21")   # 现金低价日历（无需登录）
for d in cal:                    # List[DailyPrice]，按日期升序
    print(d.date, d.price)       # "2026-10-21", 2350（price 已转 int）
```

已安装：`~/.venv/bin/python -m airchina …`（editable，
`uv pip install --python ~/.venv/bin/python -e ~/travel-skill/airchina`）。
依赖 `pydantic>=2`（响应全部解析为模型，不再返回裸 dict）；`Session.from_flows` 需要
mitmproxy（`[flows]` extra）。测试 42 个（`pytest -q`），mypy/pylint 全绿。

## 接口状态

| 接口 | 端点 | 状态 |
|---|---|---|
| 奖励客票查询 | `/ac/f/invoke.json` a=12 p=47 | ✅ 单程/往返 |
| 现金低价日历 | `/g/invoke.json` a=0 p=0 | ✅ **无需 Cookie** |
| 里程/账户概要 | `/ac/g/invoke.json` a=8 p=34 | ❌ 服务端拒绝（01010012），req 结构未逆向出来 |

奖励客票字段：`AwardFlight.flight_no/dep_time/arr_time/aircraft/mileage_price/seats/cabins`，
`AwardCabin.bookable`（pprice/fprice>0 启发式）、`classCode`（O 头等/I 公务/X 经济）。
`AwardResult.availability` 是响应里的 lowPriceList（往返可选回程日期）。

往返（`--return-date`）：**一次调用自动查双向**——RT 模式响应只含去程，回程是反向再查一次
（中间隔 1.5s 模拟翻页）。注意 RT 模式下去程显示的是往返合计价（如 CAN-PEK 经济 26000），
回程那条显示单程价（15000）。

## 会话（Cookie）

- 必须**同时**带 `SESSION` + `JSESSIONID`（只带 SESSION 会返回登录 HTML）。
- **服务端会话约 25 分钟空闲过期**（实测）；两个 Cookie 都是会话级，浏览器进程退出即没。
- `CookieExpiredError` → 需要重登（见下）。`WafBlockedError` → 换 python HTTP 栈
  （curl 的 TLS 指纹会被网宿 WAF 302 到 /500.html），等几分钟再试。

### 重登流程（全自动脚本，人在外地也能做）

```
# 1. 触发短信（自动解滑块）
~/.venv/bin/python ~/travel-skill/airchina/scripts/login_flow.py new
# 2. 用户把收到的验证码发来后：
~/.venv/bin/python ~/travel-skill/airchina/scripts/submit_code.py <验证码>
# 3. 从抓包刷新会话文件
~/.venv/bin/python -m airchina session --from-flows /tmp/airchina.flows
```

前提：MuMu 模拟器浏览器开着 m.airchina.com.cn、mitmproxy 在 8080 抓包、
`adb forward tcp:9222 localabstract:webview_devtools_remote_<pid>`。
浏览器渲染器卡死（页面永远 loading）时 `am force-stop com.android.browser` 重启即可。

### 保活（已部署 systemd 服务）

服务端会话是**滑动过期**（闲置约 25 分钟死，任何带 cookie 的请求即续期）——
2026-10-20 实测：登录后靠连续查询活了 2 小时以上。据此部署了守护：

```bash
systemctl --user status airchina-keepalive    # 看状态
journalctl --user -u airchina-keepalive -f    # 看日志（每 15 分钟一条 OK）
cat ~/.airchina/keepalive.json                # 心跳（最近一次 ping 结果）
python -m airchina keepalive --once           # 手动 ping 一次
python -m airchina keepalive --once --deep    # 深检（账户接口，顺带看里程）
```

- 默认 ping = 现金低价日历（查询类端点，稳定；账户端点 a=8 会偶报「网络非常繁忙」）。
- interval 900s（须小于 25 分钟），带 ±10% 抖动。
- 会话真死时进程退出、服务进 failed 状态（不自动重启轰炸）；重登更新
  `~/.airchina/session.json` 后最多 30 分钟自动恢复（RestartSec=1800）。
- WSL 开机自启（systemd user 单元 + linger 已开）。

## 风控注意

- 查询频率保持人类节奏（脚本里已内置 1.5s 间隔）；别高频连续调用。
- 服务端可能回 `risky: true` 要求滑块（`CaptchaRequiredError`），此时需浏览器过码拿
  checkToken 再重试（一般查询不会触发）。
