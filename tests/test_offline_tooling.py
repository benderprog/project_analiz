from pathlib import Path
import re
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_offline_compose_web_uses_image_without_build():
    compose_path = REPO_ROOT / "docker" / "offline" / "compose.yml"
    content = compose_path.read_text(encoding="utf-8")

    assert compose_path.exists()
    assert "image: project_analiz:web-ver-${VERSION}" in content

    web_match = re.search(r"\n  web:\n(.*?)(\n  [a-z_]+:|\nvolumes:)", content, re.DOTALL)
    assert web_match, "web service block not found"
    assert "build:" not in web_match.group(1)


def test_offline_compose_has_restore_services_and_portal_dump_name():
    compose_path = REPO_ROOT / "docker" / "offline" / "compose.yml"
    content = compose_path.read_text(encoding="utf-8")

    assert "restore_app:" in content
    assert "restore_portal:" in content
    assert "pg_restore -h db_app" in content
    assert "pg_restore -h portal_db_test" in content
    assert "/db_dumps/portal_db_test.dump" in content


def test_offline_compose_mounts_configs_directory_read_only():
    compose_path = REPO_ROOT / "docker" / "offline" / "compose.yml"
    content = compose_path.read_text(encoding="utf-8")

    assert "- ../configs:/app/configs:ro" in content


def test_offline_script_help():
    script_path = REPO_ROOT / "scripts" / "offline" / "offline.sh"
    result = subprocess.run(
        [str(script_path), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Offline bundle / runtime helper" in result.stdout
    assert "--db-app-dump" in result.stdout
    assert "restore" in result.stdout
    assert "ps" in result.stdout
    assert "logs" in result.stdout
    assert "--with-model" not in result.stdout



def test_offline_bundle_writes_portal_nested_config_and_sql_paths():
    script_path = REPO_ROOT / "scripts" / "offline" / "offline.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "portal/portal.yml" in content
    assert "configs/portal/sql" in content
    assert "configs/portal/sql_prod_ro" in content
    assert "PORTAL_CONFIG_PATH=/app/configs/portal.yml" in content


def test_offline_compose_db_services_use_named_volumes_for_persistence():
    compose_path = REPO_ROOT / "docker" / "offline" / "compose.yml"
    content = compose_path.read_text(encoding="utf-8")

    assert "db_app:" in content
    assert "portal_db_test:" in content
    assert "- app_db_data:/var/lib/postgresql/data" in content
    assert "- portal_db_data:/var/lib/postgresql/data" in content


def test_offline_script_has_idempotent_restore_and_reset_db_command():
    script_path = REPO_ROOT / "scripts" / "offline" / "offline.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "restore skipped, DB already initialized" in content
    assert "OFFLINE_RESTORE" in content
    assert "reset-db" in content
    assert "compose_cmd down --remove-orphans" in content


def test_offline_compose_web_worker_share_media_mount_and_no_version_key():
    compose_path = REPO_ROOT / "docker" / "offline" / "compose.yml"
    content = compose_path.read_text(encoding="utf-8")

    assert "version:" not in content
    assert "- ./media:/app/media" in content


def test_offline_compose_web_has_explicit_gunicorn_runtime_flags():
    compose_path = REPO_ROOT / "docker" / "offline" / "compose.yml"
    content = compose_path.read_text(encoding="utf-8")

    assert '"--timeout", "300"' in content
    assert '"--graceful-timeout", "30"' in content
    assert '"--access-logfile", "-"' in content
    assert '"--error-logfile", "-"' in content
    assert '"--log-level", "debug"' in content
    assert '"--capture-output"' in content


def test_offline_bundle_env_uses_django_debug_true_for_test_release():
    script_path = REPO_ROOT / "scripts" / "offline" / "offline.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "DJANGO_DEBUG=true" in content


def test_offline_script_prepares_shared_media_directory():
    script_path = REPO_ROOT / "scripts" / "offline" / "offline.sh"
    content = script_path.read_text(encoding="utf-8")

    assert '"${compose_dir}/media"' in content


def test_offline_bundle_requires_and_copies_semantic_model():
    script_path = REPO_ROOT / "scripts" / "offline" / "offline.sh"
    content = script_path.read_text(encoding="utf-8")

    assert "Required semantic model not found" in content
    assert "Copying local semantic model cache" in content
    assert "Required semantic model was not copied into bundle compose/models." in content
