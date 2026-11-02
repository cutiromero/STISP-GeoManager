"""Independent STISP availability monitor; Python 3.9+, standard library only."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


class MonitorError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_webhook(value):
    parsed = urlsplit(value)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "qyapi.weixin.qq.com"
        or parsed.path != "/cgi-bin/webhook/send"
        or parsed.fragment
        or set(query) != {"key"}
        or len(query["key"]) != 1
        or not re.fullmatch(r"[A-Za-z0-9_-]{8,200}", query["key"][0])
    ):
        raise MonitorError("企业微信地址必须是官方群机器人 Webhook，且包含有效 key")
    return value


def load_config(path):
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
        base = config["base_url"].rstrip("/")
        target = urlsplit(base)
        if (
            target.scheme not in {"http", "https"}
            or not target.hostname
            or target.username
            or target.password
            or target.query
            or target.fragment
        ):
            raise ValueError("invalid target")
        for name, default, minimum, maximum in [
            ("interval_seconds", 30, 5, 3600),
            ("timeout_seconds", 8, 1, 60),
            ("failure_threshold", 3, 1, 20),
            ("recovery_threshold", 2, 1, 20),
            ("repeat_alert_seconds", 1800, 0, 86400),
        ]:
            value = config.get(name, default)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(name)
            config[name] = value
        config["base_url"] = base
        config["name"] = str(config.get("name", "时空智能服务平台"))[:100]
        config["home_marker"] = str(config.get("home_marker", "时空智能服务平台"))
        state = Path(config.get("state_file", "monitor-state.json"))
        config["state_file"] = state if state.is_absolute() else path.parent / state
        webhook_file = config.get("webhook_file")
        from_file = ""
        if webhook_file:
            secret_path = Path(webhook_file)
            if not secret_path.is_absolute():
                secret_path = path.parent / secret_path
            if secret_path.stat().st_size > 4096:
                raise ValueError("webhook file size")
            from_file = secret_path.read_text(encoding="utf-8-sig").strip()
        webhook = config.get("webhook_url") or from_file or os.environ.get(
            config.get("webhook_env", "STISP_WECOM_WEBHOOK"), ""
        )
        config["webhook_url"] = validate_webhook(webhook) if webhook else ""
        return config
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise MonitorError("配置读取失败，请核对 JSON、网址和数值范围") from exc


def probe(config):
    checks = []
    for name, suffix in [("健康接口", "/api/health/"), ("首页", "/")]:
        try:
            request = Request(
                config["base_url"] + suffix,
                headers={"User-Agent": "STISP-Availability-Monitor/1.0"},
            )
            with urlopen(request, timeout=config["timeout_seconds"]) as response:
                raw = response.read(262145)
                if response.status != 200 or len(raw) > 262144:
                    raise MonitorError("响应状态或大小异常")
                if suffix == "/api/health/":
                    body = json.loads(raw)
                    ok = body.get("status") == "ok" and body.get("configLoaded", True)
                else:
                    ok = config["home_marker"] in raw.decode("utf-8", errors="replace")
                checks.append({"name": name, "ok": bool(ok), "detail": "正常" if ok else "响应内容异常"})
        except HTTPError as exc:
            checks.append({"name": name, "ok": False, "detail": "HTTP " + str(exc.code)})
        except (URLError, OSError):
            checks.append({"name": name, "ok": False, "detail": "网络连接失败或超时"})
        except (ValueError, AttributeError, MonitorError):
            checks.append({"name": name, "ok": False, "detail": "返回内容异常"})
    return {"ok": all(item["ok"] for item in checks), "checks": checks}


def initial_state():
    return {
        "version": 1,
        "status": "unknown",
        "consecutive_failures": 0,
        "consecutive_successes": 0,
        "outage_started_at": 0,
        "outage_notified": False,
        "last_alert_at": 0,
        "pending_recovery": False,
    }


def evaluate(previous, result, config, now):
    state = {**initial_state(), **previous, "last_probe_at": now, "checks": result["checks"]}
    event = None
    if result["ok"]:
        state["consecutive_failures"] = 0
        state["consecutive_successes"] += 1
        if state["status"] == "unknown":
            state["status"] = "up"
        if state["status"] == "down" and state["consecutive_successes"] >= config["recovery_threshold"]:
            state["status"] = "up"
            state["pending_recovery"] = state["outage_notified"]
        if state["pending_recovery"]:
            event = "recovery"
    else:
        state["consecutive_successes"] = 0
        state["consecutive_failures"] += 1
        if state["consecutive_failures"] == 1:
            state["first_failure_at"] = now
        if state["consecutive_failures"] >= config["failure_threshold"]:
            if state["status"] != "down":
                state.update(
                    status="down", outage_started_at=state.get("first_failure_at", now),
                    outage_notified=False, pending_recovery=False,
                )
            repeat = config["repeat_alert_seconds"]
            if not state["outage_notified"] or (repeat > 0 and now - state["last_alert_at"] >= repeat):
                event = "down"
    return state, event


def notification_text(event, state, config, now):
    from datetime import datetime, timedelta, timezone

    local = datetime.fromtimestamp(now, timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    status = "服务异常" if event == "down" else "服务已恢复"
    lines = ["### " + config["name"] + "：" + status, "时间：" + local + "（北京时间）", "地址：" + config["base_url"]]
    if event == "down":
        lines.append("已连续 " + str(state["consecutive_failures"]) + " 轮检查失败。")
        lines.extend(item["name"] + "：" + item["detail"] for item in state["checks"])
    else:
        minutes = max(0, now - state["outage_started_at"]) / 60
        lines.append("健康接口和首页均已恢复。异常持续约 %.1f 分钟。" % minutes)
    return "\n".join(lines)


def send_notification(webhook, text):
    payload = json.dumps({"msgtype": "markdown", "markdown": {"content": text}}, ensure_ascii=False).encode("utf-8")
    request = Request(webhook, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            body = json.loads(response.read(65536))
        if not isinstance(body, dict):
            raise MonitorError("企业微信返回了无法识别的响应")
        if body.get("errcode") != 0:
            raise MonitorError("企业微信未接受通知，错误码 " + str(body.get("errcode", "unknown")))
    except (URLError, OSError, ValueError) as exc:
        raise MonitorError("企业微信通知发送失败：" + type(exc).__name__) from None


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + str(os.getpid()) + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(state, stream, ensure_ascii=False, indent=2)
    with contextlib.suppress(OSError):
        temporary.chmod(0o600)
    temporary.replace(path)


@contextlib.contextmanager
def single_instance(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    stream.seek(0, os.SEEK_END)
    if not stream.tell():
        stream.write(b"0")
        stream.flush()
    stream.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise MonitorError("相同状态文件已有监测进程运行，未重复启动") from None
    try:
        yield
    finally:
        stream.close()


def monitor(config, once=False):
    path = config["state_file"]
    with single_instance(path.with_suffix(path.suffix + ".lock")):
        try:
            state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else initial_state()
            if not isinstance(state, dict) or state.get("version") != 1:
                raise ValueError("state format")
        except (OSError, ValueError):
            raise MonitorError("已有监测状态无法读取，原文件已保留，请检查后再启动") from None
        last_status = None
        while True:
            started = time.monotonic()
            now = time.time()
            result = probe(config)
            state, event = evaluate(state, result, config, now)
            if event:
                try:
                    send_notification(config["webhook_url"], notification_text(event, state, config, now))
                    state["last_notification_error"] = ""
                    if event == "down":
                        state.update(outage_notified=True, last_alert_at=now)
                    else:
                        state.update(pending_recovery=False, outage_notified=False)
                except MonitorError as exc:
                    state["last_notification_error"] = str(exc)
            save_state(path, state)
            if once or event or state["status"] != last_status:
                print(json.dumps({"status": state["status"], "checks": result["checks"], "notification": event,
                    "notificationError": state.get("last_notification_error", "")}, ensure_ascii=False), flush=True)
            last_status = state["status"]
            if once:
                return
            time.sleep(max(1, config["interval_seconds"] - (time.monotonic() - started)))


def main():
    parser = argparse.ArgumentParser(description="时空智能平台独立可用性监测及企业微信群告警")
    parser.add_argument("--config", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="只检查访问，不发送通知或保存状态")
    mode.add_argument("--once", action="store_true", help="执行一轮监测，达到阈值时可能发送通知")
    mode.add_argument("--notify-test", action="store_true", help="明确发送一条测试群通知后退出")
    args = parser.parse_args()
    try:
        config = load_config(args.config.resolve())
        if args.check:
            result = probe(config)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["ok"] else 1
        if not config["webhook_url"]:
            raise MonitorError("未配置企业微信群机器人 Webhook，监测告警尚未启用")
        if args.notify_test:
            send_notification(config["webhook_url"], "### " + config["name"] + "\n这是一条人工发起的监测通知测试。")
            print("测试通知已发送")
        else:
            monitor(config, args.once)
        return 0
    except MonitorError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, ValueError, TypeError) as exc:
        print("监测运行失败，请检查私有状态目录：" + type(exc).__name__, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
