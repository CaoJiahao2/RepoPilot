from app import first_nonempty


def test_default_is_returned():
    assert first_nonempty([], "") == ""
