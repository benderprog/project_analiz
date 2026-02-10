from pathlib import Path
import os
import stat
import subprocess


def test_portal_offline_config_exists():
    assert Path("configs/portal.offline.yml").exists()


def test_release_builder_is_executable():
    script = Path("scripts/release/build_release.sh")
    mode = script.stat().st_mode
    assert mode & stat.S_IXUSR


def test_release_builder_requires_fixture_flags_or_env():
    script = Path("scripts/release/build_release.sh")

    result = subprocess.run(
        ["bash", str(script), "1.5_test"],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": os.environ.get("PATH", "")},
    )

    assert result.returncode == 1
    assert "Missing fixture XLSX. Provide --xlsx or set FIXTURE_XLSX" in result.stderr
