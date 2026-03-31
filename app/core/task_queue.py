import uuid
from typing import Dict, Optional
from threading import Thread
import time
import asyncio

TASKS: Dict[str, str] = {}
TASK_LOGS: Dict[str, list] = {}
TASK_RESULTS: Dict[str, str] = {}


# async def notify_websocket(task_id: str, log: str, log_type: str = "log"):
#     try:
#         from app.core.websocket_manager import get_ws_manager
#
#         manager = get_ws_manager()
#         if log_type == "complete":
#             await manager.send_complete(task_id, log)
#         elif log_type == "error":
#             await manager.send_error(task_id, log)
#         else:
#             await manager.send_log(task_id, log, log_type)
#     except Exception:
#         pass


def run_background_task(task_id: str):
    try:
        add_log(task_id, "🚀 开始执行任务")
        time.sleep(0.5)

        from app.agent.workflow import run_task_with_logs

        result = run_task_with_logs(task_id, TASKS[task_id])

        TASK_RESULTS[task_id] = result
        add_log(task_id, "✅ 全部执行完成")

        # asyncio.run(notify_websocket(task_id, result, "complete"))

    except Exception as e:
        add_log(task_id, f"❌ 失败：{str(e)}")
        TASK_RESULTS[task_id] = str(e)
        # asyncio.run(notify_websocket(task_id, str(e), "error"))


def create_task(task_content: str) -> str:
    task_id = str(uuid.uuid4())
    TASKS[task_id] = task_content
    TASK_LOGS[task_id] = []
    TASK_RESULTS[task_id] = ""
    add_log(task_id, "📌 任务已创建")
    Thread(target=run_background_task, args=(task_id,), daemon=True).start()
    return task_id


def get_task_result(task_id: str) -> Optional[str]:
    return TASK_RESULTS.get(task_id)


def get_task_logs(task_id: str) -> list:
    return TASK_LOGS.get(task_id, [])


def add_log(task_id: str, msg: str):
    if task_id not in TASK_LOGS:
        TASK_LOGS[task_id] = []
    log_entry = f"[{time.strftime('%H:%M:%S')}] {msg}"
    TASK_LOGS[task_id].append(log_entry)
    # asyncio.run(notify_websocket(task_id, log_entry, "log"))
