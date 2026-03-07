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
    assert os.environ['OMP_NUM_THREADS'] == '1'
    assert os.environ['WORKER_THREADS_PER_CHILD'] == '1'


def test_apply_worker_thread_env_sets_expected_variables(monkeypatch) -> None:
    from scripts import run_celery_worker

    for name in run_celery_worker.THREAD_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv('TOKENIZERS_PARALLELISM', raising=False)
    monkeypatch.delenv('WORKER_THREADS_PER_CHILD', raising=False)
    monkeypatch.delenv('PYTORCH_NUM_THREADS', raising=False)

    run_celery_worker._apply_worker_thread_env(3)

    for name in run_celery_worker.THREAD_ENV_VARS:
        assert os.environ[name] == '3'
    assert os.environ['TOKENIZERS_PARALLELISM'] == 'false'
    assert os.environ['WORKER_THREADS_PER_CHILD'] == '3'
    assert os.environ['PYTORCH_NUM_THREADS'] == '3'
