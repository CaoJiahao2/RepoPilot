from app import safe_divide


def test_zero_denominator_is_safe():
    assert safe_divide(4, 0) == 0
