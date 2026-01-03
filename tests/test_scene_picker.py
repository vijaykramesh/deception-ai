import pytest

from app.agents.scene_picker import ScenePickError, parse_picked_scene


def test_parse_picked_scene_accepts_canonical_keys() -> None:
    picked = parse_picked_scene('{"location": "location__kitchen", "cause": "cause-of-death__poisoning"}')
    assert picked.location == "location__kitchen"
    assert picked.cause == "cause-of-death__poisoning"


def test_parse_picked_scene_accepts_variant_keys() -> None:
    picked = parse_picked_scene('{"location_id": "location__kitchen", "cause_id": "cause-of-death__stabbing"}')
    assert picked.location == "location__kitchen"
    assert picked.cause == "cause-of-death__stabbing"


@pytest.mark.parametrize("bad", ["not json", "[]", "{}", '{"location": "", "cause": "x"}', '{"location": "x", "cause": ""}'])
def test_parse_picked_scene_rejects_invalid(bad: str) -> None:
    with pytest.raises(ScenePickError):
        parse_picked_scene(bad)

