from django.test import SimpleTestCase

from apps.portaldb.portal_config import apply_portal_database_settings


class PortalConfigTests(SimpleTestCase):
    def test_apply_portal_database_settings_falls_back_to_current_password(self):
        cfg = {
            "profiles": {
                "dev": {
                    "database": {
                        "name": "portal_db_test",
                        "user": "portal",
                        "password": "",
                        "host": "localhost",
                        "port": 5432,
                    }
                }
            }
        }
        settings_module = {"DATABASES": {"portal": {"PASSWORD": "current-secret"}}}

        resolved = apply_portal_database_settings(settings_module, cfg)

        self.assertEqual(resolved["PASSWORD"], "current-secret")
