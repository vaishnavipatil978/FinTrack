from fastapi import APIRouter, Response

from app.core.metrics import METRICS_CONTENT_TYPE, render_latest

router = APIRouter(tags=["Observability"])


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=render_latest(), media_type=METRICS_CONTENT_TYPE)
