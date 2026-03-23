import io
import os
import tempfile
from unittest.mock import patch
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase

from apps.portaldb.portal_config import (
    apply_portal_database_settings,
    expand_env_vars,
    get_gateway_settings,
    load_yaml,
    resolve_portal_config_path,
)
from apps.portaldb.sql_registry import SQLRegistry, get_sql_registry


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

    def test_get_gateway_settings_defaults(self):
        settings_data = get_gateway_settings({})
        self.assertEqual(settings_data["backend"], "orm")
        self.assertEqual(settings_data["alias"], "portal")

    def test_apply_portal_database_settings_from_yaml(self):
        fixture_path = Path(__file__).parent / "fixtures" / "portal_config.yml"
        os.environ.update(
            {
                "PORTAL_PROFILE": "dev",
                "PORTAL_DB_NAME": "portal_db_test",
                "PORTAL_DB_USER": "portal_user",
                "PORTAL_DB_PASSWORD": "portal_pass",
                "PORTAL_DB_HOST": "127.0.0.1",
                "PORTAL_DB_PORT": "5433",
            }
        )
        cfg = load_yaml(fixture_path)
        db_settings = apply_portal_database_settings(globals(), cfg)
        self.assertEqual(db_settings["HOST"], "127.0.0.1")
        self.assertEqual(db_settings["NAME"], "portal_db_test")
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

    def test_default_config_path_prefers_configs_portal_yml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            configs_dir = root / "configs"
            configs_dir.mkdir(parents=True)
            preferred_nested = configs_dir / "portal" / "portal.yml"
            preferred = configs_dir / "portal.yml"
            fallback = configs_dir / "portal.example.yml"
            preferred_nested.parent.mkdir(parents=True)
            preferred_nested.write_text("profiles: {}\n", encoding="utf-8")
            preferred.write_text("profiles: {}\n", encoding="utf-8")
            fallback.write_text("profiles: {}\n", encoding="utf-8")

            os.environ.pop("PORTAL_CONFIG_PATH", None)
            resolved, warning = resolve_portal_config_path(project_root=root)

            self.assertEqual(resolved, preferred_nested.resolve())
            self.assertIsNone(warning)

    def test_sql_registry_resolves_configs_base_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sql_dir = root / "configs" / "portal" / "sql" / "pu"
            sql_dir.mkdir(parents=True)
            query_path = sql_dir / "list_pus.sql"
            query_path.write_text("select pu_id from pu;", encoding="utf-8")

            registry = SQLRegistry(
                queries={"list_pus": "pu/list_pus.sql"},
                base_dir="configs/portal/sql",
                fallback_dirs=[],
                project_root=root,
            )

            self.assertIn("select pu_id", registry.get_sql("list_pus"))

    def test_sql_registry_uses_portal_config_dir_as_base(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            old_sql_dir = root / "configs" / "portal" / "sql" / "pu"
            old_sql_dir.mkdir(parents=True)
            query_path = old_sql_dir / "list_pus.sql"
            query_path.write_text("select preferred from pu;", encoding="utf-8")

            registry = SQLRegistry(
                queries={"list_pus": "pu/list_pus.sql"},
                base_dir=str(root / "configs" / "portal" / "sql"),
                fallback_dirs=[],
                project_root=root,
                profile="dev",
            )

            self.assertIn("select preferred", registry.get_sql("list_pus"))

    def test_portal_config_info_command(self):
        fixture_path = Path(__file__).parent / "fixtures" / "portal_config.yml"
        os.environ.update(
            {
                "PORTAL_CONFIG_PATH": str(fixture_path),
                "PORTAL_PROFILE": "dev",
                "PORTAL_DB_NAME": "portal_db_test",
                "PORTAL_DB_USER": "portal_user",
                "PORTAL_DB_PASSWORD": "portal_pass",
                "PORTAL_DB_HOST": "127.0.0.1",
                "PORTAL_DB_PORT": "5432",
            }
        )
        buffer = io.StringIO()
        call_command("portal_config_info", stdout=buffer)
        output = buffer.getvalue()
        self.assertIn("Resolved config path:", output)
        self.assertIn("Active profile: dev", output)
        self.assertIn("Portal DB host: 127.0.0.1", output)
        self.assertIn("Portal DB name: portal_db_test", output)
        self.assertIn("Portal DB user: portal_user", output)
        self.assertIn("Resolved SQL base dir:", output)
        self.assertIn("SQL missing files:", output)
        self.assertNotIn("portal_pass", output)


    def test_get_sql_registry_prod_ro_uses_sql_prod_ro_dir(self):
        project_root = Path(__file__).resolve().parents[1]
        env = {
            "PORTAL_CONFIG_PATH": "configs/portal/portal.yml",
            "PORTAL_PROFILE": "prod_ro",
            "PORTAL_DB_NAME": "portal_db_test",
            "PORTAL_DB_USER": "portal_user",
            "PORTAL_DB_PASSWORD": "portal_pass",
            "PORTAL_DB_HOST": "127.0.0.1",
            "PORTAL_DB_PORT": "5432",
            "PORTAL_GATEWAY_BACKEND": "sql",
        }

        with patch.dict(os.environ, env, clear=False):
            registry = get_sql_registry(project_root=project_root)

        self.assertEqual(registry.base_dir, (project_root / "configs" / "portal" / "sql_prod_ro").resolve())
        self.assertEqual(registry.count_missing_queries(), 0)
        resolved = registry._resolve_query_path("list_pus")
        self.assertIn("configs/portal/sql_prod_ro", str(resolved))
