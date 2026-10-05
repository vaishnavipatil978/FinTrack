"""Prometheus metrics - docs/architecture/observability.md §4. Scraped at GET /metrics,
not exposed through the public load balancer listener in production (an infra concern, not
an app one - see that doc).
"""

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status_code"]
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "path"]
)
CACHE_HITS_TOTAL = Counter("cache_hits_total", "Report cache hits", ["cache_key_prefix"])
CACHE_MISSES_TOTAL = Counter("cache_misses_total", "Report cache misses", ["cache_key_prefix"])
RATE_LIMIT_REJECTIONS_TOTAL = Counter(
    "rate_limit_rejections_total", "Requests rejected by the rate limiter", ["scope"]
)
BACKGROUND_JOB_DURATION_SECONDS = Histogram(
    "background_job_duration_seconds", "Background job duration", ["task_name"]
)
BACKGROUND_JOB_FAILURES_TOTAL = Counter(
    "background_job_failures_total", "Background job failures", ["task_name", "reason"]
)


def render_latest() -> bytes:
    return generate_latest()


METRICS_CONTENT_TYPE = CONTENT_TYPE_LATEST
