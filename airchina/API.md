# airchina API 文档

> 国航 H5（m.airchina.com.cn）查询接口的 Python 客户端：里程奖励客票查询、现金票低价日历、里程/账户概要；登录在浏览器做一次、会话从 mitmproxy 抓包导入，日常查询零模拟器。版本 0.2.0。

## 模块总览

| 模块 | 职责 |
|---|---|
| `airchina/__init__.py` | 包出口：客户端、会话、模型、异常与默认路径常量，`__version__` |
| `airchina/client.py` | `AirChinaClient`：urllib 直连传输层 + 奖励客票、低价日历、账户三个接口 + 保活探测 |
| `airchina/session.py` | `Identity` / `Session`：登录身份与 Cookie 的持久化、从 mitmproxy 抓包提取会话 |
| `airchina/models.py` | 响应数据模型（pydantic）：奖励票、低价日历、账户概要 |
| `airchina/errors.py` | 异常体系：`AirChinaError` 基类 + 四个子类 |
| `airchina/__main__.py` | CLI（`python -m airchina`）、keepalive 守护循环、`Heartbeat` 心跳模型 |

## 前置条件与依赖

- Python ≥ 3.9；唯一运行依赖 `pydantic>=2`。传输只用标准库 `urllib`，不需要 requests/curl。
- 本机安装（editable）：`uv pip install --python ~/.venv/bin/python -e ~/travel-skill/airchina`。
- `Session.from_flows` 需要 mitmproxy（可选依赖，`pip install "airchina[flows]"`）；延迟导入，未安装时查询功能不受影响，只在提取会话时抛 `AirChinaError`。
- 登录：短信 + 滑块在模拟器浏览器里做一次（重登流程见 README），会话从抓包文件导入；之后查询不需要模拟器。
- 会话 Cookie 必须同时带 `SESSION` + `JSESSIONID`（只带 SESSION 会返回登录 HTML）；服务端会话约 25 分钟**滑动过期**，任何带 Cookie 的请求都会续期。
- 必须用 python 的 HTTP 栈直连：curl 的 TLS 指纹会被网宿 WAF 302 到 `/500.html`（抛 `WafBlockedError`）。
- 敏感文件均在仓库外：会话文件 `~/.airchina/session.json`（含 Cookie、手机号等身份信息）、心跳文件 `~/.airchina/keepalive.json`、抓包文件 `/tmp/airchina.flows`（含全量流量）。均不得入库或外传。

## 快速上手

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

## 客户端

### `AirChinaClient`

三个查询接口加一个保活探测，全部走同一传输层：请求打成 JSON POST（`m` 信封 + `a`/`p` 接口号），响应里的原始 dict 只停留在传输边界，进业务层即解析为 `models` 里的 pydantic 类型。所有方法同步阻塞。

类常量：

| 常量 | 值 |
|---|---|
| `BASE` | `https://m.airchina.com.cn` |
| `AWARD_URL` | `BASE + "/ac/f/invoke.json"`（a=12 p=47，奖励客票） |
| `CALENDAR_URL` | `BASE + "/g/invoke.json"`（a=0 p=0，低价日历，现金） |
| `ACCOUNT_URL` | `BASE + "/ac/g/invoke.json"`（a=8 p=34，里程/账户） |
| `AWARD_REFERER` | `BASE + "/ac/c/invoke/awardTickets/showAwardTicketsFlights@pg?from=booking"` |

构造签名：

```python
AirChinaClient(session: Session, timeout: int = 30)
```

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `session` | `Session` | 必填 | 会话（Cookie + 身份），见「会话管理」 |
| `timeout` | `int` | `30` | 每次 HTTP 请求的超时秒数（透传给 `urlopen`） |

两个构造类方法：

```python
@classmethod
def load(cls, path: str = DEFAULT_SESSION_FILE,
         **kw: Any) -> "AirChinaClient":
```

```python
@classmethod
def from_flows(cls, flows_path: str = DEFAULT_FLOWS,
               save_to: Optional[str] = DEFAULT_SESSION_FILE,
               **kw: Any) -> "AirChinaClient":
```

