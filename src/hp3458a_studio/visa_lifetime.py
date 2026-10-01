"""Share ownership of PyVISA's cached resource manager across channels.

PyVISA returns the same manager for a VISA library, even when callers use
different backend aliases. Closing that manager closes every session it opened,
so instrument workers and temporary scans must release leases instead.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_MANAGER_GUARD = threading.RLock()


@dataclass
class _ManagerOwners:
    manager: Any
    users: int = 0


_MANAGERS: dict[int, _ManagerOwners] = {}


class VisaManagerLease:
    def __init__(self, manager: Any):
        self.manager = manager
        self._released = False

    def close(self) -> None:
        """Release this owner; only the final owner closes the manager."""
        with _MANAGER_GUARD:
            if self._released:
                return
            self._released = True
            key = id(self.manager)
            owners = _MANAGERS[key]
            owners.users -= 1
            if owners.users == 0:
                # Keep acquisition excluded until close finishes so a new
                # caller cannot obtain the manager that is being shut down.
                try:
                    owners.manager.close()
                finally:
                    del _MANAGERS[key]

    def __enter__(self) -> Any:
        return self.manager

    def __exit__(self, *_exc_info) -> None:
        self.close()


def acquire_visa_manager(factory: Callable[[], Any]) -> VisaManagerLease:
    """Acquire a manager from PyVISA or an injected factory atomically.

    Key by the returned object, rather than backend text: PyVISA can resolve
    several backend strings to the same cached manager.
    """
    with _MANAGER_GUARD:
        manager = factory()
        owners = _MANAGERS.setdefault(id(manager), _ManagerOwners(manager))
        owners.users += 1
        return VisaManagerLease(manager)
