import pytest

from app.demo_keon import DemoKeonWorld


def test_world_starts_with_demopho_and_stick_figure_characters() -> None:
    world = DemoKeonWorld()

    assert [character.name for character in world.characters] == [
        "Keon",
        "Mavi",
        "DemoPHO",
    ]


def test_characters_can_be_added_and_join_conversations() -> None:
    world = DemoKeonWorld()

    added = world.add_character()
    dialogue = world.next_conversation()

    assert added.name == "Çöp Adam 4"
    assert len(world.characters) == 4
    assert all(line.speaker in {character.name for character in world.characters} for line in dialogue)


def test_demopho_replies_locally_and_rejects_empty_messages() -> None:
    world = DemoKeonWorld()

    assert world.reply_to_user("Merhaba").speaker == "DemoPHO"
    assert "çevrimdışı" in world.reply_to_user("Nasılsın?").text

    with pytest.raises(ValueError, match="boş"):
        world.reply_to_user("   ")
