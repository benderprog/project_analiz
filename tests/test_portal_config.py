import io
import os
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase

from apps.portaldb.portal_config import (
    apply_portal_database_settings,
    expand_env_vars,
    load_yaml,
)
from apps.portaldb.sql_registry import SQLRegistry


class PortalConfigTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        self._environ = os.environ.copy()
        self.addCleanup(self._restore_environ)

    def _restore_environ(self):
        os.environ.clear()
        os.environ.update(self._environ)

    def test_expand_env_vars_requires_env(self):
        with self.assertRaises(ValueError) as context:
            expand_env_vars({"value": "${MISSING_VAR}"})
        self.assertIn("MISSING_VAR", str(context.exception))

    def test_apply_portal_database_settings_from_yaml(self):
        fixture_path = Path(__file__).parent / "fixtures" / "portal_config.yml"
        os.environ.update(
            {
                "PORTAL_PROFILE": "dev",
                "PORTAL_DB_NAME": "portal_db",
                "PORTAL_DB_USER": "portal_user",
                "PORTAL_DB_PASSWORD": "portal_pass",
                "PORTAL_DB_HOST": "127.0.0.1",
                "PORTAL_DB_PORT": "5433",
            }
        )
        cfg = load_yaml(fixture_path)
        db_settings = apply_portal_database_settings(globals(), cfg)
        self.assertEqual(db_settings["HOST"], "127.0.0.1")
        self.assertEqual(db_settings["NAME"], "portal_db")
        self.assertEqual(db_settings["USER"], "portal_user")
        self.assertEqual(db_settings["PORT"], "5433")

    def test_sql_registry_get_sql(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            query_path = base_dir / "query.sql"
            query_path.write_text("select 1;", encoding="utf-8")
            registry = SQLRegistry({"ping": "query.sql"}, base_dir)
            sql_text = registry.get_sql("ping")
            self.assertEqual(sql_text, "select 1;")
            self.assertIn("ping", registry._cache)

    def test_portal_config_info_command(self):
        fixture_path = Path(__file__).parent / "fixtures" / "portal_config.yml"
        os.environ.update(
            {
                "PORTAL_CONFIG_PATH": str(fixture_path),
                "PORTAL_PROFILE": "dev",
                "PORTAL_DB_NAME": "portal_db",
                "PORTAL_DB_USER": "portal_user",
                "PORTAL_DB_PASSWORD": "portal_pass",
                "PORTAL_DB_HOST": "127.0.0.1",
                "PORTAL_DB_PORT": "5432",
            }
        )
        buffer = io.StringIO()
        call_command("portal_config_info", stdout=buffer)
        output = buffer.getvalue()
        self.assertIn("Active profile: dev", output)
        self.assertIn("Portal DB host: 127.0.0.1", output)
        self.assertIn("Portal DB name: portal_db", output)
        self.assertIn("Portal DB user: portal_user", output)
        self.assertIn("SQL base dir:", output)
        self.assertNotIn("portal_pass", output)
