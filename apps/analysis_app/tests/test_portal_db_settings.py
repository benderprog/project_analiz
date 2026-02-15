from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.db import connections
from django.test import RequestFactory, TestCase

from apps.analysis_app.admin import PortalDbConnectionSettingsAdmin
from apps.analysis_app.admin_forms import PortalDbConnectionSettingsAdminForm
from apps.analysis_app.models import PortalDbConnectionSettings
from apps.analysis_app.portal_db_runtime import apply_portal_db_settings
from apps.analysis_app.utils import portal_db_crypto


class _FakeFernet:
    def encrypt(self, value: bytes) -> bytes:
        return b"enc::" + value

    def decrypt(self, value: bytes) -> bytes:
        return value.replace(b"enc::", b"", 1)


class PortalDbCryptoTests(TestCase):
    @patch("apps.analysis_app.utils.portal_db_crypto._get_fernet", return_value=_FakeFernet())
    def test_password_encrypted_roundtrip(self, _):
        encrypted = portal_db_crypto.encrypt_password("secret")
        self.assertNotEqual(encrypted, "secret")
        self.assertEqual(portal_db_crypto.decrypt_password(encrypted), "secret")


class PortalDbAdminTests(TestCase):
    def setUp(self):
        self.site = AdminSite()
        self.admin = PortalDbConnectionSettingsAdmin(PortalDbConnectionSettings, self.site)
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass",
        )

    def test_admin_blank_password_keeps_existing(self):
        settings_obj = PortalDbConnectionSettings.objects.order_by("id").first()
        settings_obj.host = "localhost"
        settings_obj.port = 5432
        settings_obj.db_name = "portal"
        settings_obj.user = "portal"
        settings_obj.password_encrypted = "existing-token"
        settings_obj.save()
        form = PortalDbConnectionSettingsAdminForm(
            data={
                "profile": "TEST",
                "host": "localhost",
                "port": 5432,
                "db_name": "portal",
                "user": "portal",
                "password": "",
            },
            instance=settings_obj,
        )
        self.assertTrue(form.is_valid(), form.errors)
        request = self.factory.post("/")
        request.user = self.user

        with patch("apps.analysis_app.admin.apply_portal_db_settings"):
            self.admin.save_model(request, settings_obj, form, change=True)

        settings_obj.refresh_from_db()
        self.assertEqual(settings_obj.password_encrypted, "existing-token")


    @patch("apps.analysis_app.admin.psycopg2.connect")
    def test_check_connection_uses_fallback_password_when_model_password_blank(self, mocked_connect):
        settings_obj = PortalDbConnectionSettings.objects.order_by("id").first()
        settings_obj.host = "localhost"
        settings_obj.port = 5432
        settings_obj.db_name = "portal"
        settings_obj.user = "portal"
        settings_obj.password_encrypted = ""
        settings_obj.save()

        connections.databases["portal"]["PASSWORD"] = "runtime-pass"

        self.admin._connect_to_db(settings_obj)

        self.assertEqual(mocked_connect.call_args.kwargs["password"], "runtime-pass")
        self.assertIsNotNone(mocked_connect.call_args.kwargs["password"])

    @patch.object(PortalDbConnectionSettingsAdmin, "_connect_to_db", side_effect=RuntimeError("boom"))
    def test_check_connection_handles_failure(self, _):
        settings_obj = PortalDbConnectionSettings.objects.order_by("id").first()
        settings_obj.host = "bad-host"
        settings_obj.port = 5432
        settings_obj.db_name = "portal"
        settings_obj.user = "portal"
        settings_obj.password_encrypted = "token"
        settings_obj.save()
        request = self.factory.get("/")
        request.user = self.user

        with patch.object(self.admin, "message_user"):
            self.admin.check_connection_view(request, str(settings_obj.pk))

        settings_obj.refresh_from_db()
        self.assertFalse(settings_obj.last_check_ok)
        self.assertIn("boom", settings_obj.last_check_error)
        self.assertIsNotNone(settings_obj.last_check_at)


class PortalDbRuntimeTests(TestCase):
    def test_apply_portal_db_settings_sets_readonly_options_for_prod(self):
        settings_obj = PortalDbConnectionSettings.objects.order_by("id").first()
        settings_obj.profile = PortalDbConnectionSettings.Profile.PROD
        settings_obj.host = "prod-host"
        settings_obj.port = 5432
        settings_obj.db_name = "prod_db"
        settings_obj.user = "prod_user"
        settings_obj.password_encrypted = "token"
        settings_obj.save()

        with patch("apps.analysis_app.portal_db_runtime.decrypt_password", return_value="plain"):
            apply_portal_db_settings()

        from django.db import connections

        self.assertEqual(
            connections.databases["portal"].get("OPTIONS"),
            {"options": "-c default_transaction_read_only=on"},
        )

    @patch("apps.analysis_app.portal_db_runtime.decrypt_password", return_value="")
    def test_apply_portal_db_settings_keeps_current_password_when_password_empty(self, _):
        settings_obj = PortalDbConnectionSettings.objects.order_by("id").first()
        settings_obj.profile = PortalDbConnectionSettings.Profile.TEST
        settings_obj.host = "test-host"
        settings_obj.port = 5432
        settings_obj.db_name = "test_db"
        settings_obj.user = "test_user"
        settings_obj.password_encrypted = ""
        settings_obj.save()

        original = dict(connections.databases["portal"])
        try:
            connections.databases["portal"]["PASSWORD"] = "existing-runtime-password"
            apply_portal_db_settings()

            self.assertEqual(
                connections.databases["portal"]["PASSWORD"],
                "existing-runtime-password",
            )
            self.assertIsNotNone(connections.databases["portal"]["PASSWORD"])
        finally:
            connections.databases["portal"] = original
