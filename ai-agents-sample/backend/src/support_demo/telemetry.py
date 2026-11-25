import logging
from contextlib import contextmanager
from typing import Any

from agent_framework.observability import configure_otel_providers
from opentelemetry import metrics, trace
from opentelemetry._logs import get_logger_provider
from opentelemetry.sdk._logs import LoggingHandler
from opentelemetry.trace import Status, StatusCode

from support_demo.config import settings

logger = logging.getLogger("support_demo")
tracer = trace.get_tracer("support_demo")
meter = metrics.get_meter("support_demo")
outcomes = meter.create_counter("support.run.outcomes")
retries = meter.create_counter("support.external.retries")
turns = meter.create_counter("support.group.turns")
duration = meter.create_histogram("support.run.active.duration", unit="s")
approval_wait = meter.create_histogram("support.approval.wait.duration", unit="s")
retrieval_hits = meter.create_histogram("support.retrieval.matches")


def configure(service_name: str) -> None:
    config = settings()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if config.telemetry_enabled:
        configure_otel_providers(
            service_name=service_name,
            otlp_endpoint=config.otel_exporter_otlp_endpoint,
            enable_sensitive_data=config.capture_synthetic_payloads,
        )
        if not any(isinstance(handler, LoggingHandler) for handler in logger.handlers):
            logger.addHandler(
                LoggingHandler(
                    level=logging.INFO,
                    logger_provider=get_logger_provider(),
                )
            )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)


@contextmanager
def span(name: str, **attributes: Any):
    # Do not let exception messages or arguments leak into telemetry by default.
    with tracer.start_as_current_span(
        name, attributes=attributes, record_exception=False, set_status_on_exception=False
    ) as current:
        try:
            yield current
        except Exception as exc:
            current.set_status(Status(StatusCode.ERROR))
            current.set_attribute("error.type", type(exc).__name__)
            logger.error("%s failed [%s]", name, type(exc).__name__)
            raise


def shutdown() -> None:
    for provider in (trace.get_tracer_provider(), metrics.get_meter_provider()):
        if hasattr(provider, "force_flush"):
            provider.force_flush()
    logs_provider = get_logger_provider()
    if hasattr(logs_provider, "force_flush"):
        logs_provider.force_flush()
