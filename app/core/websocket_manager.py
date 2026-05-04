import asyncio
import json
from typing import Dict, Set
from fastapi import WebSocket
from datetime import datetime


class WebSocketManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, task_id: str):
        await websocket.accept()
        async with self._lock:
            if task_id not in self.active_connections:
                self.active_connections[task_id] = set()
            self.active_connections[task_id].add(websocket)

    async def disconnect(self, websocket: WebSocket, task_id: str):
        async with self._lock:
            if task_id in self.active_connections:
                self.active_connections[task_id].discard(websocket)
                if not self.active_connections[task_id]:
                    del self.active_connections[task_id]

    async def broadcast(self, task_id: str, message: dict):
        if task_id not in self.active_connections:
            return
        
        dead_connections = set()
        async with self._lock:
            connections = self.active_connections.get(task_id, set()).copy()
        
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.add(connection)
        
        if dead_connections:
            async with self._lock:
                for conn in dead_connections:
                    if task_id in self.active_connections:
                        self.active_connections[task_id].discard(conn)

    async def send_stage(self, task_id: str, stage: str, message: str, data: dict = None):
        msg = {
            "type": "stage",
            "stage": stage,
            "message": message,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }
        await self.broadcast(task_id, msg)

    async def send_thinking(self, task_id: str, agent: str, thinking: str, streaming: bool = False):
        msg = {
            "type": "thinking",
            "agent": agent,
            "content": thinking,
            "streaming": streaming,
            "timestamp": datetime.now().isoformat()
        }
        await self.broadcast(task_id, msg)

    async def send_result(self, task_id: str, stage: str, result: str):
        msg = {
            "type": "result",
            "stage": stage,
            "content": result,
            "timestamp": datetime.now().isoformat()
        }
        await self.broadcast(task_id, msg)

    async def send_complete(self, task_id: str, final_result: str):
        msg = {
            "type": "complete",
            "result": final_result,
            "task_id": task_id,
            "timestamp": datetime.now().isoformat()
        }
        await self.broadcast(task_id, msg)

    async def send_error(self, task_id: str, error: str):
        msg = {
            "type": "error",
            "error": error,
            "timestamp": datetime.now().isoformat()
        }
        await self.broadcast(task_id, msg)

    async def send_log(self, task_id: str, log: str):
        msg = {
            "type": "log",
            "content": log,
            "timestamp": datetime.now().isoformat()
        }
        await self.broadcast(task_id, msg)


ws_manager = WebSocketManager()