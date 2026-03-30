import logging

from app.core.request_context import get_request_id

_record_factory_installed = False


def _install_log_record_factory() -> None:
    global _record_factory_installed

    if _record_factory_installed:
        return

    previous_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = previous_factory(*args, **kwargs)
        record.request_id = get_request_id()
        return record

    logging.setLogRecordFactory(record_factory)
    _record_factory_installed = True


def configure_logging(level: str) -> None:
    _install_log_record_factory()

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | request_id=%(request_id)s | %(message)s"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
        return

    for handler in root_logger.handlers:
        handler.setFormatter(formatter)
