from __future__ import annotations

from types import SimpleNamespace
from threading import Event, Thread
from uuid import uuid4

from app.core import distributed_state as distributed_state_module
from app.core.distributed_state import HybridLock
from app.strategies.runner import _torum_v1_symbol_lock


def _single_worker_settings() -> SimpleNamespace:
    return SimpleNamespace(enforce_single_worker=True)


def test_hybrid_lock_shared_handle_keeps_ownership_isolated_per_thread(monkeypatch) -> None:
    monkeypatch.setattr(distributed_state_module, "get_settings", _single_worker_settings)
    key = f"test:{uuid4().hex}"
    owner = HybridLock(key)
    contender = HybridLock(key)

    assert owner.acquire(timeout=0.05) is True
    assert contender.acquire(timeout=0.01) is False

    owner.release()
    assert contender.acquire(timeout=0.05) is True
    contender.release()

    probe = HybridLock(key)
    assert probe.acquire(timeout=0.05) is True
    probe.release()



def test_shared_hybrid_lock_waiter_releases_its_own_acquisition(monkeypatch) -> None:
    monkeypatch.setattr(distributed_state_module, "get_settings", _single_worker_settings)
    key = f"test:{uuid4().hex}"
    shared = HybridLock(key)
    owner_acquired = Event()
    release_owner = Event()
    contender_acquired = Event()
    release_contender = Event()
    outcomes: list[bool] = []

    def owner() -> None:
        outcomes.append(shared.acquire(timeout=0.5))
        owner_acquired.set()
        release_owner.wait(1.0)
        shared.release()

    def contender() -> None:
        owner_acquired.wait(1.0)
        outcomes.append(shared.acquire(timeout=1.0))
        contender_acquired.set()
        release_contender.wait(1.0)
        shared.release()

    owner_thread = Thread(target=owner)
    contender_thread = Thread(target=contender)
    owner_thread.start()
    contender_thread.start()
    assert owner_acquired.wait(1.0) is True
    release_owner.set()
    assert contender_acquired.wait(1.0) is True

    probe = HybridLock(key)
    assert probe.acquire(timeout=0.01) is False
    release_contender.set()
    owner_thread.join(1.0)
    contender_thread.join(1.0)

    assert outcomes == [True, True]
    assert probe.acquire(timeout=0.1) is True
    probe.release()

def test_torum_symbol_lock_returns_independent_acquisition_handles(monkeypatch) -> None:
    monkeypatch.setattr(distributed_state_module, "get_settings", _single_worker_settings)
    symbol = f"TEST_{uuid4().hex}"
    first = _torum_v1_symbol_lock(symbol)
    second = _torum_v1_symbol_lock(symbol)

    assert first is not second
    assert first.key == second.key
    assert first.acquire(timeout=0.05) is True
    assert second.acquire(timeout=0.01) is False

    first.release()
    assert second.acquire(timeout=0.05) is True
    second.release()
