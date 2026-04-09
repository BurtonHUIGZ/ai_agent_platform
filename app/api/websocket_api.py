import asyncio
import json
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, UploadFile, File, Form, Header
from pydantic import BaseModel
from typing import Optional
import tempfile
import os

from app.core.websocket_manager import ws_manager
from app.agent.streaming_workflow import run_streaming_task
from app.core.task_queue import TASKS
from app.core.memory import memory

ws_router = APIRouter(prefix="/ws")


@ws_router.websocket("/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    await ws_manager.connect(websocket, task_id)
    
    try:
        await websocket.send_json({
            "type": "connected",
            "task_id": task_id,
            "message": "WebSocket连接已建立"
        })
        
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                
            elif message.get("type") == "cancel":
                await websocket.send_json({
                    "type": "cancelled",
                    "message": "任务取消功能开发中"
                })
                
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket, task_id)
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "error": str(e)
        })
        await ws_manager.disconnect(websocket, task_id)


class TaskRequest(BaseModel):
    task: str
    user_id: str = "default"
    session_id: Optional[str] = None


agent_router = APIRouter(prefix="/api/agent")


@agent_router.post("/run-stream")
async def run_agent_stream(req: TaskRequest):
    task_id = str(uuid.uuid4())
    
    TASKS[task_id] = {"content": req.task, "user_id": req.user_id}
    
    async def send_message(tid: str, msg_type: str, agent: str, data: dict):
        message = {
            "type": msg_type,
            "agent": agent,
            "data": data
        }
        
        if msg_type == "complete":
            message["result"] = data.get("content", "")
            message["data"] = data
        elif msg_type == "error":
            message["error"] = data.get("content", "")
            message["data"] = data
        elif msg_type in ["researcher", "executor", "validator", "manager"]:
            message["agent"] = msg_type
        
        await ws_manager.broadcast(tid, message)
    
    asyncio.create_task(run_streaming_task(task_id, req.task, req.user_id, send_message, req.session_id))
    
    return {
        "code": 200,
        "data": {
            "task_id": task_id,
            "websocket_url": f"/ws/{task_id}"
        }
    }


ws_info_router = APIRouter(prefix="/api")


@ws_info_router.get("/ws-info/{task_id}")
async def get_ws_info(task_id: str):
    return {
        "code": 200,
        "data": {
            "task_id": task_id,
            "websocket_url": f"/ws/{task_id}",
            "active_connections": len(ws_manager.active_connections.get(task_id, set()))
        }
    }


async def extract_text_from_file(file_path: str, file_extension: str) -> str:
    text = ""
    if file_extension == ".txt":
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
    elif file_extension == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            for page in reader.pages:
                text += page.extract_text() or ""
        except Exception as e:
            raise ValueError(f"PDF解析失败: {str(e)}")
    elif file_extension == ".docx":
        try:
            from docx import Document
            doc = Document(file_path)
            text = "\n".join([p.text for p in doc.paragraphs])
        except Exception as e:
            raise ValueError(f"DOCX解析失败: {str(e)}")
    else:
        raise ValueError(f"不支持的文件格式: {file_extension}")
    return text


