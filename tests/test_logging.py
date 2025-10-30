import logging

import mqdm as M
from mqdm import install_logging, uninstall_logging


def _count_mqdm_handlers(logger=None):
    logger = logger or logging.getLogger()
    from mqdm._logging import MQDMHandler
    return sum(isinstance(h, MQDMHandler) for h in logger.handlers)


def test_install_uninstall_logging_handler_idempotent():
    uninstall_logging()
    root = logging.getLogger()
    n0 = _count_mqdm_handlers(root)
    install_logging(level=logging.INFO)
    install_logging(level=logging.INFO)
    n1 = _count_mqdm_handlers(root)
    assert n1 == n0 + 1
    uninstall_logging()
    n2 = _count_mqdm_handlers(root)
    assert n2 == n0
