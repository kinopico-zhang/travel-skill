# fliggy — 飞猪机票查询 python 库(纯 HTTP 直连 mtop H5 网关,零模拟器)

v0.1.0:单程航班列表(直飞 + 中转),免登录、零模拟器、零浏览器。

## 为什么直连能过

`h5api.m.taobao.com` 是淘宝系 H5 的公共 mtop 网关,h5.m.taobao.com
机票页的 JS 用的就是它:

- **签名是三段式 MD5**:`md5(token & t & appKey & data)`,无 TLS 指纹墙、
  无 JSVMP —— 标准库 `hashlib.md5` 直接算
- **token 匿名自取**:cookie `_m_h5_tk` 前半段;首次空 token 请求会被
  `FAIL_SYS_TOKEN_EMPTY` 拒绝但同时 Set-Cookie 下发新 token,重签重试
  即自愈(CookieJar + opener 自动管理,库内闭环)
- **必须带** iPhone Safari UA + `Referer: https://h5.m.taobao.com/trip/flight/search/index.html`,
  否则触发 `RGV587_ERROR`(无线保镖拦截)

价格单位是分,模型层统一换算成元;`Flight.price` 为**成人含税总价**。

## 用法

```python
from fliggy import FliggyClient

fg = FliggyClient()                    # 默认 min_interval=12s(5 req/min)
r = fg.search("CAN", "PEK", "2026-11-18")
print(r.summary())                     # 31+ 班,直飞/中转混排按价升序
print(r.summary(direct_only=True))     # 只看直飞

for f in r.cheapest_n(5):
    print(f.flight_no, f.dep_time, f.arr_time, f.price)   # price=含税总价
    for seg in f.segments:             # 中转=2 个航段
        print("   ", seg)              # 航班号/机场/航站楼/时刻/机型
# f.fare.price 票面 / f.fare.tax 税 / f.fare.total 总价(元)
```

```bash
python -m fliggy flights CAN PEK 2026-11-18            # 单程列表
python -m fliggy flights CAN PEK 2026-11-18 --direct   # 只看直飞
```

dep/arr 用三字码(机场码即可,如 CAN/PEK);date 为 YYYY-MM-DD。

## 风控要点

- 库默认 `min_interval=12s`(一次查询一个请求),批量扫描请再加长,
  节奏贴近真人
- 触发 `RGV587_ERROR` 时抛 `RateLimitedError`,冷却后再试
- 国际票该接口需要登录态,本库只覆盖国内单程

## 已知限制

- 只封装单程(`tripType=1`);往返参数未验证
- 一个行程卡片只有一档成人报价(经济舱),无多舱位列表

测试 21 个(`pytest -q`,真实抓包夹具驱动、传输层 mock 不触网),
mypy / pylint 全绿。
