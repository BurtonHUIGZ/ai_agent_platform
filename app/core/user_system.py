from pydantic import BaseModel
from fastapi import HTTPException
import uuid

USERS = {"admin": {"pwd": "admin123456", "role": "admin", "permissions": ["agent.run", "user.list", "task.view", "monitor.view", "memory.view", "memory.write"]}}
TOKENS = {}

class LoginReq(BaseModel):
    username: str
    password: str

def login(req: LoginReq):
    if req.username not in USERS or USERS[req.username]["pwd"] != req.password:
        raise HTTPException(status_code=401)
    token = str(uuid.uuid4())
    TOKENS[token] = req.username
    return {"token": token}

def check(token: str, perm: str):
    if token not in TOKENS:
        raise HTTPException(status_code=401)
    return True