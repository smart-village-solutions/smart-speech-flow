"""Process-wide logging for the gateway.

uvicorn configures only its own loggers, so without a root handler the
gateway's INFO lines never reach stdout, and so never reach Loki.
"""

import logging

LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"


def configure_logging() -> None:
    # A no-op when the root logger already has a handler (tests, embedding hosts).
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
