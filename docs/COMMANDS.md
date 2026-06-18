# Funding Sentinel 命令词

下面命令默认在项目目录执行：

```powershell
cd C:\Users\hek\Documents\资金费率前哨
```

## 日常运行

启动虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

启动机器人持续监控：

```powershell
py -m funding_sentinel.main
```

只扫描一次后退出：

```powershell
py -m funding_sentinel.main --once
```

停止正在运行的机器人：

```powershell
Ctrl+C
```

干跑测试，不发送 Telegram：

```powershell
$env:DRY_RUN='true'
py -m funding_sentinel.main --once
Remove-Item Env:\DRY_RUN
```

运行单元测试：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test*.py" -v
```

查看 GitHub 远端最新提交：

```powershell
gh api repos/yuriswj12-bit/funding-sentinel/commits/main --jq "{sha:.sha,message:.commit.message,date:.commit.committer.date}"
```

查看本地代码状态：

```powershell
.\.tools\mingit\cmd\git.exe status --short --branch
```

## 关键配置词

这些配置写在 `.env`，改完后需要重启机器人。

Telegram：

```text
TG_BOT_TOKEN=
TG_CHAT_ID=
```

市场扫描：

```text
MARKET_SCAN=true
MIN_ALERT_LEVEL=L1
MAX_CANDIDATE_SYMBOLS=70
MIN_24H_VOLUME_USDT=5000000
```

过滤项：

```text
EXCLUDE_TOKENIZED_STOCKS=true
EXCLUDE_MAJOR_SPOT_SYMBOLS=true
EXCLUDE_STABLECOINS=true
NEGATIVE_FUNDING_ONLY=false
PREFER_NEGATIVE_FUNDING=false
```

3m 资金费率 + 量能确认：

```text
VOLUME_TIMEFRAME=3m
```

15m 巨量异动告警：

```text
SPIKE_VOLUME_TIMEFRAME=15m
SPIKE_VOLUME_PREV_BARS=8
SPIKE_VOLUME_RATIO_THRESHOLD=4.0
```

稳定费率放量监控：

```text
STEALTH_VOLUME_TIMEFRAME=15m
STEALTH_VOLUME_PREV_BARS=8
STEALTH_VOLUME_RATIO_THRESHOLD=2.5
STEALTH_ONE_HOUR_VOLUME_USDT=5000000
STEALTH_TREND_BARS=3
STEALTH_MAX_CANDIDATE_SYMBOLS=60
```

冷却时间：

```text
CHECK_INTERVAL_SECONDS=45
ALERT_COOLDOWN_SECONDS=2700
L4_COOLDOWN_SECONDS=2700
```

周期报告：

```text
REPORT_ENABLED=true
REPORT_INTERVAL_HOURS=12
REPORT_WINDOW_HOURS=12
REPORT_TOP_N=10
```

数据文件：

```text
SQLITE_PATH=data/sentinel.sqlite3
```

## 告警类型

资金费率哨兵告警：

```text
L1-L2：需要 3m 放量确认才推送
L3-L4：可先推送，后续 3m 放量确认会补发升级提醒
```

15m 巨量异动告警：

```text
资金费率达到 L1-L4
15m 原始量比 >= 4x
45 分钟内同币同方向不重复推送
```

稳定费率放量监控：

```text
资金费率低于 L1
15m 原始量比 >= 2.5x
最近 1h 成交额 >= 500 万 USDT
最近 3 根 15m K 线成交量递增
45 分钟内同币不重复推送
```

## 常见改法

降低稳定费率放量监控数量，减少请求：

```text
STEALTH_MAX_CANDIDATE_SYMBOLS=40
```

提高稳定费率放量阈值，减少噪音：

```text
STEALTH_VOLUME_RATIO_THRESHOLD=3.0
```

提高 15m 巨量异动阈值：

```text
SPIKE_VOLUME_RATIO_THRESHOLD=5.0
```

只监控指定币种：

```text
MARKET_SCAN=false
MONITORED_SYMBOLS=SENTUSDT,ZECUSDT,BEATUSDT
```
