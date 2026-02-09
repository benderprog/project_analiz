import uuid

from django.test import TestCase, override_settings

from apps.analysis_app.models import CachedSubdivision
from apps.analysis_app.subdivision_cache import sync_subdivision_cache
from apps.portaldb.models import Pu, Subdivision


@override_settings(SKIP_SEMANTIC_MODEL=True)
class SubdivisionCacheSyncTests(TestCase):
    databases = {"default", "portal"}

    def test_sync_subdivision_cache_populates_parent_pu_id(self):
        pu = Pu.objects.using("portal").create(pu_id=uuid.uuid4(), name="ПУ Север")
        subdivision = Subdivision.objects.using("portal").create(
            subdivision_id=uuid.uuid4(),
            name="Отдел Север",
            short_name="Отдел Север",
            parent_pu=pu,
        )

        sync_subdivision_cache()

        cached = CachedSubdivision.objects.get(
            portal_subdivision_id=subdivision.subdivision_id
        )
        self.assertEqual(cached.parent_pu_id, pu.pu_id)
