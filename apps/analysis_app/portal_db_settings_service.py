import os


def _env_or_fallback(primary: str, fallback: str) -> str:
    return os.getenv(primary) or os.getenv(fallback, "")


def get_test_portal_db_params() -> dict:
    return {
        "host": _env_or_fallback("PORTAL_DB_TEST_HOST", "PORTAL_DB_HOST"),
        "port": int(_env_or_fallback("PORTAL_DB_TEST_PORT", "PORTAL_DB_PORT") or 5432),
        "db_name": _env_or_fallback("PORTAL_DB_TEST_NAME", "PORTAL_DB_NAME"),
        "user": _env_or_fallback("PORTAL_DB_TEST_USER", "PORTAL_DB_USER"),
        "password": _env_or_fallback("PORTAL_DB_TEST_PASSWORD", "PORTAL_DB_PASSWORD"),
    }
