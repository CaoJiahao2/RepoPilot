from app import parse_config


def test_empty_mapping_returns_empty_mapping():
    assert parse_config({}) == {}
