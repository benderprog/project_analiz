from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.analysis_app.models import CachedPU
from apps.portaldb.models import Pu


class PuCacheModelTests(TestCase):
    databases = {"default", "portal"}

    def test_cached_pu_has_two_embeddings_fields(self):
        fields = {field.name for field in CachedPU._meta.get_fields()}
        self.assertIn("embedding_short", fields)
        self.assertIn("embedding_full", fields)

    @override_settings(SKIP_SEMANTIC_MODEL=False)
    def test_pu_post_save_updates_cached_pu(self):
        class DummyModel:
            def encode(self, texts):
                return [[float(idx), float(idx + 1)] for idx in range(len(texts))]

        with patch("apps.analysis_app.pu_cache.get_sentence_model", return_value=DummyModel()):
            portal_pu = Pu.objects.using("portal").create(
                short_name="ПУ Север",
                full_name="Пограничное управление Север",
            )

        cached = CachedPU.objects.get(portal_pu_id=portal_pu.pu_id)
        self.assertIsNotNone(cached.embedding_short)
        self.assertIsNotNone(cached.embedding_full)


class PuCacheAdminTests(TestCase):
    databases = {"default", "portal"}

    def setUp(self):
        super().setUp()
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password",
        )
        self.client.force_login(self.user)

    def test_admin_has_recompute_button_or_url(self):
        url = reverse("admin:analysis_app_cachedpu_recompute_cache")
        with patch("apps.analysis_app.admin.call_command") as mocked_command:
            response = self.client.get(url)
        mocked_command.assert_called_once_with("sync_pu_cache", rebuild_embeddings=True)
        self.assertEqual(response.status_code, 302)