| 方法 | 说明 |
|---|---|
| `load` | 从会话文件构造（默认 `~/.airchina/session.json`）；`path` 换路径，`**kw` 透传给构造器（如 `timeout=10`）；文件不存在抛 `FileNotFoundError` |
| `from_flows` | 从 mitmproxy 抓包提取会话并构造；`save_to` 非 `None` 时顺带保存到该路径（默认即会话文件，传 `None` 跳过保存）；需要 mitmproxy |

#### `award_search`

里程奖励客票查询（a=12 p=47）。完整签名（与源码逐字一致）：

```python
def award_search(self, org: str, dst: str, date: str, *,
                 return_date: Optional[str] = None,
                 cabin: str = "X", adults: int = 1, children: int = 0,
                 flag: str = "D", check_token: str = "",
                 carrier: str = "CA") -> AwardResult:
```

参数表（`*` 之后均为关键字参数）：

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `org` | `str` | 必填 | 出发机场三字码（如 `CAN`） |
| `dst` | `str` | 必填 | 到达机场三字码 |
| `date` | `str` | 必填 | 去程日期 `YYYY-MM-DD` |
| `return_date` | `Optional[str]` | `None` | 回程日期；传入即查往返 |
| `cabin` | `str` | `"X"` | `"X"` 经济舱奖励票；`"0"` 不限 |
| `adults` | `int` | `1` | 成人人数 |
| `children` | `int` | `0` | 儿童人数 |
| `flag` | `str` | `"D"` | `"D"` 国内；`"I"` 国际 |
| `check_token` | `str` | `""` | 浏览器过滑块后拿到的 checkToken（一般不需要） |
| `carrier` | `str` | `"CA"` | 承运航司二字码：`"CA"` 国航 / `"ZH"` 深航 / `"SC"` 山航；星盟成员（NH/UA/LH/OZ/SQ/TG…）国际线可用；空串行为未验证 |

返回值：`AwardResult`（结构见「数据模型」）。无可兑换航班时**返回空结果**（`bool(r)` 为 `False`），`r.message` 带服务端提示，不算错误。

异常：

- `ApiError`：去程结果为空且业务 code 非成功（`00000000`）且 message 不含「没有可兑换」；或回程结果非空且满足同样条件。
- `CookieExpiredError` / `WafBlockedError` / `CaptchaRequiredError` / `AirChinaError`：传输层，见「异常体系」。

示例：

```python
r = ac.award_search("CAN", "PEK", "2026-10-21")                            # 单程
r = ac.award_search("CAN", "PEK", "2026-10-21", return_date="2026-10-24")  # 往返
r = ac.award_search("NRT", "PEK", "2026-11-05", flag="I", carrier="NH")    # 国际/星盟
```

备注：

- 往返是两次请求：RT 模式响应只含去程（服务端无 returnFlightInfos），库隔 1.5 秒后反向再查一次回程（模拟 H5 翻页节奏，勿高频）。
- RT 模式下去程的 `mileage_price` 是**往返合计价**，回程那条是**单程价**（实测口径：CAN-PEK 经济去程显示 26000，回程显示 15000）。
- 触发滑块时（`CaptchaRequiredError`）需浏览器过码拿 checkToken 后经 `check_token=…` 重试。
- **假空**：偶发返回空列表但服务端无错，隔几秒重查即恢复——对空结果做一次重试验证，不要把假空当成无票。

#### `low_price_calendar`

现金票低价日历（a=0 p=0）。完整签名：

```python
def low_price_calendar(self, org: str, dst: str,
                       date: str) -> List[DailyPrice]:
```

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `org` | `str` | 必填 | 出发机场三字码 |
| `dst` | `str` | 必填 | 到达机场三字码 |
| `date` | `str` | 必填 | 基准日期 `YYYY-MM-DD`（返回该日期前后的日历） |

返回值：`List[DailyPrice]`，按日期升序；只保留有价格的日期。这是 `/g/` 模块（现金票），返回人民币价格，**不是里程**。

