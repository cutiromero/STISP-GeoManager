import hashlib
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.test import Client, TestCase

from apps.core.browser_sessions import SESSION_KEY


class BrowserSessionTests(TestCase):
    token = "a" * 64
    page = "first_page_12345678"

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "page-user", password="test-page-password"
        )

    def action(self, action, *, page=None, token=None, sequence=1):
        return self.client.post(
            "/api/auth/browser-session/",
            json.dumps(
                {
                    "action": action,
                    "pageId": page or self.page,
                    "token": token or self.token,
                    "sequence": sequence,
                }
            ),
            content_type="application/json",
        )

    def login(self, **extra):
        return self.client.post(
            "/api/auth/login/",
            json.dumps(
                {
                    "username": self.user.username,
                    "password": "test-page-password",
                    **extra,
                }
            ),
            content_type="application/json",
        )

    def start(self):
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.action("start").status_code, 200)

    def test_real_login_requires_page_lease_even_with_remember_true(self):
        response = self.login(remember=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.cookies["sessionid"]["max-age"], "")
        self.assertEqual(response.cookies["sessionid"]["expires"], "")
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.assertEqual(self.action("start").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)
        state = self.client.session[SESSION_KEY]
        self.assertNotIn(self.token, json.dumps(state))
        self.assertEqual(
            state["pages"][self.page]["digest"],
            hashlib.sha256(self.token.encode()).hexdigest(),
        )

    def test_raw_superuser_has_same_close_and_refresh_policy(self):
        self.user.is_superuser = self.user.is_staff = True
        self.user.save(update_fields=["is_superuser", "is_staff"])
        self.start()
        self.assertEqual(self.action("suspend", sequence=2).json()["active"], False)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/profile/").status_code, 401)
        self.assertEqual(self.action("resume", sequence=3).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)

    def test_close_last_page_blocks_cookie_replay_then_reload_can_resume(self):
        self.start()
        old_cookie = self.client.cookies["sessionid"].value
        self.assertEqual(self.action("suspend", sequence=2).status_code, 200)
        replay = Client()
        replay.cookies["sessionid"] = old_cookie
        self.assertEqual(replay.get("/api/auth/me/").status_code, 401)
        self.assertEqual(replay.get("/api/agent/bootstrap/").status_code, 401)
        self.assertEqual(self.action("resume", sequence=3).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)

    def test_closing_one_of_two_pages_keeps_other_page_authorized(self):
        self.start()
        self.assertEqual(
            self.action("resume", page="second_page_1234567").status_code, 200
        )
        self.assertEqual(self.action("suspend", sequence=2).json()["active"], True)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)
        self.assertEqual(
            self.action("suspend", page="second_page_1234567", sequence=2).json()[
                "active"
            ],
            False,
        )
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)

    def test_stale_heartbeat_cannot_reactivate_closed_page(self):
        self.start()
        self.action("suspend", sequence=3)
        self.assertEqual(self.action("heartbeat", sequence=2).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.action("resume", sequence=4)
        self.action("suspend", sequence=3)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)

    def test_lost_close_notification_expires_after_120_seconds(self):
        with patch("apps.core.browser_sessions.time.time", return_value=1000):
            self.start()
        with patch("apps.core.browser_sessions.time.time", return_value=1121):
            self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
            self.assertEqual(self.action("heartbeat", sequence=2).status_code, 401)
            self.assertEqual(self.action("resume", sequence=3).status_code, 401)

    def test_refresh_window_is_20_seconds(self):
        with patch("apps.core.browser_sessions.time.time", return_value=1000):
            self.start()
            self.action("suspend", sequence=2)
        with patch("apps.core.browser_sessions.time.time", return_value=1021):
            self.assertEqual(self.action("resume", sequence=3).status_code, 401)

    def test_new_visit_abandon_invalidates_actual_server_session(self):
        self.start()
        cookie = self.client.cookies["sessionid"].value
        self.assertEqual(self.action("abandon").status_code, 200)
        self.assertFalse(Session.objects.filter(session_key=cookie).exists())
        self.client.cookies["sessionid"] = cookie
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)

    def test_bad_token_and_restart_cannot_claim_existing_session(self):
        self.start()
        self.assertEqual(self.action("resume", token="b" * 64).status_code, 401)
        self.assertEqual(
            self.action("start", page="new_page_123456789", token="b" * 64).status_code,
            401,
        )
        self.assertEqual(self.action("heartbeat", sequence=0).status_code, 400)

    def test_legacy_session_is_removed_on_fresh_page_abandon(self):
        self.client.force_login(self.user)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(self.action("resume").status_code, 401)
        self.assertEqual(self.action("abandon").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)

    def test_guest_login_uses_same_lease_and_close_policy(self):
        self.assertEqual(self.client.post("/api/auth/guest-login/").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.assertEqual(self.action("start").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 200)
        self.action("suspend", sequence=2)
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)

    def test_lifecycle_keeps_standard_csrf_validation(self):
        secure = Client(enforce_csrf_checks=True)
        secure.get("/api/auth/csrf/")
        old_csrf = secure.cookies["csrftoken"].value
        response = secure.post(
            "/api/auth/login/",
            json.dumps(
                {"username": self.user.username, "password": "test-page-password"}
            ),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=old_csrf,
        )
        self.assertEqual(response.status_code, 200)
        body = json.dumps(
            {"action": "start", "pageId": self.page, "token": self.token, "sequence": 1}
        )
        self.assertEqual(
            secure.post(
                "/api/auth/browser-session/", body, content_type="application/json"
            ).status_code,
            403,
        )
        self.assertEqual(
            secure.post(
                "/api/auth/browser-session/",
                body,
                content_type="application/json",
                HTTP_X_CSRFTOKEN=secure.cookies["csrftoken"].value,
            ).status_code,
            200,
        )
