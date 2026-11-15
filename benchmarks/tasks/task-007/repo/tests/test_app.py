from app import sum_positive


def test_only_positive_values_are_summed():
    assert sum_positive([1, -2, 3]) == 4
