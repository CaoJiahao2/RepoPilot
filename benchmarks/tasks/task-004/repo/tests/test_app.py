from app import normalize_name


def test_whitespace_only_name_is_empty():
    assert normalize_name("   ") == ""
