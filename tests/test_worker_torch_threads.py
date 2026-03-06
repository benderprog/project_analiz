import sys

from config.worker_torch_threads import configure_torch_threads


class _TorchStub:
    def __init__(self):
        self.num_threads = None
        self.interop_threads = None

    def set_num_threads(self, value):
        self.num_threads = value

    def set_num_interop_threads(self, value):
        self.interop_threads = value


def test_configure_torch_threads_sets_values(monkeypatch):
    stub = _TorchStub()
    monkeypatch.setenv('WORKER_THREADS_PER_CHILD', '4')
    monkeypatch.setitem(sys.modules, 'torch', stub)

    configure_torch_threads()

    assert stub.num_threads == 4
    assert stub.interop_threads == 1


def test_configure_torch_threads_skips_on_invalid_value(monkeypatch):
    monkeypatch.setenv('WORKER_THREADS_PER_CHILD', 'bad')

    configure_torch_threads()


def test_configure_torch_threads_skips_when_missing(monkeypatch):
    monkeypatch.delenv('WORKER_THREADS_PER_CHILD', raising=False)

    configure_torch_threads()


def test_configure_torch_threads_skips_without_torch(monkeypatch):
    monkeypatch.setenv('WORKER_THREADS_PER_CHILD', '2')
    monkeypatch.delitem(sys.modules, 'torch', raising=False)

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == 'torch':
            raise ModuleNotFoundError('no torch')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr('builtins.__import__', fake_import)

    configure_torch_threads()
