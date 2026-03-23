#!/usr/bin/env python
import logging
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from config.worker_autolimits import (
    build_celery_command,
    compute_worker_limits,
    get_cpu_available,
    get_mem_available_bytes,
    log_worker_limits,
)

THREAD_ENV_VARS = (
    'OMP_NUM_THREADS',
    'MKL_NUM_THREADS',
    'OPENBLAS_NUM_THREADS',
    'NUMEXPR_NUM_THREADS',
    'VECLIB_MAXIMUM_THREADS',
)


def _apply_worker_thread_env(threads_per_child: int) -> None:
    thread_count = str(threads_per_child)
    for name in THREAD_ENV_VARS:
        os.environ[name] = thread_count
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    os.environ['WORKER_THREADS_PER_CHILD'] = thread_count
    os.environ['PYTORCH_NUM_THREADS'] = thread_count


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    return int(value)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')

    cpu_available = get_cpu_available()
    mem_available_bytes = get_mem_available_bytes()
    limits = compute_worker_limits(
        cpu_available=cpu_available,
        mem_available_bytes=mem_available_bytes,
        max_concurrency=_env_int('WORKER_MAX_CONCURRENCY', 8),
        safety_margin_kb=_env_int('WORKER_MEMORY_SAFETY_MARGIN_KB', 200_000),
    )
    log_worker_limits(limits)
    _apply_worker_thread_env(limits.threads_per_child)

    command = build_celery_command(
        limits,
        app=os.getenv('WORKER_CELERY_APP', 'config'),
        log_level=os.getenv('WORKER_LOG_LEVEL', 'INFO'),
        queue=os.getenv('WORKER_QUEUE', 'analysis'),
        max_tasks_per_child=_env_int('WORKER_MAX_TASKS_PER_CHILD', 50),
        soft_time_limit=_env_int('WORKER_SOFT_TIME_LIMIT', 1800),
        time_limit=_env_int('WORKER_TIME_LIMIT', 1860),
    )

    logging.getLogger(__name__).info('Starting Celery with computed command: %s', ' '.join(command))
    os.execvp(command[0], command)


if __name__ == '__main__':
    main()
