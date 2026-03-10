"""
Prometheus-compatible metrics endpoint.
Scraped by Prometheus / Grafana Alloy in Kubernetes.
"""
from fastapi import APIRouter, Response
from prometheus_client import (
    Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST,
    CollectorRegistry, REGISTRY,
)

router = APIRouter()

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
)


@router.get("/prometheus")
async def prometheus_metrics():
    """Expose metrics for Prometheus scraping."""
    return Response(
        content=generate_latest(REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )
