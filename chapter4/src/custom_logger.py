"""ログ設定は起動時に行う。モジュールのimportでは既存設定を変更しない。"""

import logging
import sys

from src.security import RedactingFormatter


def configure_logging():
    # VS CodeやWindows端末がASCII系のstdout/stderrを渡す環境でも、
    # 日本語を含むログやCLI出力でUnicodeEncodeErrorを起こさないようにする。
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="backslashreplace")
            except (OSError, ValueError):
                # GUI起動元が再設定不可のストリームを渡す場合は、通常の起動を続ける。
                pass
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(getattr(handler, "helpdesk_console", False) for handler in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.helpdesk_console = True
        handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(message)s"))
        root.addHandler(handler)
    logger = logging.getLogger(__name__)
    logger.info(
        "CONSOLE_ENCODING stdout=%s stderr=%s",
        getattr(sys.stdout, "encoding", None),
        getattr(sys.stderr, "encoding", None),
    )


def setup_logger(name, level=logging.INFO):
    """元の書籍コード向け互換関数。ルートロガーには触れない。"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    return logger
