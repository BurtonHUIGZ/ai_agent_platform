
from fastapi import APIRouter, Header
from fastapi import HTTPException
from app.core.user_system import LoginReq, login, check

router = APIRouter(prefix="/api/user")

@router.post("/login")
def login_api(req: LoginReq):
    return login(req)

@router.get("/me")
def get_current_user(token: str = Header(None)):
    check(token, "agent.run")
    return {"code": 200, "msg": "ok"}