@ws_info_router.post("/upload-file")
async def upload_file(
    upload_id: str = Form(...),
    file: UploadFile = File(...),
    user_id: str = Form("default"),
    memory_type: str = Form("knowledge"),
    token: str = Header(None)
):
    from app.core.user_system import check
    check(token, "memory.write")
    
    try:
        filename = file.filename or "unknown"
        file_extension = os.path.splitext(filename)[1].lower()
        if file_extension not in [".txt", ".pdf", ".docx"]:
            await ws_manager.broadcast(upload_id, {
                "type": "upload_error",
                "error": "不支持的文件格式",
                "status": "error"
            })
            return {"code": 400, "msg": "不支持的文件格式"}
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        
        await ws_manager.broadcast(upload_id, {
            "type": "upload_status",
            "message": "正在解析文件...",
            "progress": 10
        })
        
        try:
            text = await extract_text_from_file(tmp_path, file_extension)
            
            if not text.strip():
                await ws_manager.broadcast(upload_id, {
                    "type": "upload_error",
                    "error": "文件内容为空",
                    "status": "error"
                })
                return {"code": 400, "msg": "文件内容为空"}
            
            await ws_manager.broadcast(upload_id, {
                "type": "upload_status",
                "message": "正在分块...",
                "progress": 30
            })
            
            chunks = split_text(text)
            total = len(chunks)
            
            await ws_manager.broadcast(upload_id, {
                "type": "upload_status",
                "message": f"开始处理 {total} 个片段...",
                "progress": 40,
                "total_chunks": total
            })
            
            for i, chunk in enumerate(chunks):
                memory.add_memory(
                    user_id=user_id,
                    content=chunk,
                    memory_type=memory_type,
                    metadata={
                        "source_file": file.filename,
                        "chunk_index": i,
                        "total_chunks": total
                    }
                )
                
                chunk_progress = 40 + int((i + 1) / total * 55)
                await ws_manager.broadcast(upload_id, {
                    "type": "upload_progress",
                    "progress": chunk_progress,
                    "chunk_index": i,
                    "total_chunks": total,
                    "status": "uploading"
                })
                
                await asyncio.sleep(0.1)
            
            await ws_manager.broadcast(upload_id, {
                "type": "upload_complete",
                "progress": 100,
                "chunks": total,
                "status": "completed"
            })
            
            return {"code": 200, "msg": "上传成功", "chunks": total}
            
        finally:
            os.unlink(tmp_path)
            
    except Exception as e:
        await ws_manager.broadcast(upload_id, {
            "type": "upload_error",
            "error": str(e),
            "status": "error"
        })
        return {"code": 500, "msg": str(e)}


def split_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list:
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
    return chunks


class UploadStartRequest(BaseModel):
    filename: str
    user_id: str = "default"
    memory_type: str = "knowledge"


@ws_info_router.post("/upload-start")
async def upload_start(req: UploadStartRequest, token: str = Header(None)):
    from app.core.user_system import check
    check(token, "memory.write")
    
    upload_id = str(uuid.uuid4())
    
    TASKS[upload_id] = {
        "type": "upload",
        "filename": req.filename,
        "user_id": req.user_id,
        "memory_type": req.memory_type,
        "status": "started"
    }
    
    return {
        "code": 200,
        "data": {
            "upload_id": upload_id,
            "websocket_url": f"/ws/{upload_id}"
        }
    }


@ws_info_router.post("/upload-chunk")
async def upload_chunk(
    upload_id: str,
    chunk_index: int,
    total_chunks: int,
    content: str,
    metadata: dict = None
):
    try:
        memory.add_memory(
            user_id=TASKS.get(upload_id, {}).get("user_id", "default"),
            content=content,
            memory_type=TASKS.get(upload_id, {}).get("memory_type", "knowledge"),
            metadata={
                "source_file": TASKS.get(upload_id, {}).get("filename", "unknown"),
                "chunk_index": chunk_index,
                "total_chunks": total_chunks,
                **(metadata or {})
            }
        )
        
        progress = int((chunk_index + 1) / total_chunks * 100)
        
        await ws_manager.broadcast(upload_id, {
            "type": "upload_progress",
            "progress": progress,
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
            "status": "uploading"
        })
        
        if chunk_index == total_chunks - 1:
            TASKS[upload_id]["status"] = "completed"
            await ws_manager.broadcast(upload_id, {
                "type": "upload_complete",
                "progress": 100,
                "status": "completed"
            })
        
        return {"code": 200, "progress": progress}
        
    except Exception as e:
        await ws_manager.broadcast(upload_id, {
            "type": "upload_error",
            "error": str(e),
            "status": "error"
        })
        return {"code": 500, "error": str(e)}
