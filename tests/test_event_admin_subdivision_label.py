from django.contrib.admin.sites import AdminSite
from django.test import SimpleTestCase

from apps.portaldb.admin import EventAdmin
from apps.portaldb.models import Event, Pu, Subdivision


class EventAdminSubdivisionLabelTests(SimpleTestCase):
    def test_subdivision_str_includes_full_name_and_pu(self):
        pu = Pu(full_name="ПУ Южное", short_name="ПУ Южное")
        subdivision = Subdivision(
            name="ПОГК «Васильковое» (пгт Васильковое)",
            short_name="Васильковое",
            parent_pu=pu,
        )

        label = str(subdivision)

        self.assertIn(subdivision.name, label)
        self.assertIn(pu.short_name, label)
        self.assertNotEqual(label, subdivision.short_name)

    def test_event_admin_labels_find_subdivision_unit(self):
        admin_site = AdminSite()
        admin_instance = EventAdmin(Event, admin_site)
        db_field = Event._meta.get_field("find_subdivision_unit")
        pu = Pu(full_name="ПУ Южное", short_name="ПУ Южное")
        subdivision = Subdivision(
            name="ПОГК «Васильковое» (пгт Васильковое)",
            short_name="Васильковое",
            parent_pu=pu,
        )

        formfield = admin_instance.formfield_for_foreignkey(db_field, request=None)

        self.assertIsNotNone(formfield)
        self.assertEqual(formfield.label_from_instance(subdivision), str(subdivision))
