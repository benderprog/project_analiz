import os
from pathlib import Path

from apps.portaldb.portal_config import (
    PROJECT_ROOT,
    expand_env_vars,
    get_active_profile,
    load_portal_config,
)


def _project_root_path(project_root=None):
    return Path(project_root) if project_root else PROJECT_ROOT


def _resolve_base_dir(base_dir, project_root=None):
    if not base_dir:
        return None
    base_path = Path(base_dir).expanduser()
    root = _project_root_path(project_root)
    if not base_path.is_absolute():
        base_path = root / base_path
    return base_path.resolve()


def _default_fallback_dirs(project_root=None):
    root = _project_root_path(project_root)
    return [
        (root / "configs" / "portal" / "sql").resolve(),
        (root / "apps" / "portaldb" / "sql").resolve(),
    ]


class SQLRegistry:
    def __init__(self, queries, base_dir, fallback_dirs=None, project_root=None):
        self.queries = queries or {}
        self.base_dir = _resolve_base_dir(base_dir, project_root=project_root)
        self.fallback_dirs = [
            Path(path).resolve()
            for path in (fallback_dirs or _default_fallback_dirs(project_root=project_root))
        ]
        self._cache = {}

    def _candidate_paths(self, query_name):
        relative_path = Path(self.queries[query_name])
        candidates = []
        if self.base_dir:
            candidates.append((self.base_dir / relative_path).resolve())
        for fallback in self.fallback_dirs:
            fallback_candidate = (fallback / relative_path).resolve()
            if fallback_candidate not in candidates:
                candidates.append(fallback_candidate)
        return candidates

    def _resolve_query_path(self, query_name):
        candidates = self._candidate_paths(query_name)
        for candidate in candidates:
            if candidate.exists():
                return candidate
        tried = ", ".join(str(path) for path in candidates)
        raise FileNotFoundError(
            f"SQL file for query '{query_name}' was not found. Tried: {tried}."
        )

    def get_sql(self, query_name):
        if query_name in self._cache:
            return self._cache[query_name]
        if query_name not in self.queries:
            raise KeyError(f"Query '{query_name}' is not registered.")

        query_path = self._resolve_query_path(query_name)
        sql_text = query_path.read_text(encoding="utf-8")
        self._cache[query_name] = sql_text
        return sql_text

    def count_missing_queries(self):
        missing = 0
        for query_name in self.queries:
            try:
                self._resolve_query_path(query_name)
            except FileNotFoundError:
                missing += 1
        return missing


def get_sql_registry(project_root=None):
    cfg, _, _ = load_portal_config(project_root=project_root)
    profile = expand_env_vars(get_active_profile(cfg))
    sql_cfg = profile.get("sql") or profile.get("sql_registry") or {}
    if not isinstance(sql_cfg, dict):
        raise ValueError("Active profile must define a 'sql' mapping.")

    base_dir = sql_cfg.get("base_dir")
    queries = sql_cfg.get("queries", {})
    if not isinstance(queries, dict):
        raise ValueError("'sql.queries' must be a mapping.")

    fallback_dirs = _default_fallback_dirs(project_root=project_root)
    return SQLRegistry(
        queries=queries,
        base_dir=base_dir,
        fallback_dirs=fallback_dirs,
        project_root=project_root,
    )
