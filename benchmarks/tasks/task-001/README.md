# task-001: parse_config empty mapping

The fixture is a small Python Git repository. `parse_config({})` currently returns `None`, while the expected behavior is an empty dictionary. The target test is `tests/test_parser.py::test_empty_mapping_returns_empty_mapping`.

`evaluation_only/gold_patch.diff` is kept outside the agent-visible repository input and is never loaded by the repair pipeline.
