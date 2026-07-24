from hp3458a_studio.channel_groups import resolve_channel_group


def test_resolves_any_two_channel_pair_in_stable_order():
    enabled = ("A", "B", "C")
    assert resolve_channel_group(enabled, {"A": True, "B": False, "C": True}) == (
        "A",
        "C",
    )
    assert resolve_channel_group(enabled, {"A": False, "B": True, "C": True}) == (
        "B",
        "C",
    )


def test_disabled_channel_is_never_returned_even_if_still_checked():
    assert resolve_channel_group(("A", "B"), {"A": True, "B": False, "C": True}) == (
        "A",
    )


def test_single_and_empty_group_are_supported():
    assert resolve_channel_group(("A", "B", "C"), {"C": True}) == ("C",)
    assert resolve_channel_group(("A", "B"), {}) == ()
