from fastapi import APIRouter, Header
from pydantic import BaseModel
from app.core.task_queue import create_task, get_task_result, get_task_logs
from app.core.user_system import check

router = APIRouter(prefix="/api/task")

class TaskCreate(BaseModel):
    task: str

@router.post("/create")
def create(req: TaskCreate, token: str = Header(None)):
    check(token, "agent.run")
    return {"task_id": create_task(req.task)}

@router.get("/{task_id}")
def get(task_id: str, token: str = Header(None)):
    check(token, "task.view")
    return {
        "status": "completed" if get_task_result(task_id) else "running",
        "result": get_task_result(task_id),
        "logs": get_task_logs(task_id)
    }