from fastapi import APIRouter
import psutil

router = APIRouter(prefix="/api/monitor")

@router.get("/status")
def status():
    return {"cpu": psutil.cpu_percent(), "memory": psutil.virtual_memory().percent}