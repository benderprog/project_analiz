from __future__ import annotations

from pathlib import Path

from django.test import SimpleTestCase


class NoDirectPortalUsingTests(SimpleTestCase):
    def test_no_direct_portal_using_outside_gateway_or_repository(self):
        root = Path(__file__).resolve().parents[1]
        apps_dir = root / "apps"
        forbidden = [".using(\"portal\")", ".using(settings.PORTAL_DB_ALIAS)"]
        allowed_scopes = [
            str((apps_dir / "portaldb" / "gateway").resolve()),
            str((apps_dir / "portaldb" / "repository.py").resolve()),
        ]

        violations: list[str] = []
        for path in apps_dir.rglob("*.py"):
            resolved = str(path.resolve())
            if any(resolved.startswith(scope) for scope in allowed_scopes):
                continue
            text = path.read_text(encoding="utf-8")
            for needle in forbidden:
                if needle in text:
                    violations.append(f"{path}: {needle}")

        self.assertEqual(violations, [], msg="\n".join(violations))
