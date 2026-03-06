import logging
import os


def configure_torch_threads() -> None:
    value = os.getenv('WORKER_THREADS_PER_CHILD')
    if not value:
        return

    try:
        threads_per_child = max(1, int(value))
    except ValueError:
        logging.getLogger(__name__).warning(
            'Invalid WORKER_THREADS_PER_CHILD value %r; skipping torch thread configuration',
            value,
        )
        return

    try:
        import torch
    except Exception:  # pragma: no cover - optional dependency
        return

    try:
        torch.set_num_threads(threads_per_child)
        torch.set_num_interop_threads(1)
        logging.getLogger(__name__).info(
            'Configured torch thread limits: num_threads=%d num_interop_threads=1',
            threads_per_child,
        )
    except Exception:
        logging.getLogger(__name__).exception('Failed to configure torch thread limits')
