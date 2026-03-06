from pathlib import Path

from config.worker_autolimits import (
    CGROUP_V2_CPU_MAX,
    CGROUP_V2_MEMORY_MAX,
    MEMINFO_PATH,
    CPU_V1_PERIOD_PATHS,
    CPU_V1_QUOTA_PATHS,
    MEMORY_V1_LIMIT_PATHS,
    compute_worker_limits,
    get_cpu_available,
    get_mem_available_bytes,
    log_worker_limits,
)


def _fake_fs_reader(data: dict[Path, str]):
    def _exists(path: Path) -> bool:
        return path in data

    def _read(path: Path) -> str:
        return data[path]

    return _exists, _read


def test_cgroup_v2_limits_are_used_for_cpu_and_memory() -> None:
    data = {
        CGROUP_V2_CPU_MAX: '200000 100000',
        CGROUP_V2_MEMORY_MAX: str(2 * 1024 * 1024 * 1024),
        MEMINFO_PATH: 'MemTotal:       16384000 kB\n',
    }
    exists, read_text = _fake_fs_reader(data)

    cpu_available = get_cpu_available(exists=exists, read_text=read_text, cpu_count=16)
    mem_available = get_mem_available_bytes(exists=exists, read_text=read_text)
    limits = compute_worker_limits(cpu_available=cpu_available, mem_available_bytes=mem_available)

    assert cpu_available == 2.0
    assert mem_available == 2 * 1024 * 1024 * 1024
    assert limits.concurrency == 1
    assert limits.threads_per_child == 1
    assert limits.max_memory_per_child_kb == 1477721


def test_cgroup_v1_falls_back_to_host_when_unlimited() -> None:
    data = {
        CPU_V1_QUOTA_PATHS[0]: '-1',
        CPU_V1_PERIOD_PATHS[0]: '100000',
        MEMORY_V1_LIMIT_PATHS[0]: str(1 << 62),
        MEMINFO_PATH: 'MemTotal:       8192000 kB\n',
    }
    exists, read_text = _fake_fs_reader(data)

    cpu_available = get_cpu_available(exists=exists, read_text=read_text, cpu_count=10)
    mem_available = get_mem_available_bytes(exists=exists, read_text=read_text)
    limits = compute_worker_limits(cpu_available=cpu_available, mem_available_bytes=mem_available)

    assert cpu_available == 10.0
    assert mem_available == 8192000 * 1024
    assert limits.concurrency == 8
    assert limits.threads_per_child == 1
    assert limits.max_memory_per_child_kb == 619200


def test_log_worker_limits_smoke(caplog) -> None:
    limits = compute_worker_limits(cpu_available=4.0, mem_available_bytes=4 * 1024 * 1024 * 1024)

    with caplog.at_level('INFO'):
        log_worker_limits(limits)

    assert 'cpu_available=4.000' in caplog.text
    assert 'computed_concurrency=3' in caplog.text
    assert 'threads_per_child=1' in caplog.text
    assert 'computed_max_memory_per_child_kb=918481' in caplog.text


def test_threads_per_child_uses_cpu_budget_split() -> None:
    limits = compute_worker_limits(cpu_available=32.0, mem_available_bytes=16 * 1024 * 1024 * 1024)

    assert limits.concurrency == 8
    assert limits.threads_per_child == 3
