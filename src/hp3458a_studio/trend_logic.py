from __future__ import annotations


def assign_unit_axes(
    channel_units: dict[str, str],
    channel_order: tuple[str, ...] = ("A", "B", "C"),
) -> tuple[dict[str, int], dict[str, int]]:
    """Assign equal physical units to one axis and mixed units to new axes."""
    unit_slots: dict[str, int] = {}
    channel_slots: dict[str, int] = {}
    for channel in channel_order:
        unit = channel_units.get(channel)
        if unit is None:
            continue
        if unit not in unit_slots:
            if len(unit_slots) >= 3:
                raise ValueError("The trend plot supports at most three units")
            unit_slots[unit] = len(unit_slots)
        channel_slots[channel] = unit_slots[unit]
    return channel_slots, unit_slots
