from fastapi import APIRouter, Header
from app.schemas.request import TaskRequest
from app.agent.workflow import workflow
from app.core.user_system import check

agent_router = APIRouter(prefix="/api/agent")

@agent_router.post("/run")
def run(req: TaskRequest, token: str = Header(None)):
    check(token, "agent.run")
    result = workflow.invoke({"task": req.task})
    return {"code": 200, "data": result}