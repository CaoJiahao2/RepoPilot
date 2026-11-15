import pytest

from repopilot.core.errors import PatchValidationError
from repopilot.core.schemas import PatchResult
from repopilot.tools.patch import PatchPolicy, PatchValidator


VALID_DIFF = """\
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""


def _two_file_diff() -> str:
    return """\
--- a/a.py
+++ b/a.py
@@ -1 +1 @@
-old
+new
--- a/b.py
+++ b/b.py
@@ -1 +1 @@
-old
+new
"""


def test_valid_unified_diff_and_patch_result_match() -> None:
    result = PatchResult(
        unified_diff=VALID_DIFF,
        modified_files=["src/app.py"],
        explanation="fix addition",
    )

    validated = PatchValidator().validate(result)

    assert validated.modified_files == ["src/app.py"]
    assert validated.hunk_count == 1
    assert validated.diff_bytes == len(VALID_DIFF.encode("utf-8"))


def test_malformed_diff_is_rejected() -> None:
    validator = PatchValidator()

    with pytest.raises(PatchValidationError, match="file headers"):
        validator.validate("--- a/a.py\n+++ b/a.py\n")

    with pytest.raises(PatchValidationError, match="hunk header"):
        validator.validate("--- a/a.py\n+++ b/a.py\n@@ broken @@\n")


def test_absolute_traversal_and_forbidden_paths_are_rejected() -> None:
    validator = PatchValidator()
    dangerous_diffs = [
        "--- /tmp/a.py\n+++ /tmp/a.py\n@@ -1 +1 @@\n-old\n+new\n",
        "--- a/../outside.py\n+++ b/../outside.py\n@@ -1 +1 @@\n-old\n+new\n",
        "--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-old\n+new\n",
    ]

    for diff in dangerous_diffs:
        with pytest.raises(PatchValidationError):
            validator.validate(diff)


def test_allowed_paths_size_and_file_count_limits_are_enforced() -> None:
    validator = PatchValidator()
    with pytest.raises(PatchValidationError, match="outside the allowed list"):
        validator.validate(VALID_DIFF, PatchPolicy(allowed_paths=["tests"]))

    with pytest.raises(PatchValidationError, match="maximum diff size"):
        validator.validate(VALID_DIFF, PatchPolicy(max_diff_bytes=10))

    with pytest.raises(PatchValidationError, match="too many files"):
        validator.validate(_two_file_diff(), PatchPolicy(max_modified_files=1))


def test_patch_result_file_list_must_match_diff() -> None:
    result = PatchResult(
        unified_diff=VALID_DIFF,
        modified_files=["src/other.py"],
        explanation="mismatch",
    )

    with pytest.raises(PatchValidationError, match="does not match"):
        PatchValidator().validate(result)
