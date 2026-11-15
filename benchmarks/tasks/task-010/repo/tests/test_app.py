from app import repeat_text


def test_text_repeats_requested_count():
    assert repeat_text("ab", 3) == "ababab"
