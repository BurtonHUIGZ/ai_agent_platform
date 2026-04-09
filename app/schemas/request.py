from pydantic import BaseModel
class TaskRequest(BaseModel):
    task: str
    model: str = None
    session_id: str = None