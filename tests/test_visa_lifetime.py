import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from hp3458a_studio.visa_lifetime import acquire_visa_manager


class _Manager:
    def __init__(self):
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


def test_concurrent_manager_users_close_only_after_every_owner_releases():
    manager = _Manager()
    acquired = threading.Barrier(9)
    release = threading.Barrier(9)

    def use_manager():
        lease = acquire_visa_manager(lambda: manager)
        try:
            acquired.wait(timeout=2)
            release.wait(timeout=2)
        finally:
            lease.close()
            lease.close()  # Repeated disconnect must not release another user.

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(use_manager) for _ in range(8)]
        acquired.wait(timeout=2)
        assert manager.close_calls == 0
        release.wait(timeout=2)
        for future in futures:
            future.result(timeout=2)
    assert manager.close_calls == 1


def test_final_close_failure_does_not_leave_a_stale_manager_owner():
    class FailingCloseManager(_Manager):
        def close(self):
            super().close()
            raise RuntimeError("VISA close failed")

    manager = FailingCloseManager()
    lease = acquire_visa_manager(lambda: manager)
    with pytest.raises(RuntimeError, match="VISA close failed"):
        lease.close()
    lease.close()
    assert manager.close_calls == 1

    another_lease = acquire_visa_manager(lambda: manager)
    with pytest.raises(RuntimeError, match="VISA close failed"):
        another_lease.close()
    assert manager.close_calls == 2