异常：`ApiError`（响应 code 非成功且响应里没有 `RT` 字段时）；传输层异常同上。

示例：

```python
cal = ac.low_price_calendar("CAN", "PEK", "2026-10-21")
for d in cal:
    print(d.date, d.price)
```

备注：该端点**无需 Cookie** 即可用（客户端仍会附带会话头）；`price` 服务端以字符串下发（如 `"1350"`），模型统一转 `int`；日历覆盖的日期范围以服务端返回为准。

#### `mileage_summary`

里程/账户概要（a=8 p=34）。完整签名：

```python
def mileage_summary(self) -> MileageSummary:
```

无参数。

返回值：`MileageSummary`。固定解析 `code`/`msg`，其余字段以服务端为准、随版本可能变化，经 `extra="allow"` 透传（`model_dump()` 取全量）。

异常：`ApiError`（响应 code 非成功）；传输层异常同上。

示例：

```python
m = ac.mileage_summary()
print(m.code, m.msg)
print(m.model_dump())        # 其余字段随服务端版本
```

备注（现状）：该端点 req 结构未完全逆向，真实环境下服务端多直接拒绝（`01010012` 网络非常繁忙 → `ApiError`，测试夹具即真实被拒响应），接口保留备用；端点较敏感，低频使用。

#### `keepalive_ping`

会话保活探测。完整签名：

```python
def keepalive_ping(
        self, deep: bool = False) -> Union[List[DailyPrice], MileageSummary]:
```

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `deep` | `bool` | `False` | `False` 用现金低价日历做轻量 ping（查询类端点，全天稳定）；`True` 改查账户概要——能顺带校验里程，但该端点偶报 `01010012`，只适合低频深检 |

返回值：`deep=False` → `List[DailyPrice]`（固定查 `CAN` → `PEK`，日期取「今天 + 7 天」）；`deep=True` → `MileageSummary`。

异常：透传所调接口的异常。Cookie 失效时（响应变登录 HTML）抛 `CookieExpiredError`——这正是守护进程判断「会话已死」的信号。

示例：

```python
ac.keepalive_ping()               # 轻量 ping，续期滑动会话
ac.keepalive_ping(deep=True)      # 深检，顺带看里程
```

备注：服务端会话是滑动过期（闲置约 25 分钟），任何带 Cookie 的请求都会续期；守护用法见 CLI `keepalive`。

## 会话管理（session.py）

登录态 = Cookie（`SESSION` + `JSESSIONID`，会话级，浏览器进程退出即失效）+ 身份标识（`userId`/`infoID`/`crmMemberId`/知音卡号，登录后固定不变）。

默认路径常量（可从 `airchina` 或 `airchina.session` 导入）：

| 常量 | 值 |
|---|---|
| `DEFAULT_SESSION_FILE` | `~/.airchina/session.json`（源码为 `os.path.expanduser("~/.airchina/session.json")`） |
| `DEFAULT_FLOWS` | `/tmp/airchina.flows` |

会话文件的 JSON 形状与旧版（dataclass 时代）保持兼容：

```json
{"cookies": "...", "identity": {...}, "created_at": 123.0}
```

### `Identity` / `Session` / `Heartbeat`

#### `Identity`

登录身份标识（从抓包提取，登录后固定）。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `user_id` | `str` | `""` | 32 位 HEX |
| `info_id` | `str` | `""` | 32 位 HEX |
| `crm_member_id` | `str` | `""` | mId，形如 `1-XXXXXXX`（日历等 g 模块接口用） |
| `main_vip_card` | `str` | `""` | 知音卡号，奖励票查询必填 |
| `mobile` | `str` | `""` | 手机号 |
| `tier` | `str` | `""` | 会员等级，如 `Silver` / `白金卡` |
| `member_no` | `str` | `""` | 知音号（同 `main_vip_card`） |

所有字段在解析前 `null` 一律落成 `""`（兼容旧会话文件）；未知字段忽略。

#### `Session`

