import logging

import pytest


@pytest.fixture(autouse=True)
def clean_salespilot_logger():
    logger = logging.getLogger("salespilot")
    previous_handlers = list(logger.handlers)
    previous_level = logger.level
    previous_propagate = logger.propagate
    for handler in previous_handlers:
        logger.removeHandler(handler)
        handler.close()
    yield
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    for handler in previous_handlers:
        logger.addHandler(handler)
    logger.setLevel(previous_level)
    logger.propagate = previous_propagate


def test_configure_logging_defaults_to_info_and_is_idempotent(tmp_path):
    from utils.logging_config import configure_logging

    logger = configure_logging(tmp_path / "logs", env={})
    handler_count = len(logger.handlers)

    assert logger.level == logging.INFO
    assert logger.propagate is False
    configure_logging(tmp_path / "logs", env={})
    assert len(logger.handlers) == handler_count == 2


@pytest.mark.parametrize(
    ("configured", "expected"),
    [("DEBUG", logging.DEBUG), ("WARNING", logging.WARNING), ("not-a-level", logging.INFO)],
)
def test_configure_logging_parses_level_and_defaults_invalid_values(
    tmp_path, configured, expected
):
    from utils.logging_config import configure_logging

    logger = configure_logging(tmp_path / "logs", env={"SALESPILOT_LOG_LEVEL": configured})

    assert logger.level == expected


def test_configure_logging_writes_utf8_file_with_daily_rotation(tmp_path):
    from logging.handlers import TimedRotatingFileHandler

    from utils.logging_config import configure_logging

    logger = configure_logging(tmp_path / "logs", env={})
    logger.info("logging-core-test")

    file_handler = next(
        handler for handler in logger.handlers if isinstance(handler, TimedRotatingFileHandler)
    )
    assert file_handler.baseFilename.endswith("salespilot.log")
    assert file_handler.when == "MIDNIGHT"
    assert file_handler.backupCount == 14
    assert file_handler.encoding == "utf-8"
    assert "logging-core-test" in (tmp_path / "logs" / "salespilot.log").read_text(encoding="utf-8")


def test_redaction_removes_api_keys_authorization_and_truncates():
    from utils.logging_config import redact_sensitive

    value = "sk-secret-value DEEPSEEK_API_KEY=deep-secret Authorization: Bearer token-secret"
    redacted = redact_sensitive(value)

    assert "sk-secret-value" not in redacted
    assert "deep-secret" not in redacted
    assert "token-secret" not in redacted
    assert "[REDACTED]" in redacted
    assert len(redact_sensitive("x" * 700)) == 500


def test_exception_traceback_is_redacted_in_file_and_console(tmp_path, capsys):
    from utils.logging_config import configure_logging

    logger = configure_logging(tmp_path / "logs", env={})
    try:
        raise RuntimeError("request failed with sk-secret-value")
    except RuntimeError:
        logger.exception("analysis.run.failed")

    captured = capsys.readouterr()
    console_output = captured.out + captured.err
    file_output = (tmp_path / "logs" / "salespilot.log").read_text(encoding="utf-8")

    for output in (console_output, file_output):
        assert "sk-secret-value" not in output
        assert "analysis.run.failed" in output
        assert "Traceback" in output


def test_file_handler_failure_keeps_console_logging(tmp_path, monkeypatch, capsys):
    import utils.logging_config as logging_config

    def fail_file_handler(*args, **kwargs):
        raise OSError("DEEPSEEK_API_KEY=secret")

    monkeypatch.setattr(logging_config, "TimedRotatingFileHandler", fail_file_handler)

    logger = logging_config.configure_logging(tmp_path / "logs", env={})
    logger.info("still-running")
    captured = capsys.readouterr()
    output = captured.out + captured.err

    assert any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers)
    assert "still-running" in output
    assert "secret" not in output
    assert "[REDACTED]" in output
