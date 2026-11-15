from app import apply_discount


def test_percentage_discount_is_applied():
    assert apply_discount(200, 25) == 150
