
from fastapi import APIRouter
from app.core.user_system import LoginReq, login

router = APIRouter(prefix="/api/user")

@router.post("/login")
def login_api(req: LoginReq):
    return login(req)