一次登录的完整会话。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `cookies` | `str` | 必填 | 原始 Cookie 头整串（如 `SESSION=…; JSESSIONID=…`） |
| `identity` | `Identity` | 空 `Identity` | 身份标识 |
| `created_at` | `float` | `time.time()` | 创建时刻（Unix 秒） |

属性与方法：

```python
@property
def cookie_dict(self) -> Dict[str, str]:
```

按 `;` 拆分 Cookie 串，取每段第一个 `=` 前后的键值；不含 `=` 的片段忽略。例：`"SESSION=abc; JSESSIONID=def"` → `{"SESSION": "abc", "JSESSIONID": "def"}`。

```python
def save(self, path: str = DEFAULT_SESSION_FILE) -> None:
```

保存为 JSON（`ensure_ascii=False`、`indent=1`）；父目录不存在会自动创建。

```python
@classmethod
def load(cls, path: str = DEFAULT_SESSION_FILE) -> "Session":
```

从 JSON 文件加载（`json.load` + `model_validate`）；未知字段忽略、`null` → `""`，可直接读旧版会话文件。

```python
@classmethod
def from_flows(cls, flows_path: str = DEFAULT_FLOWS) -> "Session":
```

从 mitmproxy 抓包文件提取最新登录会话：

- 需要 mitmproxy（延迟导入）；未安装抛 `AirChinaError`（消息提示 `pip install mitmproxy`）。
- Cookie 取 `m.airchina.com.cn` 域名下**最近一条**带 `Cookie` 头的请求。
- 身份取最近一条 `invoke.json` 请求的 `m` 信封（`userID`/`infoID`/`crmMemberId`），奖励票请求 `req` 里的 `mainVipCard` 一并提取。
- 可选字段从最近一条带 `"ziYinNo"` 的 GET 响应页面内联 JSON 补齐：`phone`→`mobile`、`primaryTierName`→`tier`、`ziYinNo`→`member_no`。
- 找不到 Cookie，或找不到含 `userID` 的 invoke 请求，分别抛 `AirChinaError`。
- 抓包内容不可信：单条流解析失败即跳过该条，不致命。

#### `Heartbeat`（定义在 `__main__.py`）

keepalive 心跳文件（默认 `~/.airchina/keepalive.json`）的内容模型，每次 ping 成功或失败后都覆写一次。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `ok` | `bool` | 必填 | 最近一次 ping 是否成功 |
| `ts` | `float` | 必填 | 时间戳（Unix 秒） |
| `err` | `str` | `""` | 失败原因（成功为空串） |

保活守护用法：`python -m airchina keepalive`（见「CLI 参考」）；滑动过期机制——闲置约 25 分钟会话即死，靠定时 ping 续期。本机已部署 systemd user 单元 `airchina-keepalive`（部署细节见 README）。

## 数据模型（models.py）

响应进业务层即解析为 pydantic 模型；字段类型以真实抓包响应为准。模型均可 `model_dump()` / `model_dump_json()` 序列化往返（测试覆盖）。

### `AwardCabin` / `AwardFlight` / `AwardResult` / `DayAward` / `DailyPrice` / `MileageSummary`

#### `AwardCabin`

奖励票舱位。

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | `str`，默认 `""` | 舱位代码：`I` 公务 / `X` 经济 / `O` 头等 |
| `service` | `str`，默认 `""` | 服务等级英文：`business` / `economy` / `first` |
| `service_desc` | `str`，默认 `""` | 中文描述：公务舱 / 经济舱 / 头等舱 |
| `pprice` | `Optional[float]` | 兑换价字段；`>0` 视为该舱可兑（仅对公务舱 `I` 可靠） |
| `fprice` | `Optional[float]` | 同上，备用价字段 |
| `seat_num` | `str`，默认 `""` | 该舱剩余座位 |
| `hand_baggage` | `str`，默认 `""` | 手提行李（如 `5KG`） |
| `child_baggage` | `str`，默认 `""` | 免费托运行李 |

辅助成员：

```python
@property
def bookable(self) -> bool:
```

等价于 `(pprice or 0) > 0 or (fprice or 0) > 0`。启发式：真实数据里 `X` 行 `pprice` 常为 `-1`（不可据此判兑），`pprice>0` 只在公务舱 `I` 行可靠；精确可用性看航班级 `mileage_price` + `seats`。

