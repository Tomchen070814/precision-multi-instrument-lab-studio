from __future__ import annotations

from collections.abc import Iterable, Mapping

CHANNEL_ORDER = ("A", "B", "C")


def resolve_channel_group(
    enabled_channels: Iterable[str],
    checked_channels: Mapping[str, bool],
) -> tuple[str, ...]:
    """Return a deterministic checked subset of currently enabled channels."""
    enabled = set(enabled_channels)
    return tuple(
        channel
        for channel in CHANNEL_ORDER
        if channel in enabled and bool(checked_channels.get(channel, False))
    )
