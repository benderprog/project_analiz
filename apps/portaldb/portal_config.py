import os
import re
from pathlib import Path

import yaml

ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def load_yaml(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("Portal config must be a YAML mapping at the root level.")
    return data


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


def _expand_env_in_string(value):
    def replace(match):
        var_name = match.group(1)
        env_value = os.getenv(var_name)
        if env_value is None:
            raise ValueError(f"Missing environment variable '{var_name}'.")
        return env_value

    return ENV_VAR_PATTERN.sub(replace, value)