```python
@classmethod
def parse(cls, c: Dict[str, Any]) -> "AwardCabin":
```

从服务端原始字段解析：`classCode`→`code`、`classOfService`→`service`、`classDescOfService`→`service_desc`、`pprice`/`fprice`（空值转 `None`）、`seatNum`→`seat_num`、`handBaggage`→`hand_baggage`、`childBaggage`→`child_baggage`。

`__str__` 语义：`code(中文舱位或英文 service[,可兑])`，如 `X(经济舱,可兑)`；不可兑时无「,可兑」后缀。

#### `AwardFlight`

一个可兑换航班。

| 字段 | 类型 | 说明 |
|---|---|---|
| `flight_no` | `str` | 航班号，如 `CA1322` / `ZH9325`（公司二字码 + 序号拼接） |
| `org` | `str` | 出发机场三字码 |
| `dst` | `str` | 到达机场三字码 |
| `dep_date` | `str` | 起飞日期 `YYYY-MM-DD` |
| `dep_time` | `str` | 起飞时间，如 `13:40` |
| `arr_date` | `str` | 到达日期 |
| `arr_time` | `str` | 到达时间，如 `16:55` |
| `dep_term` | `str` | 出发航站楼，如 `T3` |
| `arr_term` | `str` | 到达航站楼 |
| `aircraft` | `str` | 机型，如 `空客350` |
| `duration` | `str` | 飞行时长描述，如 `3小时15分钟` |
| `mileage_price` | `Optional[int]` | 最低兑换里程（如 `15000`）；服务端以字符串/浮点下发，统一转 `int`，空值转 `None` |
| `seats` | `str` | 剩余奖励票座位数（字符串） |
| `cabins` | `List[AwardCabin]` | 舱位明细，默认空列表 |
| `flight_id` | `str`，默认 `""` | 服务端航班 id |

```python
@classmethod
def parse(cls, f: Dict[str, Any]) -> "AwardFlight":
```

`parse` 的字段映射：`flightCompanyNameCode + flightNo`→`flight_no`、`orgStr`/`dstStr`→`org`/`dst`、`depDate`（缺则 `departure.date`）→`dep_date`、`departure.time`（缺则 `depTime`）→`dep_time`、`arriDate`（缺则 `arrival.date`）→`arr_date`、`arrival.time`（缺则 `arriTime`）→`arr_time`、`depTerm`/`arriTerm`→`dep_term`/`arr_term`、`airCraft`→`aircraft`、`flightTimeDesc`→`duration`、`minCombinedPrice`→`mileage_price`、`seatNum`→`seats`、`cabins`→`cabins`、`id`→`flight_id`。

`__str__` 语义（CLI 逐行输出用）：`航班号 起飞时间->到达时间 出发航站楼->到达航站楼 机型 里程列 余座位 [舱位列表]`；里程列非 `None` 时为 `N里程`（如 `5600里程`），为 `None` 时显示 `?`；无舱位时舱位列表显示 `-`。

#### `AwardResult`

`award_search` 的结果。

| 字段 | 类型 | 说明 |
|---|---|---|
| `flights` | `List[AwardFlight]` | 去程航班，默认空列表 |
| `return_flights` | `List[AwardFlight]` | 回程航班（仅往返查询由库反向补查后填充），默认空列表 |
| `code` | `str`，默认 `""` | 服务端业务码原样保留（`00000000` 为成功） |
| `message` | `str`，默认 `""` | 服务端提示，无可兑时形如「抱歉，暂时没有可兑换航班啦。」 |
| `availability` | `List[DayAward]` | 响应里的 `lowPriceList`：往返可选回程日期 |

```python
@classmethod
def parse(cls, data: Dict[str, Any]) -> "AwardResult":
```

从原始响应解析：`resp.departureFlightInfos`→`flights`、`resp.returnFlightInfos`→`return_flights`、`resp.code`/`resp.msg`→`code`/`message`、`resp.lowPriceList`→`availability`（无 `date` 的条目跳过）。

