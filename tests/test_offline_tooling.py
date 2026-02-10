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
