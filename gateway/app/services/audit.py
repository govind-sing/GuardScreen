import time
from app.models.request_log import RequestLog


class RequestTimer:
    """Small helper to measure request latency for audit logging."""

    def __init__(self):
        self._start = time.monotonic()

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._start) * 1000)


def mark_success(request_log: RequestLog, timer: RequestTimer) -> None:
    request_log.status = "success"
    request_log.latency_ms = timer.elapsed_ms()


def mark_error(request_log: RequestLog, timer: RequestTimer, error_detail: str) -> None:
    request_log.status = "error"
    request_log.latency_ms = timer.elapsed_ms()
    request_log.error_detail = error_detail