- `__bool__`：`bool(flights or return_flights)`——任一方向有航班即为真。
- `__len__`：`len(flights)`——只数去程。

#### `DayAward`

`lowPriceList` 的一项：候选日期 + `hasTicket` 标记。

| 字段 | 类型 | 说明 |
|---|---|---|
| `date` | `str` | 候选日期 `YYYY-MM-DD` |
| `has_ticket` | `str`，默认 `""` | 服务端标记（`0`/`4`/`6`…，统一转成字符串） |

重要口径：`hasTicket` 的值经实测**与真实可兑性对不上**，仅供展示；判断可用性必须实查 `award_search`。

#### `DailyPrice`

低价日历的一个日期：最低现金票价（人民币）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `date` | `str` | 日期 `YYYY-MM-DD` |
| `price` | `int` | 最低现金价（元）；服务端以字符串下发（如 `"1350"`），模型统一转 `int` |

`low_price_calendar` 返回的就是它：按日期升序，且只含有价格的日期。

#### `MileageSummary`

里程/账户概要（a=8 p=34）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | `str`，默认 `""` | 业务码 |
| `msg` | `str`，默认 `""` | 提示 |

模型配置 `extra="allow"`：服务端其余字段（如 `mileage`、`tierName`，字段名随服务端版本可能变化）原样透传——可作为属性访问、也出现在 `model_dump()` 里；值保持服务端原样类型（可能是字符串）。

## 异常体系（errors.py）

继承关系：

```
AirChinaError                       # 库内所有异常的基类
├── CookieExpiredError              # Cookie 失效（服务端回了登录 HTML 页）
├── WafBlockedError                 # 被网宿 WAF 拦截（302 → /500.html）
├── CaptchaRequiredError            # 服务端要求滑块验证（resp.risky == true）
└── ApiError                        # 服务端业务错误（resp.code 非 00000000 且非「无航班」类）
```

| 异常 | 触发条件 |
|---|---|
| `AirChinaError` | 基类，也直接用于：HTTP 非 2xx（消息形如 `HTTP 502 Bad Gateway (url)`）、响应不是 JSON、`Session.from_flows` 缺 mitmproxy 或抓包里找不到 Cookie/身份 |
| `CookieExpiredError` | 响应是 HTML（登录页）——会话 Cookie 失效（约 25 分钟闲置过期，或浏览器进程退出）。需重新走浏览器登录后 `python -m airchina session --from-flows` 更新会话 |
| `WafBlockedError` | 请求被网宿 WAF 拦截（最终 URL 302 到 `/500.html`）。本库用 python urllib（已知可过 WAF 的 TLS 指纹）；仍被拦通常是短时间内请求过多，等几分钟再试 |
| `CaptchaRequiredError` | 响应 `risky: true`，要求滑块验证。独立 HTTP 调用通常不触发；一旦触发需浏览器上下文过码拿 `checkToken`，经 `award_search(check_token=…)` 传入重试 |
| `ApiError` | 服务端返回业务错误：code 非 `00000000` 且非「没有可兑换」类。属性 `code`/`msg`（`None` 归一为 `""`），`str(e)` 形如 `[01010012] 网络非常繁忙!` |

注意：「无可兑换航班」**不是异常**——`award_search` 返回空 `AwardResult`。

`ApiError` 构造签名：

```python
ApiError(code: Optional[str], msg: Optional[str])
```

## CLI 参考

`python -m airchina <子命令>`，程序名 `airchina`。除 `session` 外，所有子命令先读会话文件 `~/.airchina/session.json` 构造客户端；文件不存在时向 stderr 输出 `会话文件不存在,先运行: airchina session --from-flows /tmp/airchina.flows` 并退出 2。`AirChinaError` 统一以 `错误: …` 打到 stderr 并退出 1。

退出码：`0` 成功（`award` 无可兑换航班也算成功）；`1` 业务/传输错误；`2` 会话文件不存在。

### `award` —— 里程奖励客票查询

