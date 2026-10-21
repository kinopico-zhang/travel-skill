# 国航 H5 (m.airchina.com.cn) API 手册

抓包环境:MuMu 模拟器浏览器 → mitmproxy (192.168.3.196:8080, flows: /tmp/airchina.flows) → 国航。
所有 POST 均为 `Content-Type: application/json; charset=UTF-8`,信封格式:

```
{ "m": { "req": "<JSON字符串>", "token": "h5001", "lang": "zh_CN",
         "userID": ..., "infoID": ..., "userInfo1": "75200",
         "deviceType": "H5", "type": "checkN", ... },
  "a": "<action>", "p": "<param>", "timestamp": <ms> }
```

登录态 = Cookie `SESSION` + `JSESSIONID`(**会话级**,浏览器进程退出即失效)。
身份标识(登录后固定):userId `<32位HEX>`、infoID `<32位HEX>`、
mId/crmMemberId `1-XXXXXXX`、知音卡 ziYinNo/mainVipCard `<12位数字>`。
(真实值属本人账户数据,已从库中移除;登录后自动存于 ~/.airchina/session.json,不入 git。)

## 1. 登录链(短信验证码)

| 步骤 | 请求 | 说明 |
|---|---|---|
| 验证码图 | `POST /airchina/captcha/api/generate` | 返回 {id,type,backgroundImage,templateImage,backgroundImageWidth}; type 随机 SLIDER/ROTATE/CONCAT; **有效期≈60s** |
| 验证码校验 | `POST /airchina/captcha/api/check` | body {id, data:{bgImageWidth:300, trackList:[{x,y,type,t}...]}}; 成功返回 `data` = checkToken UUID |
| 发短信 | `POST /c/invoke.json a=11 p=459` | req {phone, areaCode:"86", businessType:"1"}; **验证码 5 分钟有效** |
| 登录 | `POST /c/loginN a=5 p=9` | req {loginName, password:<RSA>, encryptType:"0", loginType:"5", smsVerifiCode, areaCode, mobileType:"H5", appVer:"6.7.0", mainVersion:"75200"}; 响应 AesMap 加密的账户 JSON → 存 `aj` |

登录页有两套验证码:tianai(滑块,上述 API)与顶象 `_dx.Captcha`(appId 5f6727ec854786a86cd4c3c171d13499,risky 重试时用)。

### tianai 滑块解法
- 小图变体(登录页):bg~320 宽,template 为缺口小图;缺口 = alpha 遮罩暗度扫描,delta = x*(300/bgNaturalWidth)
- 全高模板变体(奖励客票页):bg 600×360,template 110×360(拼图块在模板内 bbox~88×88);块图案与 bg 不匹配,**缺口=bg 上块形状的暗影**;解法 = 块 alpha mask 与 bg 暗度图互相关 → 拖动 (notch_left - piece_left)*显示比例
- 陷阱:弹窗被 CSS transform/overflow:hidden 搞坏 → kill animation/transition、overflow:visible、把 handle 中心拉到 (135,160);**奖励页视口高仅 204px**,handle 必须拉进视口否则鼠标事件落空

## 2. 里程/账户查询(已验证可独立调用)

`POST /ac/g/invoke.json a=8 p=34`,req {} → resp 含当前里程、账户信息。

`a=20 p=251`(req {})→ 通用状态;`a=0 p=0`(低价日历,req {org,dst,date,rtType,...})→ 200 正常。

## 3. ★ 里程奖励客票查询(核心成果)

**`POST https://m.airchina.com.cn/ac/f/invoke.json` `a=12 p=47`** (m.page="awardTicket")

req 字段:
```json
{"queryTripType":"OW",            // OW 单程 / RT 往返
 "orgCity":"CAN","dstCity":"PEK", // 三字码
 "orgCityName":"","dstCityName":"", // 展示用城市名(可空)
 "leaveDate":"2026-10-21","returnDate":"",
 "adultTravelers":"1","childTravelers":"0",
 "cabin":"X",                     // X=经济舱奖励票(锁定经济兑换);0=不限
 "carrierAirline":"CA","airCarrier":"CA","operType":"0",
 "flag":"D",                      // D 国内 / I 国际
 "tabFlag":"0",                   // 0 单程 / 1 往返
 "userId":"...","mId":"",         // mId 传空串
 "mainVipCard":"055000000001"}    // 知音卡号
```
m 信封另需:type:"checkN", crmMemberId, userID, infoID, userInfo1:"75200"。
**checkToken 可省略**(实测无 token 也返回数据;有 token 时可复用旧值)。

响应 `resp`:
- `code` "00000000";`travelTip` 出行提醒;`lowPriceList` [{date,hasTicket:"A"}] 近期每日票况
- **`departureFlightInfos[]`**:flightNo/airCraft/depTime/arriTime/depTerm、
  `minCombinedPrice`(**最低兑换里程**,如 "15000")、`seatNum` 余票、
  `cabins[]` 各舱位 {classCode(I/X/O), classOfService(business/economy/first), pprice/fprice(>0=可兑), handBaggage, childBaggage}

