from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.audit.events import AUTH_LOGIN_SUCCESS
from apps.audit.middleware import record_user_activity
from apps.audit.models import OperationLog, UserActivityHour
from apps.audit.service import _client_ip, log_operation


class OperationLogModelTests(TestCase):
    def test_str_representation(self):
        log = OperationLog(module="数据导出", action="导出数据", status="success")
        self.assertEqual(str(log), "数据导出.导出数据 success")

    def test_status_choices(self):
        self.assertEqual(OperationLog.Status.SUCCESS, "success")
        self.assertEqual(OperationLog.Status.WARNING, "warning")
        self.assertEqual(OperationLog.Status.FAILED, "failed")

    def test_ordering_by_created_at_desc(self):
        OperationLog.objects.create(
            module="认证授权", action="用户登录", status="success"
        )
        OperationLog.objects.create(
            module="数据查询", action="查询数据", status="success"
        )
        logs = list(OperationLog.objects.all())
        self.assertEqual(logs[0].module, "数据查询")
        self.assertEqual(logs[1].module, "认证授权")


class LogOperationTests(TestCase):
    def test_creates_log_for_authenticated_user(self):
        user = get_user_model().objects.create_user(
            username="logger-test", password="pass12345"
        )

        log_operation(user, "数据导出", "导出数据", "success", "导出成功")

        log = OperationLog.objects.first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, user)
        self.assertEqual(log.module, "数据导出")
        self.assertEqual(log.action, "导出数据")
        self.assertEqual(log.status, "success")
        self.assertEqual(log.message, "导出成功")

    def test_creates_log_with_target_fields(self):
        user = get_user_model().objects.create_user(
            username="target-log-test", password="pass12345"
        )

        log_operation(
            user,
            "数据管理",
            "更新存量数据",
            "success",
            "更新访问权限",
            target_type="data_resource",
            target_id=42,
            target_code="resource-code",
            target_name="样地数据",
        )

        log = OperationLog.objects.first()
        self.assertEqual(log.target_type, "data_resource")
        self.assertEqual(log.target_id, 42)
        self.assertEqual(log.target_code, "resource-code")
        self.assertEqual(log.target_name, "样地数据")

    def test_creates_log_with_stable_event_code(self):
        user = get_user_model().objects.create_user(
            username="event-code-test", password="pass12345"
        )

        log_operation(
            user,
            "认证授权",
            "用户登录",
            "success",
            event_code=AUTH_LOGIN_SUCCESS,
        )

        self.assertEqual(OperationLog.objects.get().event_code, AUTH_LOGIN_SUCCESS)

    def test_creates_log_with_null_user_for_anonymous(self):
        anonymous = MagicMock()
        anonymous.is_authenticated = False

        log_operation(anonymous, "认证授权", "用户登录", "failed", "登录失败")

        log = OperationLog.objects.first()
        self.assertIsNotNone(log)
        self.assertIsNone(log.user)

    def test_creates_log_with_null_user_for_none(self):
        log_operation(None, "认证授权", "用户登录", "failed", "登录失败")

        log = OperationLog.objects.first()
        self.assertIsNotNone(log)
        self.assertIsNone(log.user)

    def test_extracts_ip_from_request(self):
        user = get_user_model().objects.create_user(
            username="ip-test", password="pass12345"
        )
        factory = RequestFactory()
        request = factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "192.168.1.100"

        log_operation(user, "数据查询", "查询数据", "success", request=request)

        log = OperationLog.objects.first()
        self.assertEqual(log.ip_address, "192.168.1.100")

    def test_extracts_ip_from_x_forwarded_for(self):
        user = get_user_model().objects.create_user(
            username="forwarded-test", password="pass12345"
        )
        factory = RequestFactory()
        request = factory.get("/api/test/")
        request.META["HTTP_X_FORWARDED_FOR"] = "10.0.0.1, 10.0.0.2"

        log_operation(user, "数据查询", "查询数据", "success", request=request)

        log = OperationLog.objects.first()
        self.assertEqual(log.ip_address, "10.0.0.1")

    def test_extracts_public_ip_from_proxy_headers(self):
        user = get_user_model().objects.create_user(
            username="real-ip-test", password="pass12345"
        )
        factory = RequestFactory()
        request = factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "172.19.0.3"
        request.META["HTTP_X_REAL_IP"] = "8.8.8.8"

        log_operation(user, "数据查询", "查询数据", "success", request=request)

        log = OperationLog.objects.first()
        self.assertEqual(log.ip_address, "8.8.8.8")

    def test_handles_none_request(self):
        user = get_user_model().objects.create_user(
            username="no-request-test", password="pass12345"
        )

        log_operation(user, "系统测试", "测试日志", "success")

        log = OperationLog.objects.first()
        self.assertIsNone(log.ip_address)


