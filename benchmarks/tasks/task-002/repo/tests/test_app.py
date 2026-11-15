from app import clamp


def test_upper_bound_is_enforced():
    assert clamp(15, 0, 10) == 10
