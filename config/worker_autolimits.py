import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional


CGROUP_V2_CPU_MAX = Path('/sys/fs/cgroup/cpu.max')
CGROUP_V2_MEMORY_MAX = Path('/sys/fs/cgroup/memory.max')
MEMINFO_PATH = Path('/proc/meminfo')
CPU_V1_QUOTA_PATHS = (
    Path('/sys/fs/cgroup/cpu/cpu.cfs_quota_us'),
    Path('/sys/fs/cgroup/cpu.cfs_quota_us'),
)
CPU_V1_PERIOD_PATHS = (
    Path('/sys/fs/cgroup/cpu/cpu.cfs_period_us'),
    Path('/sys/fs/cgroup/cpu.cfs_period_us'),
)
MEMORY_V1_LIMIT_PATHS = (
    Path('/sys/fs/cgroup/memory/memory.limit_in_bytes'),
    Path('/sys/fs/cgroup/memory.limit_in_bytes'),
)
UNLIMITED_MEMORY_THRESHOLD_BYTES = 1 << 60
CPU_BUDGET_FACTOR = 0.8
MEMORY_BUDGET_FACTOR = 0.8


@dataclass(frozen=True)
class WorkerLimits:
    cpu_available: float
    mem_available_bytes: int
    concurrency: int
    threads_per_child: int
    max_memory_per_child_kb: int


def _default_exists(path: Path) -> bool:
    return path.exists()


def _default_read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8').strip()


def _read_first_existing(
    paths: Iterable[Path],
    *,
    exists: Callable[[Path], bool],
    read_text: Callable[[Path], str],
) -> Optional[str]:
    for path in paths:
        if exists(path):
            return read_text(path)
    return None


def parse_memtotal_bytes(meminfo_text: str) -> int:
    for line in meminfo_text.splitlines():
        if line.startswith('MemTotal:'):
            return int(line.split()[1]) * 1024
    raise ValueError('MemTotal not found in /proc/meminfo')


def get_cpu_available(
    *,
    exists: Callable[[Path], bool] = _default_exists,
    read_text: Callable[[Path], str] = _default_read_text,
    cpu_count: Optional[int] = None,
) -> float:
    host_cpu_count = cpu_count or os.cpu_count() or 1

    if exists(CGROUP_V2_CPU_MAX):
        quota, period = read_text(CGROUP_V2_CPU_MAX).split()
        if quota != 'max':
            return max(float(quota) / float(period), 1e-6)
        return float(host_cpu_count)

    quota_raw = _read_first_existing(CPU_V1_QUOTA_PATHS, exists=exists, read_text=read_text)
    period_raw = _read_first_existing(CPU_V1_PERIOD_PATHS, exists=exists, read_text=read_text)
    if quota_raw is not None and period_raw is not None:
        quota = int(quota_raw)
        period = int(period_raw)
        if quota > 0 and period > 0:
            return max(float(quota) / float(period), 1e-6)

    return float(host_cpu_count)


def get_mem_available_bytes(
    *,
    exists: Callable[[Path], bool] = _default_exists,
    read_text: Callable[[Path], str] = _default_read_text,
) -> int:
    host_mem_total = parse_memtotal_bytes(read_text(MEMINFO_PATH))

    if exists(CGROUP_V2_MEMORY_MAX):
        value = read_text(CGROUP_V2_MEMORY_MAX)
        if value != 'max':
            return int(value)
        return host_mem_total

    memory_limit_raw = _read_first_existing(MEMORY_V1_LIMIT_PATHS, exists=exists, read_text=read_text)
    if memory_limit_raw is not None:
        limit = int(memory_limit_raw)
        if 0 < limit < UNLIMITED_MEMORY_THRESHOLD_BYTES:
            return limit

    return host_mem_total


def compute_worker_limits(
    *,
    cpu_available: float,
    mem_available_bytes: int,
    max_concurrency: int = 8,
    safety_margin_kb: int = 200_000,
) -> WorkerLimits:
    cpu_budget = cpu_available * CPU_BUDGET_FACTOR
    concurrency = max(1, min(math.floor(cpu_budget), max_concurrency))
    threads_per_child = max(1, math.floor(cpu_budget / concurrency))

    mem_budget = int(mem_available_bytes * MEMORY_BUDGET_FACTOR)
    max_memory_per_child_kb = max(1, math.floor(mem_budget / concurrency / 1024) - safety_margin_kb)

    return WorkerLimits(
        cpu_available=cpu_available,
        mem_available_bytes=mem_available_bytes,
        concurrency=concurrency,
        threads_per_child=threads_per_child,
        max_memory_per_child_kb=max_memory_per_child_kb,
    )


def log_worker_limits(limits: WorkerLimits, *, logger: Optional[logging.Logger] = None) -> None:
    log = logger or logging.getLogger(__name__)
    log.info(
        'Worker auto-limits: cpu_available=%.3f mem_available_bytes=%d computed_concurrency=%d threads_per_child=%d computed_max_memory_per_child_kb=%d',
        limits.cpu_available,
        limits.mem_available_bytes,
        limits.concurrency,
        limits.threads_per_child,
        limits.max_memory_per_child_kb,
    )


def build_celery_command(
    limits: WorkerLimits,
    *,
    app: str,
    log_level: str,
    queue: str,
    max_tasks_per_child: int,
    soft_time_limit: int,
    time_limit: int,
) -> list[str]:
    return [
        'celery',
        '-A',
        app,
        'worker',
        '-l',
        log_level,
        '-Q',
        queue,
        f'--concurrency={limits.concurrency}',
        f'--max-memory-per-child={limits.max_memory_per_child_kb}',
        f'--max-tasks-per-child={max_tasks_per_child}',
        f'--soft-time-limit={soft_time_limit}',
        f'--time-limit={time_limit}',
        '--prefetch-multiplier=1',
    ]