class ClientIpTests(TestCase):
    def test_returns_none_for_none_request(self):
        self.assertIsNone(_client_ip(None))

    def test_returns_remote_addr(self):
        request = MagicMock()
        request.META = {"REMOTE_ADDR": "127.0.0.1"}
        self.assertEqual(_client_ip(request), "127.0.0.1")

    def test_returns_first_x_forwarded_for(self):
        request = MagicMock()
        request.META = {"HTTP_X_FORWARDED_FOR": "10.0.0.1, 10.0.0.2, 10.0.0.3"}
        self.assertEqual(_client_ip(request), "10.0.0.1")

    def test_prefers_public_ip_from_forwarded_chain(self):
        request = MagicMock()
        request.META = {
            "REMOTE_ADDR": "172.19.0.3",
            "HTTP_X_FORWARDED_FOR": "172.19.0.3, 8.8.8.8, 10.0.0.2",
        }
        self.assertEqual(_client_ip(request), "8.8.8.8")

    def test_returns_x_real_ip(self):
        request = MagicMock()
        request.META = {
            "REMOTE_ADDR": "172.19.0.3",
            "HTTP_X_REAL_IP": "8.8.4.4",
        }
        self.assertEqual(_client_ip(request), "8.8.4.4")

    def test_returns_cf_connecting_ip(self):
        request = MagicMock()
        request.META = {
            "REMOTE_ADDR": "172.19.0.3",
            "HTTP_CF_CONNECTING_IP": "1.1.1.1",
        }
        self.assertEqual(_client_ip(request), "1.1.1.1")

    def test_returns_forwarded_for_ip(self):
        request = MagicMock()
        request.META = {
            "REMOTE_ADDR": "172.19.0.3",
            "HTTP_FORWARDED": 'for="[2001:4860:4860::8888]";proto=https',
        }
        self.assertEqual(_client_ip(request), "2001:4860:4860::8888")

    def test_falls_back_to_first_private_ip_when_no_public_ip(self):
        request = MagicMock()
        request.META = {
            "REMOTE_ADDR": "172.19.0.3",
            "HTTP_X_FORWARDED_FOR": "10.0.0.1, 172.19.0.3",
        }
        self.assertEqual(_client_ip(request), "10.0.0.1")

    def test_returns_none_when_no_ip_info(self):
        request = MagicMock()
        request.META = {}
        self.assertIsNone(_client_ip(request))


class UserActivityTests(TestCase):
    def test_records_at_most_one_row_per_user_and_local_hour(self):
        user = get_user_model().objects.create_user(
            username="activity-test", password="pass12345"
        )
        request = SimpleNamespace(user=user, path="/api/catalog/resources/", session={})
        first_hour = timezone.make_aware(datetime(2026, 7, 14, 9, 15))

        self.assertTrue(record_user_activity(request, now=first_hour))
        self.assertTrue(
            record_user_activity(request, now=first_hour + timedelta(minutes=30))
        )
        self.assertEqual(UserActivityHour.objects.filter(user=user).count(), 1)

        self.assertTrue(
            record_user_activity(request, now=first_hour + timedelta(hours=1))
        )
        self.assertEqual(UserActivityHour.objects.filter(user=user).count(), 2)

    def test_ignores_non_api_requests(self):
        user = get_user_model().objects.create_user(
            username="non-api-activity-test", password="pass12345"
        )
        request = SimpleNamespace(user=user, path="/admin/dashboard", session={})

        self.assertFalse(record_user_activity(request))
        self.assertFalse(UserActivityHour.objects.filter(user=user).exists())
