from django.contrib.admin.sites import AdminSite
from django.test import SimpleTestCase

from apps.portaldb.admin import OffenderAdmin, OffenderInline
from apps.portaldb.models import Offender


class OffenderAdminConfigTests(SimpleTestCase):
    def setUp(self):
        self.admin_site = AdminSite()

    def test_list_display_order(self):
        admin_instance = OffenderAdmin(Offender, self.admin_site)

        self.assertEqual(
            admin_instance.list_display,
            ("second_name", "first_name", "patronymic_name", "date_of_birth", "event"),
        )

    def test_fields_order(self):
        admin_instance = OffenderAdmin(Offender, self.admin_site)

        self.assertEqual(
            admin_instance.fields,
            ("second_name", "first_name", "patronymic_name", "date_of_birth", "event"),
        )

    def test_inline_fields_order(self):
        self.assertEqual(
            OffenderInline.fields,
            ("second_name", "first_name", "patronymic_name", "date_of_birth"),
        )
