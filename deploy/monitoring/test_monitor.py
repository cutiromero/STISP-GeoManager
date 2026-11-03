import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("monitor", Path(__file__).with_name("monitor.py"))
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.config = {"failure_threshold": 3, "recovery_threshold": 2, "repeat_alert_seconds": 1800}
        self.up = {"ok": True, "checks": [{"name": "健康接口", "ok": True, "detail": "正常"}]}
        self.down = {"ok": False, "checks": [{"name": "健康接口", "ok": False, "detail": "HTTP 502"}]}

    def test_transient_failure_does_not_alert(self):
        state = monitor.initial_state()
        for now in (10, 40):
            state, event = monitor.evaluate(state, self.down, self.config, now)
            self.assertIsNone(event)
        state, event = monitor.evaluate(state, self.up, self.config, 70)
        self.assertIsNone(event)
        self.assertEqual(state["status"], "up")

    def test_outage_repeat_suppression_and_recovery_after_persisted_state(self):
        state = monitor.initial_state()
        for now in (10, 40, 70):
            state, event = monitor.evaluate(state, self.down, self.config, now)
        self.assertEqual(event, "down")
        state.update(outage_notified=True, last_alert_at=70)
        state = json.loads(json.dumps(state))
        state, event = monitor.evaluate(state, self.down, self.config, 100)
        self.assertIsNone(event)
        state, event = monitor.evaluate(state, self.down, self.config, 1870)
        self.assertEqual(event, "down")
        state, event = monitor.evaluate(state, self.up, self.config, 1900)
        self.assertIsNone(event)
        state, event = monitor.evaluate(state, self.up, self.config, 1930)
        self.assertEqual(event, "recovery")

    def test_failed_delivery_remains_retryable(self):
        state = monitor.initial_state()
        for now in (10, 40, 70, 100):
            state, event = monitor.evaluate(state, self.down, self.config, now)
        self.assertEqual(event, "down")
        self.assertFalse(state["outage_notified"])

    def test_webhook_cannot_redirect_secret_to_another_host(self):
        good = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdefgh-1234"
        self.assertEqual(monitor.validate_webhook(good), good)
        for value in [
            good.replace("https://", "http://"),
            good.replace("qyapi.weixin.qq.com", "qyapi.weixin.qq.com.evil.test"),
            good + "&key=second-key",
            good + "#fragment",
        ]:
            with self.assertRaises(monitor.MonitorError):
                monitor.validate_webhook(value)

    def test_notification_requires_wecom_success(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self, _):
                return b'{"errcode": 93000}'
        with patch.object(monitor, "build_opener") as factory:
            factory.return_value.open.return_value = Response()
            with self.assertRaises(monitor.MonitorError):
                monitor.send_notification("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abcdefgh", "test")

    def test_proxy_html_with_200_is_not_a_healthy_platform(self):
        class Response:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self, _):
                return "<title>时空智能服务平台</title>".encode("utf-8")
        with patch.object(monitor, "urlopen", return_value=Response()):
            result = monitor.probe({"base_url": "http://platform.test", "timeout_seconds": 1, "home_marker": "时空智能服务平台"})
        self.assertFalse(result["ok"])
        self.assertFalse(result["checks"][0]["ok"])
        self.assertTrue(result["checks"][1]["ok"])

    def test_delivery_failure_is_saved_without_claiming_delivery(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            config = {**self.config, "state_file": path, "failure_threshold": 1,
                "name": "测试平台", "base_url": "http://platform.test", "webhook_url": "not-sent"}
            with patch.object(monitor, "probe", return_value=self.down), patch.object(monitor, "send_notification", side_effect=monitor.MonitorError("发送失败")), patch("builtins.print"):
                monitor.monitor(config, once=True)
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "down")
            self.assertFalse(state["outage_notified"])
            self.assertEqual(state["last_notification_error"], "发送失败")

    def test_single_instance_and_atomic_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            monitor.save_state(path, monitor.initial_state())
            self.assertEqual(json.loads(path.read_text())["version"], 1)
            lock = path.with_suffix(".lock")
            with monitor.single_instance(lock):
                with self.assertRaises(monitor.MonitorError):
                    with monitor.single_instance(lock):
                        self.fail("Duplicate process accepted")


if __name__ == "__main__":
    unittest.main()
