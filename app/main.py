import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api.agent_api import agent_router
from app.api.user_api import router as user_router
from app.api.task_api import router as task_api
from app.api.monitor_api import router as monitor_api

# 绝对路径修复（解决 static 报错的核心）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_PATH = os.path.join(BASE_DIR, "static")
app = FastAPI(title="企业级AI Agent平台", version="v5.0")

app.mount("/static", StaticFiles(directory=STATIC_PATH), name="static")
app.include_router(agent_router)
app.include_router(user_router)
app.include_router(task_api)
app.include_router(monitor_api)


@app.get("/test")
def test():
    return {"code": 200, "msg": "服务正常！"}


@app.get("/")
def index():
    index_html_path = os.path.join(STATIC_PATH, "index.html")
    return FileResponse(index_html_path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app", host="127.0.0.1", port=8718, reload=False, log_level="debug"
    )
