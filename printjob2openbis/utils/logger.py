"""
Logging configuration for printjob2openbis.
"""

import logging
from pathlib import Path

# Log file written next to the package root.
_LOG_FILE = Path(__file__).parent.parent / "parser.log"


def get_logger(name: str = "printjob_parser") -> logging.Logger:
    """
    Return a configured logger.

    A console handler (INFO level) and a file handler (DEBUG level) are
    added once; subsequent calls with the same *name* return the cached
    logger without adding duplicate handlers.

    Args:
        name: Logger name – typically ``__name__`` of the calling module.

    Returns:
        Configured :class:`logging.Logger` instance.
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(logging.DEBUG)

        # Console – INFO and above
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

        # File – DEBUG and above
        file_handler = logging.FileHandler(_LOG_FILE)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

        logger.addHandler(console_handler)
        logger.addHandler(file_handler)

    return logger
