# 平台可用性监测与企业微信群通知

监测程序独立于 Django，使用 Python 3.9 以上版本的标准库。默认每30秒检查公网首页及 `/api/health/`；连续3轮失败发送群告警，连续2轮恢复正常后发送恢复通知。持续异常每30分钟提醒一次；设 `repeat_alert_seconds=0` 可只通知状态变化。重启监测后读取同一状态文件，保留告警与恢复进度。

当前选择先在本机运行。电脑关机、休眠、断网或退出监测进程期间不会检查平台，也不能发出停服通知。需要持续覆盖服务器断电、硬盘维护等故障时，将同一个工具和私有配置放在另一台长期在线设备上；仅在平台服务器自身运行，无法发现该服务器断电。

## 准备私有配置

1. 在企业微信群添加自定义机器人，取得机器人的 Webhook。
2. 将地址独立保存为本机私有文本文件，例如仓库 `.runtime/platform-monitor/wecom-webhook.txt`。文件中只放完整地址，不把它加入 Git 或截图公开。
3. 将 `deploy/monitoring/monitor-config.example.json` 复制为 `.runtime/platform-monitor/config.json`，加入 `"webhook_file": "wecom-webhook.txt"`。配置、状态、锁和日志均放在这个 Git 忽略目录中。

也支持通过 `STISP_WECOM_WEBHOOK` 环境变量，或私有 JSON 的 `webhook_url` 配置。提交的示例不包含凭据。程序只接受企业微信官方 HTTPS 机器人接口，不跟随通知接口的重定向，也不在日志中打印机器人地址。

## 先检查，再接通群通知

在仓库根目录运行以下命令。`--check` 只访问公网页面，不发送通知、不写入监测状态。

```powershell
& 'C:/Users/uboo/miniconda3/envs/uboo/python.exe' -X utf8 deploy/monitoring/monitor.py --config .runtime/platform-monitor/config.json --check
```

确认需要向群内发一条测试消息后，显式执行：

```powershell
& 'C:/Users/uboo/miniconda3/envs/uboo/python.exe' -X utf8 deploy/monitoring/monitor.py --config .runtime/platform-monitor/config.json --notify-test
```

随后隐藏启动；重复启动会检查 PID、启动时间、命令与文件锁，避免同一监测重复运行：

```powershell
./deploy/monitoring/monitor-windows.ps1 -Action Start -Config .runtime/platform-monitor/config.json
./deploy/monitoring/monitor-windows.ps1 -Action Status -Config .runtime/platform-monitor/config.json
./deploy/monitoring/monitor-windows.ps1 -Action Stop -Config .runtime/platform-monitor/config.json
```

停止命令只处理本工具登记且身份匹配的进程，不按进程名批量停止 Python。私有目录中的 `monitor-process.json` 记录进程身份，`monitor-state.json` 记录检查与告警状态，`monitor.log`、`monitor-error.log` 记录运行输出。Webhook 无效、群机器人限流或网络故障时，状态会保留发送失败信息，下轮继续尝试；不能将“检测到了异常”误称为“群消息已送达”。

若需登录 Windows 后自动启动，可在“任务计划程序”中创建当前用户任务：触发器选择“登录时”，程序选择 PowerShell，参数为 `-NoProfile -WindowStyle Hidden -File "<仓库绝对路径>/deploy/monitoring/monitor-windows.ps1" -Action Start -Config "<私有配置绝对路径>"`。本次提供工具和用法，只有接通实际 Webhook 并启用进程/任务后才算监测已上线。

## 其他常在线设备

复制 `monitor.py` 和私有配置，配置中的网址保持为公网入口。前台运行：

```bash
python3 monitor.py --config /private/stisp-monitor/config.json
```

可由设备现有的进程管理器持续运行上述命令。对相同状态文件重复启动会被文件锁拒绝；持续运行不依赖登录平台、用户会话或服务器上的模型服务。

## 检查范围

本工具判断“公网首页和健康接口是否可用”，可识别连接失败、超时、502等错误，以及健康接口返回了错误内容的情况。它不主动提交计算、访问科研数据或模拟登录，因此不能据此判断每一种算法及模型回答都正常。群通知使用企业微信网络，监测机自身断网同样会影响送达。

验证命令：`python deploy/monitoring/test_monitor.py`。单测覆盖短暂故障抑制、连续失败、持续故障提醒、恢复和状态恢复、发送失败重试、Webhook目标限制及重复进程保护，不向任何真实群发送消息。
