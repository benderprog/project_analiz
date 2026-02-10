import os

from django.core.management.base import BaseCommand, CommandError

from apps.portaldb.portal_config import (
    apply_portal_database_settings,
    expand_env_vars,
    get_active_profile,
    load_yaml,
)
from apps.portaldb.sql_registry import SQLRegistry


class Command(BaseCommand):
    help = "Display active portal config profile and SQL registry details."

    def handle(self, *args, **options):
        portal_config_path = os.getenv("PORTAL_CONFIG_PATH")
        if not portal_config_path:
            raise CommandError("PORTAL_CONFIG_PATH is not set.")

        try:
            cfg = load_yaml(portal_config_path)
            profile = get_active_profile(cfg)
            expanded_profile = expand_env_vars(profile)
            db_settings = apply_portal_database_settings(globals(), cfg)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        sql_registry_cfg = expanded_profile.get("sql_registry", {})
        queries = sql_registry_cfg.get("queries", {}) if isinstance(sql_registry_cfg, dict) else {}
        base_dir = sql_registry_cfg.get("base_dir") if isinstance(sql_registry_cfg, dict) else None
        registry = SQLRegistry(queries, base_dir)

        self.stdout.write(f"Active profile: {os.getenv('PORTAL_PROFILE')}")
        self.stdout.write(f"Portal DB host: {db_settings['HOST']}")
        self.stdout.write(f"Portal DB name: {db_settings['NAME']}")
        self.stdout.write(f"Portal DB user: {db_settings['USER']}")
        self.stdout.write(f"SQL base dir: {registry.base_dir or ''}")
        self.stdout.write(f"SQL queries loaded: {len(registry.queries)}")
