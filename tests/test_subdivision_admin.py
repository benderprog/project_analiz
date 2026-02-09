from django.contrib.admin.sites import AdminSite
from django.test import SimpleTestCase

from apps.portaldb.admin import SubdivisionAdmin
from apps.portaldb.models import Subdivision


class SubdivisionAdminConfigTests(SimpleTestCase):
    def test_list_display_includes_short_name(self):
        admin_site = AdminSite()
        admin_instance = SubdivisionAdmin(Subdivision, admin_site)

        self.assertIn("short_name", admin_instance.list_display)
        self.assertIn("short_name", admin_instance.search_fields)
