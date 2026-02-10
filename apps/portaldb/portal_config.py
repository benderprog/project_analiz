import os
import re
from pathlib import Path

import yaml

ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("Portal config must be a YAML mapping at the root level.")
    return data


def resolve_portal_config_path(project_root=None):
    root = Path(project_root) if project_root else PROJECT_ROOT
    env_path = os.getenv("PORTAL_CONFIG_PATH")
    if env_path:
        path = Path(env_path).expanduser()
        if not path.is_absolute():
            path = root / path
        if not path.exists():
            raise FileNotFoundError(f"Portal config not found at {path.resolve()}.")
        return path.resolve(), None

    preferred = root / "configs" / "portal.yml"
    example = root / "configs" / "portal.example.yml"
    if preferred.exists():
        return preferred.resolve(), None
    if example.exists():
        warning = (
            "PORTAL_CONFIG_PATH is not set. Falling back to configs/portal.example.yml; "
            "create configs/portal.yml for local development."
        )
        return example.resolve(), warning

    raise FileNotFoundError(
        "Portal config not found. Tried: "
        f"{preferred.resolve()} and {example.resolve()}."
    )


def load_portal_config(project_root=None):
    config_path, warning = resolve_portal_config_path(project_root=project_root)
    return load_yaml(config_path), config_path, warning


def expand_env_vars(obj):
    if isinstance(obj, dict):
        return {key: expand_env_vars(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [expand_env_vars(value) for value in obj]
    if isinstance(obj, str):
        return _expand_env_in_string(obj)
    return obj


def get_active_profile(cfg):
    profile_name = os.getenv("PORTAL_PROFILE")
    if not profile_name:
        raise ValueError("PORTAL_PROFILE is not set.")
    profiles = cfg.get("profiles")
    if not isinstance(profiles, dict):
        raise ValueError("Portal config must define a 'profiles' mapping.")
    if profile_name not in profiles:
        available = ", ".join(sorted(profiles))
        raise ValueError(
            f"Profile '{profile_name}' not found. Available profiles: {available}."
        )
    return profiles[profile_name]


def apply_portal_database_settings(settings_module, cfg):
    profile = expand_env_vars(get_active_profile(cfg))
    db_config = profile.get("database")
    if not isinstance(db_config, dict):
        raise ValueError("Active profile must define a 'database' mapping.")
    engine = db_config.get("engine", "django.db.backends.postgresql")
    required = ["name", "user", "password", "host", "port"]
    missing = [key for key in required if not db_config.get(key)]
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"Portal database config missing values: {missing_list}.")
    return {
        "ENGINE": engine,
        "NAME": db_config["name"],
        "USER": db_config["user"],
        "PASSWORD": db_config["password"],
        "HOST": db_config["host"],
        "PORT": str(db_config["port"]),
    }


def get_gateway_settings(cfg):
    gateway_cfg = cfg.get("gateway") or {}
    if not isinstance(gateway_cfg, dict):
        raise ValueError("Portal config 'gateway' must be a mapping.")

    expanded = dict(gateway_cfg)
    backend_raw = expanded.get("backend", "orm")
    if isinstance(backend_raw, str) and backend_raw == "${PORTAL_GATEWAY_BACKEND}":
        backend_raw = os.getenv("PORTAL_GATEWAY_BACKEND", "orm")
    else:
        backend_raw = expand_env_vars(backend_raw)
    backend = str(backend_raw).strip().lower() or "orm"
    if backend not in {"orm", "sql"}:
        raise ValueError("Portal gateway backend must be either 'orm' or 'sql'.")

    alias = str(expand_env_vars(expanded.get("alias", "portal"))).strip() or "portal"
    return {"backend": backend, "alias": alias}


def _expand_env_in_string(value):
    def replace(match):
        var_name = match.group(1)
        env_value = os.getenv(var_name)
        if env_value is None:
            raise ValueError(f"Missing environment variable '{var_name}'.")
        return env_value

    return ENV_VAR_PATTERN.sub(replace, value)
