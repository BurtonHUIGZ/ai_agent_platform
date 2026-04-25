import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api.user_api import router as user_router
from app.api.monitor_api import router as monitor_api
from app.api.memory_api import router as memory_router
from app.api.websocket_api import ws_router, agent_router as ws_agent_router, ws_info_router
from app.api.eval_api import router as eval_router
from app.settings import STATIC_PATH

app = FastAPI(title="企业级AI Agent平台", version="v5.0")

app.mount("/static", StaticFiles(directory=STATIC_PATH), name="static")
app.include_router(user_router)
app.include_router(monitor_api)
app.include_router(memory_router)
app.include_router(ws_router)
app.include_router(ws_agent_router)
app.include_router(ws_info_router)
app.include_router(eval_router)


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
