import os
from pathlib import Path


def test_import_sets_defaults_and_repo_root_on_path() -> None:
    import importlib
    import sys

    os.environ.pop('DJANGO_SETTINGS_MODULE', None)
    module = importlib.import_module('scripts.run_celery_worker')

    assert os.environ['DJANGO_SETTINGS_MODULE'] == 'config.settings'
    repo_root = str(Path(module.__file__).resolve().parents[1])
    assert repo_root in sys.path


def test_main_smoke_logs_limits_without_import_error(monkeypatch, caplog) -> None:
    from scripts import run_celery_worker

    monkeypatch.setattr(run_celery_worker, 'get_cpu_available', lambda: 4.0)
    monkeypatch.setattr(run_celery_worker, 'get_mem_available_bytes', lambda: 2 * 1024 * 1024 * 1024)

    called = {}

    def _fake_execvp(file: str, args: list[str]) -> None:
        called['file'] = file
        called['args'] = args
        raise SystemExit(0)

    monkeypatch.setattr(run_celery_worker.os, 'execvp', _fake_execvp)

    with caplog.at_level('INFO'):
        try:
            run_celery_worker.main()
        except SystemExit:
            pass

    assert 'Worker auto-limits:' in caplog.text
    assert called['file'] == 'celery'
    assert called['args'][0] == 'celery'
