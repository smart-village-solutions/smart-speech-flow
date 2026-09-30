"""The gateway's own INFO lines reach stdout without the legacy route module (#230)."""

import logging
from contextlib import contextmanager
from typing import Iterator

from services.api_gateway.app import create_app
from services.api_gateway.logging_setup import LOG_FORMAT


@contextmanager
def _bare_root_logger() -> Iterator[logging.Logger]:
    # pytest adds its capture handlers for the call phase, after fixtures run.
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    root.handlers.clear()
    root.setLevel(logging.WARNING)
    try:
        yield root
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)


def test_create_app_gives_the_root_logger_the_gateway_format() -> None:
    with _bare_root_logger() as root:
        create_app()

        assert root.level == logging.INFO
        assert [handler.formatter._fmt for handler in root.handlers] == [LOG_FORMAT]


def test_an_existing_root_handler_is_left_alone() -> None:
    with _bare_root_logger() as root:
        existing = logging.StreamHandler()
        root.addHandler(existing)

        create_app()

        assert root.handlers == [existing]
