import json
import os
import shutil
import subprocess
from pathlib import Path


def test_portal_offline_config_exists():
    assert Path("configs/portal.offline.yml").exists()


def test_make_release_bundle_creates_compose_env_and_manifest_entry(tmp_path):
    version = "test_bundle_assets"
    version_slug = version.replace('.', '_')
    bundle_dir = Path("dist") / f"release_ver_{version_slug}"

    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)

    env = {**os.environ, "PATH": os.environ.get("PATH", "")}
    result = subprocess.run(
        [
            "bash",
            "scripts/make_release_bundle.sh",
            "--version",
            version,
            "--skip-image-export",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr

    compose_env = bundle_dir / "compose" / ".env.docker"
    assert compose_env.exists()

    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest_paths = {entry["path"] for entry in manifest["files"]}
    assert "compose/.env.docker" in manifest_paths


def test_offline_compose_uses_versioned_web_image_without_build():
    offline_compose = Path("docker-compose.offline.yml").read_text(encoding="utf-8")

    assert "image: project_analiz:web-ver-${VERSION}" in offline_compose
    assert "build:" not in offline_compose


def test_make_release_bundle_writes_version_to_compose_env(tmp_path):
    version = "test_bundle_version_env"
    version_slug = version.replace('.', '_')
    bundle_dir = Path("dist") / f"release_ver_{version_slug}"

    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)

    env = {**os.environ, "PATH": os.environ.get("PATH", "")}
    result = subprocess.run(
        [
            "bash",
            "scripts/make_release_bundle.sh",
            "--version",
            version,
            "--skip-image-export",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr

    compose_env = bundle_dir / "compose" / ".env.docker"
    env_text = compose_env.read_text(encoding="utf-8")
    assert f"VERSION={version}" in env_text
