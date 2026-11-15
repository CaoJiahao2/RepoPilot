import repopilot
from repopilot.core.config import AppConfig, load_config
from repopilot.core.errors import ErrorCode, RepoPilotError
from repopilot.core.schemas import TaskRequest, ToolResult
from repopilot.observability.logging import configure_logging


def test_package_and_foundation_modules_import() -> None:
    assert repopilot.__version__ == "0.0.1"
    assert AppConfig is not None
    assert callable(load_config)
    assert issubclass(RepoPilotError, Exception)
    assert ErrorCode.CONFIGURATION_ERROR.value == "configuration_error"
    assert TaskRequest is not None
    assert ToolResult is not None
    assert callable(configure_logging)
