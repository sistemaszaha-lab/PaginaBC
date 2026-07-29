"""Instrumentacion ligera de requests para diagnostico local de rendimiento."""

from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import ExitStack
import logging
import re
from time import perf_counter

from django.conf import settings
from django.db import connections


logger = logging.getLogger("performance")

_SQL_STRING_LITERAL = re.compile(r"'(?:''|[^'])*'")
_SQL_NUMBER_LITERAL = re.compile(r"(?<![\w])[-+]?\d+(?:\.\d+)?(?![\w])")
_SQL_WHITESPACE = re.compile(r"\s+")


def _safe_sql_fingerprint(sql: str) -> str:
    """Normaliza SQL sin interpolar ni registrar sus parametros."""
    redacted = _SQL_STRING_LITERAL.sub("?", str(sql))
    redacted = _SQL_NUMBER_LITERAL.sub("?", redacted)
    return _SQL_WHITESPACE.sub(" ", redacted).strip()


class _QueryRecorder:
    def __init__(self) -> None:
        self.queries: list[tuple[float, str]] = []

    def __call__(self, execute, sql, params, many, context):
        started = perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            duration_ms = (perf_counter() - started) * 1000
            # No se registran params: pueden contener datos personales o secretos.
            self.queries.append((duration_ms, _safe_sql_fingerprint(sql)))


class PerformanceDiagnosticsMiddleware:
    """Mide tiempo, SQL y respuesta cuando PERFORMANCE_DEBUG esta habilitado."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.PERFORMANCE_DEBUG:
            return self.get_response(request)

        recorder = _QueryRecorder()
        started = perf_counter()
        response = None

        try:
            with ExitStack() as stack:
                for connection in connections.all():
                    stack.enter_context(connection.execute_wrapper(recorder))
                response = self.get_response(request)
            return response
        finally:
            total_ms = (perf_counter() - started) * 1000
            self._log_summary(request, response, recorder.queries, total_ms)

    @staticmethod
    def _log_summary(request, response, queries, total_ms):
        sql_ms = sum(duration_ms for duration_ms, _sql in queries)
        status = getattr(response, "status_code", "exception")
        html_bytes = 0
        if response is not None and not getattr(response, "streaming", False):
            content_type = response.get("Content-Type", "")
            if "text/html" in content_type:
                html_bytes = len(response.content)

        logger.info(
            "[PERF] %s %s status=%s total_ms=%.2f sql_queries=%d "
            "sql_ms=%.2f html_bytes=%d",
            request.method,
            request.path,
            status,
            total_ms,
            len(queries),
            sql_ms,
            html_bytes,
        )

        grouped = defaultdict(list)
        for duration_ms, sql in queries:
            grouped[sql].append(duration_ms)

        repeated = Counter({sql: len(times) for sql, times in grouped.items()})
        for sql, count in repeated.most_common(settings.PERFORMANCE_DEBUG_TOP_QUERIES):
            if count < 2:
                continue
            times = grouped[sql]
            logger.info(
                "[PERF] repeated count=%d total_ms=%.2f max_ms=%.2f sql=%s",
                count,
                sum(times),
                max(times),
                sql[: settings.PERFORMANCE_DEBUG_SQL_LENGTH],
            )

        slowest = sorted(queries, key=lambda item: item[0], reverse=True)
        for duration_ms, sql in slowest[: settings.PERFORMANCE_DEBUG_TOP_QUERIES]:
            logger.info(
                "[PERF] slow duration_ms=%.2f sql=%s",
                duration_ms,
                sql[: settings.PERFORMANCE_DEBUG_SQL_LENGTH],
            )
