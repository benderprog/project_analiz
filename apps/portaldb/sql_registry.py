from pathlib import Path


class SQLRegistry:
    def __init__(self, queries, base_dir):
        self.queries = queries or {}
        self.base_dir = Path(base_dir) if base_dir else None
        self._cache = {}

    def get_sql(self, query_name):
        if query_name in self._cache:
            return self._cache[query_name]
        if query_name not in self.queries:
            raise KeyError(f"Query '{query_name}' is not registered.")
        if not self.base_dir:
            raise ValueError("SQL registry base_dir is not configured.")
        query_path = self.base_dir / self.queries[query_name]
        sql_text = query_path.read_text(encoding="utf-8")
        self._cache[query_name] = sql_text
        return sql_text
