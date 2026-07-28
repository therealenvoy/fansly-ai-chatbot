from __future__ import annotations

import ast
import logging
import sys
from pathlib import Path

from src.safe_logging import PrivacySafeFormatter


ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_IDENTIFIERS = {
    "account_id",
    "body",
    "fan_id",
    "chat_id",
    "creator_id",
    "display_name",
    "fan_texts",
    "partner_account_id",
    "payload",
    "platform_message_id",
    "raw_body",
    "message_id",
    "content",
    "text",
    "username",
}
EXCEPTION_IDENTIFIERS = {"e", "exc", "error", "exception"}
LOGGER_METHODS = {
    "debug",
    "info",
    "warning",
    "error",
    "exception",
    "critical",
}


def _logger_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in LOGGER_METHODS:
            continue
        if not isinstance(node.func.value, ast.Name):
            continue
        if node.func.value.id != "logger":
            continue
        yield node


def _raise_with_dynamic_message(message: str) -> None:
    raise ValueError(message)


def test_exception_formatter_omits_exception_message() -> None:
    sensitive_text = "raw fan message and provider secret"
    try:
        _raise_with_dynamic_message(sensitive_text)
    except ValueError:
        record = logging.LogRecord(
            name="privacy-test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="Operation failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    rendered = PrivacySafeFormatter("%(message)s").format(record)

    assert sensitive_text not in rendered
    assert "ValueError" in rendered
    assert "_raise_with_dynamic_message" in rendered


def test_logger_arguments_do_not_reference_fan_payload_fields() -> None:
    violations: list[str] = []
    for path in (ROOT / "src").rglob("*.py"):
        for call in _logger_calls(path):
            referenced_names = {
                child.id
                for argument in call.args
                for child in ast.walk(argument)
                if isinstance(child, ast.Name)
            }
            referenced_attributes = {
                child.attr
                for argument in call.args
                for child in ast.walk(argument)
                if isinstance(child, ast.Attribute)
            }
            found = (
                referenced_names | referenced_attributes
            ) & SENSITIVE_IDENTIFIERS
            if found:
                relative = path.relative_to(ROOT)
                violations.append(
                    f"{relative}:{call.lineno}: {sorted(found)}"
                )

    assert violations == []


def test_logger_arguments_do_not_render_exception_messages() -> None:
    violations: list[str] = []
    for path in (ROOT / "src").rglob("*.py"):
        for call in _logger_calls(path):
            for argument in call.args:
                direct_names: set[str] = set()
                if isinstance(argument, ast.Name):
                    direct_names.add(argument.id)
                elif isinstance(argument, ast.JoinedStr):
                    direct_names.update(
                        child.id
                        for child in ast.walk(argument)
                        if isinstance(child, ast.Name)
                    )
                found = direct_names & EXCEPTION_IDENTIFIERS
                if found:
                    relative = path.relative_to(ROOT)
                    violations.append(
                        f"{relative}:{call.lineno}: {sorted(found)}"
                    )

    assert violations == []
