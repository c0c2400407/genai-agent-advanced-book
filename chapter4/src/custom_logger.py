"""ログ設定は起動時に行う。モジュールのimportでは既存設定を変更しない。"""

import logging
import sys

from src.security import RedactingFormatter


def configure_logging():
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(getattr(handler, "helpdesk_console", False) for handler in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.helpdesk_console = True
        handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(message)s"))
        root.addHandler(handler)


def setup_logger(name, level=logging.INFO):
    """元の書籍コード向け互換関数。ルートロガーには触れない。"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    return logger