```bash
python -m airchina award ORG DST DATE [--return-date 日期] [--cabin X|0] \
        [--adults N] [--children N] [--flag D|I] [--check-token TOK]
```

| 参数 | 说明 |
|---|---|
| `ORG` / `DST` | 出发/到达三字码（位置参数） |
| `DATE` | 去程日期 `YYYY-MM-DD`（位置参数） |
| `--return-date` | 回程日期，传入即查往返（一次调用自动查双向） |
| `--cabin` | `X` 经济舱奖励票（默认）/ `0` 不限 |
| `--adults` | 成人人数（默认 1） |
| `--children` | 儿童人数（默认 0） |
| `--flag` | `D` 国内（默认）/ `I` 国际 |
| `--check-token` | 过滑块后的 checkToken（通常不需要） |

前置条件：登录会话（`~/.airchina/session.json`）。

输出：`ORG->DST DATE 奖励客票 去程 N 班`（往返追加 ` / 回程 M 班`），每班一行（`AwardFlight.__str__` 格式，回程行前缀 `(回) `）；无可兑换时输出 `ORG->DST DATE:无可兑换航班`（有服务端提示时附在括号里），退出码仍为 0。

```bash
python -m airchina award CAN PEK 2026-10-21
python -m airchina award CAN PEK 2026-10-21 --return-date 2026-10-24   # 往返
```

### `calendar` —— 现金票低价日历

```bash
python -m airchina calendar ORG DST DATE
```

位置参数同 `award`。**无需登录**。

输出：`ORG->DST 现金低价日历(自 DATE 前后):`，每天一行 `  DATE  ¥PRICE`。

```bash
python -m airchina calendar CAN PEK 2026-10-21
```

### `account` —— 里程/账户概要

```bash
python -m airchina account
```

无参数。前置条件：登录会话。

输出：`code`/`msg` 两行，其余透传字段按名称排序逐行打印（标量直接显示，复杂类型显示 `<类型名>`）。现状：端点多被服务端拒绝（`01010012` → `ApiError` → 退出 1）。

### `session` —— 从抓包提取/保存会话

```bash
python -m airchina session [--from-flows 文件] [--save 文件]
```

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--from-flows` | `/tmp/airchina.flows` | mitmproxy 抓包文件 |
| `--save` | `~/.airchina/session.json` | 会话输出路径（传空串跳过保存） |

前置条件：已安装 mitmproxy，抓包文件里有国航登录后的流量。

输出：`cookies:`（前 80 字符）+ 身份 JSON 一行；保存后打印 `saved -> 路径`。

### `keepalive` —— 会话保活守护

```bash
python -m airchina keepalive [--interval 900] [--backoff 1800] [--once] \
        [--deep] [--heartbeat 文件]
```

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--interval` | `900` | ping 间隔秒（须小于约 25 分钟闲置超时） |
| `--backoff` | `1800` | 瞬时错误退避秒 |
| `--once` | 关 | 只 ping 一次即退出 |
| `--deep` | 关 | 用账户接口深检（能看里程，但端点较敏感） |
| `--heartbeat` | `~/.airchina/keepalive.json` | 心跳文件路径（支持 `~` 展开） |

行为：

- 默认每 `--interval` 秒轻量 ping 一次（现金日历端点），间隔带 ±10% 抖动、避免整点节律。
- 成功：打日志（形如 `[YYYY-MM-DD HH:MM:SS] OK(日历) 返回N天票价`；deep 时为 `OK(账户) 里程≈N`，里程是从账户响应里挑第一个介于 1000 与 10**7 之间数值的启发式），并写心跳 `ok=true`。
- `CookieExpiredError`（会话真死）：写心跳 `ok=false`、退出 1——需要人工重登（短信验证码），这是设计行为，不要配置自动重启。
- 其他 `AirChinaError` / `OSError` / `TimeoutError` 视为瞬时错误：写心跳 `ok=false`，非 `--once` 时退避 `--backoff` 秒后继续。
- `--once` 时：成功退出 0，任何失败退出 1。

```bash
python -m airchina keepalive --once
python -m airchina keepalive --once --deep
```
