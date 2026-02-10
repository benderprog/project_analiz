import os

from django.core.management.base import BaseCommand, CommandError

from apps.portaldb.portal_config import (
    apply_portal_database_settings,
    expand_env_vars,
    get_active_profile,
    load_portal_config,
)
from apps.portaldb.sql_registry import SQLRegistry, _default_fallback_dirs


class Command(BaseCommand):
    help = "Display active portal config profile and SQL registry details."

    def handle(self, *args, **options):
        try:
            cfg, config_path, warning = load_portal_config()
            profile = get_active_profile(cfg)
            expanded_profile = expand_env_vars(profile)
            db_settings = apply_portal_database_settings(globals(), cfg)
        except (ValueError, FileNotFoundError) as exc:
            raise CommandError(str(exc)) from exc

        sql_cfg = expanded_profile.get("sql") or expanded_profile.get("sql_registry") or {}
        queries = sql_cfg.get("queries", {}) if isinstance(sql_cfg, dict) else {}
        base_dir = sql_cfg.get("base_dir") if isinstance(sql_cfg, dict) else None
        registry = SQLRegistry(queries, base_dir, fallback_dirs=_default_fallback_dirs())

        if warning:
            self.stdout.write(f"Warning: {warning}")
        self.stdout.write(f"Resolved config path: {config_path}")
        self.stdout.write(f"Active profile: {os.getenv('PORTAL_PROFILE')}")
        self.stdout.write(f"Portal DB host: {db_settings['HOST']}")
        self.stdout.write(f"Portal DB name: {db_settings['NAME']}")
        self.stdout.write(f"Portal DB user: {db_settings['USER']}")
        self.stdout.write(f"Resolved SQL base dir: {registry.base_dir or ''}")
        self.stdout.write(f"SQL queries loaded: {len(registry.queries)}")
        self.stdout.write(f"SQL missing files: {registry.count_missing_queries()}")
