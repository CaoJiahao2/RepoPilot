from app import format_name


def test_names_are_space_separated():
    assert format_name("Ada", "Lovelace") == "Ada Lovelace"