### 调用注意
- **curl 会被网宿 WAF 302→/500.html 拦(TLS 指纹);python urllib 直连可过**(mitmproxy/python 同栈)
- Cookie 必须带全 `SESSION` + `JSESSIONID`(只带 SESSION 返回登录 HTML 页)
- 无票日期返回 `{"resp":{"msg":"抱歉，暂时没有可兑换航班啦。"}}`
- 入口页面:搜索结果页 showFlights@pg 的"奖励客票"切换(#changeType)→ `awardTickets/showAwardTicketsFlights@pg`
- 现成脚本:`~/travel-skill/airchina/scripts/award_query.py`(已是 airchina 库薄封装)
- **RT 模式响应里没有 returnFlightInfos,回程要反向(org/dst 互换 + leaveDate=returnDate)再查一次**;RT 模式去程 minCombinedPrice 是往返合计价(如 CAN-PEK 经济 26000),反向查回程显示单程价(15000)

### python 库(2026-10-20 新增)★

`~/travel-skill/airchina/`(editable 装进 ~/.venv,依赖 pydantic,README 见库目录):

```python
from airchina import AirChinaClient
ac = AirChinaClient.load()                          # ~/.airchina/session.json
r = ac.award_search("CAN", "PEK", "2026-10-21")     # 或 return_date="2026-10-24" 自动查双向
ac.low_price_calendar("CAN", "PEK", "2026-10-21")   # 现金日历,无需 Cookie
```
CLI:`python -m airchina award|calendar|account|session`。异常体系:CookieExpiredError/WafBlockedError/CaptchaRequiredError/ApiError。
账户概要(a=8 p=34)服务端拒(01010012),req 结构未逆向出——**未通**。

### 会话时长与重登(实测)

- 服务端会话 **~25 分钟空闲过期**(最后成功调用→失效 25min 内);SESSION/JSESSIONID 均会话级、必须全带。
- 验证码 5 分钟有效,重登链路要一气呵成(第一次就因排查按钮多花 7 分钟导致码过期)。
- **重登三步**(人在外地也能做):
  1. `~/.venv/bin/python ~/travel-skill/airchina/scripts/login_flow.py new` —— 填号+滑块+发短信
  2. 用户口述验证码 → `~/.venv/bin/python ~/travel-skill/airchina/scripts/submit_code.py <码>` —— 填码+提交+滑块,loginN 成功回 **AesMap 加密 + Set-Cookie 新 JSESSIONID**(失败回明文错误码如 04030001、无 Set-Cookie)
  3. `~/.venv/bin/python -m airchina session --from-flows /tmp/airchina.flows`
- 登录页陷阱:①#subbtn 的启用条件是 JS 变量 `readdangerFlag && phone && loginCode`,物理点 checkbox 不更新变量,须 `readdangerFlag=true; checkFrom()`;②浏览器渲染器会卡死(页面永远 loading/fetch 挂起/连接池满),`adb shell am force-stop com.android.browser` 后带 URL 重启,新 pid 要重新 forward;③CDP 可能有 /c/ 与 /ac/c/ 两个 login@pg 标签,选已渲染那个(submit_code.py 的 login_target());④submit_code 的滑块拖完 ~13 秒内出 loginN 结果。

## 4. 现金购票航班查询(被 WAF 拦,未通)

`POST /g/invoke.json a=3 p=6`(page=qryFlights):req {org, dst:"PEK|PKX", date, adt, cnn, inf, cabin:"Economy", tabFlag, isgap, isUm, version:"4", geeflag:"qryFlights", userId, mId}。
**该 action 被 WAF/网关 302→/500.html**(响应无 X-Tingyun-Data=未到应用层;同端点 a=0 p=0 正常)。已排除:参数变体、pipe、isUm、登录态。怀疑按 action 级别的反爬策略。响应如返回 risky=true 会走顶象验证码重试(带 checkToken, type:"check")。

## 5. 工具清单(~/travel-skill/airchina/)

2026-10-20 重构后:两库各自独立文件夹,常用脚本在 `~/travel-skill/airchina/scripts/`,
历史实验脚本归档在 `~/tools/airchina/archive/`(下表旧名除标注外都在这两处)。

| 文件 | 用途 |
|---|---|
| **airchina/** | ★ python 库(award/calendar/session,见上) |
| scripts/award_query.py | 奖励客票查询 CLI(airchina 库薄封装) |
| scripts/login_flow.py | 登录链:new=发短信 / submit=提交(均自动解滑块) |
| scripts/submit_code.py | ★ 重登主力:填验证码+启用按钮+提交+滑块+监听 loginN |
| scripts/login_driver.py | CDP 拖动/状态/find_notch(小图变体)函数库 |
| scripts/cdp.py | CDP WebSocket 客户端 |
| scripts/block_trackers.py | mitmproxy 插件:204 掉谷歌统计,防页面卡死 |
| scripts/flowdump.py | 从 flows 提取接口请求/响应 |
| archive/award_flow.py 等 | 历史实验脚本(滑块变体/a=12 捕获/a=3 p=6 排查) |

环境:adb 设备 127.0.0.1:16384(MuMu);WebView 调试 `adb forward tcp:9222 localabstract:webview_devtools_remote_<pid>`;
竖屏点击用 MuMuManager(adb 坐标会转置);python 用 `~/.venv/bin/python -u`(含 pillow/websocket-client/mitmproxy)。
