from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
import psutil

from app.core.metrics import metrics

router = APIRouter(prefix="/api/monitor")

@router.get("/status")
def status():
    return {"cpu": psutil.cpu_percent(), "memory": psutil.virtual_memory().percent}

@router.get("/metrics")
def get_metrics():
    return metrics.get_stats()

@router.get("/metrics/prometheus")
def get_prometheus_metrics():
    return PlainTextResponse(
        content=metrics.get_prometheus(),
        media_type="text/plain"
    )