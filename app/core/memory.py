import chromadb
from chromadb.config import Settings as ChromaSettings
from typing import List, Dict, Optional, Any
from datetime import datetime
import uuid
import sqlite3
import os
import math
from collections import OrderedDict

from app.settings import CHROMA_PATH

MAX_EMBEDDING_TOKENS = 2000

# SQLite 数据库路径
MEMORY_DB_PATH = os.path.join(os.path.dirname(CHROMA_PATH), "memories.db")

def _get_sqlite_conn():
    return sqlite3.connect(MEMORY_DB_PATH)

def _init_sqlite_db():
    os.makedirs(os.path.dirname(MEMORY_DB_PATH), exist_ok=True)
    conn = _get_sqlite_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_fulltext (
            id TEXT PRIMARY KEY,
            summary TEXT NOT NULL,
            full_content TEXT,
            user_id TEXT,
            memory_type TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    
def estimate_tokens(text: str) -> int:
    chinese = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    others = len(text) - chinese
    return chinese + others // 4 * 3


class ShortTermMemory:
    def __init__(self, max_size: int = 20):
        self.history: Dict[str, List[Dict[str, Any]]] = {}
        self.max_size = max_size

    def add(self, session_id: str, role: str, content: str):
        if session_id not in self.history:
            self.history[session_id] = []
        self.history[session_id].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        if len(self.history[session_id]) > self.max_size:
            self.history[session_id].pop(0)

    def get_context(self, session_id: str, last_n: int = 10) -> str:
        msgs = self.history.get(session_id, [])[-last_n:]
        return "\n".join([f"{m['role']}: {m['content']}" for m in msgs])

    def get_messages(self, session_id: str, last_n: int = 10) -> List[Dict[str, Any]]:
        return self.history.get(session_id, [])[-last_n:]

    def clear(self, session_id: str):
        if session_id in self.history:
            self.history[session_id] = []

    def clear_all(self):
        self.history = {}

    def get_token_count(self, session_id: str) -> int:
        messages = self.history.get(session_id, [])
        total = 0
        for m in messages:
            content = m.get("content", "")
            total += len(content)
        return total

    def compress_context(self, session_id: str, compress_threshold: int = 15):
        if session_id in self.history:
            messages = self.history[session_id]
            if len(messages) > compress_threshold:
                keep = messages[-compress_threshold:]
                self.history[session_id] = keep


short_term_memory = ShortTermMemory()


def build_where_filter(user_id: str, memory_type: Optional[str] = None) -> Dict:
    if memory_type:
        return {
            "$and": [
                {"user_id": {"$eq": user_id}},
                {"memory_type": {"$eq": memory_type}}
            ]
        }
    return {"user_id": {"$eq": user_id}}


class LongTermMemory:
    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=CHROMA_PATH,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            name="agent_memories",
            metadata={"description": "AI Agent 长期记忆存储"}
        )
        self.embedding_model = "nomic-embed-text"
        self._embeddings = None

    def _get_embeddings(self):
        if self._embeddings is None:
            from langchain_ollama import OllamaEmbeddings
            self._embeddings = OllamaEmbeddings(
                model=self.embedding_model
            )
        return self._embeddings

    def _get_embedding(self, text: str) -> List[float]:
        embeddings = self._get_embeddings()
        return embeddings.embed_query(text)

    def add_memory(
            self,
            user_id: str,
            content: str,
            memory_type: str = "general",
            full_content: Optional[str] = None,
            metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        memory_id = str(uuid.uuid4())

        metadata = metadata or {}
        metadata.update({
            "user_id": user_id,
            "memory_type": memory_type,
            "created_at": datetime.now().isoformat(),
            "db_id": memory_id
        })

        summary = content[:500] if len(content) > 500 else content

        try:
            embedding = self._get_embedding(summary)
            print(f"[LongTermMemory] 获取embedding成功, summary长度={len(summary)}, embedding维度={len(embedding)}")
        except Exception as e:
            print(f"[LongTermMemory] 获取embedding失败: {e}")
            raise

        try:
            self.collection.add(
                ids=[memory_id],
                embeddings=[embedding],
                documents=[summary],
                metadatas=[metadata]
            )
            print(f"[LongTermMemory] 已添加到collection, id={memory_id}")
        except Exception as e:
            print(f"[LongTermMemory] collection.add失败: {e}")
            raise

        try:
            conn = _get_sqlite_conn()
            conn.execute("""
                INSERT INTO memory_fulltext (id, summary, full_content, user_id, memory_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, [memory_id, summary, full_content or content, user_id, memory_type, datetime.now().isoformat()])
            conn.commit()
            print(f"[LongTermMemory] 已保存到SQLite, id={memory_id}")
        except Exception as e:
            print(f"[LongTermMemory] SQLite保存失败: {e}")

        return memory_id

    def retrieve_memories(
            self,
            user_id: str,
            query: str,
            top_k: int = 5,
            memory_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query_embedding = self._get_embedding(query)

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k * 2,
            where=build_where_filter(user_id, memory_type),
            include=["documents", "metadatas", "distances"]
        )

        memories = []
        if results["documents"] and len(results["documents"]) > 0:
            for i, doc in enumerate(results["documents"][0]):
                mem_id = results["ids"][0][i]
                metadata = results["metadatas"][0][i]
                similarity = 1 - results["distances"][0][i]
                full_content = None
                
                try:
                    conn = _get_sqlite_conn()
                    row = conn.execute(
                        "SELECT full_content, created_at FROM memory_fulltext WHERE id=?",
                        [mem_id]
                    ).fetchone()
                    full_content = row[0] if row else None
                    created_at = row[1] if row else metadata.get("created_at", "")
                except Exception as e:
                    print(f"[LongTermMemory] 读取全文失败: {e}")
                    full_content = None
                    created_at = metadata.get("created_at", "")
                
                time_weight = self._calc_time_weight(created_at)
                combined_score = similarity * 0.7 + time_weight * 0.3
                
                memories.append({
                    "id": mem_id,
                    "content": doc,
                    "full_content": full_content or doc,
                    "metadata": metadata,
                    "similarity": similarity,
                    "combined_score": combined_score,
                    "created_at": created_at
                })

        memories.sort(key=lambda m: m["combined_score"], reverse=True)
        return memories[:top_k]

    def _calc_time_weight(self, created_at: str) -> float:
        try:
            created = datetime.fromisoformat(created_at)
            hours_passed = (datetime.now() - created).total_seconds() / 3600
            if hours_passed < 1:
                return 1.0
            elif hours_passed < 24:
                return 0.8
            elif hours_passed < 72:
                return 0.5
            else:
                return max(0.2, math.exp(-0.01 * hours_passed))
        except (ValueError, TypeError):
            return 0.5

    def get_user_memories(
            self,
            user_id: str,
            memory_type: Optional[str] = None,
            limit: int = 100
    ) -> List[Dict[str, Any]]:
        results = self.collection.get(
            where=build_where_filter(user_id, memory_type),
            limit=limit,
            include=["documents", "metadatas"]
        )

        memories = []
        if results["documents"]:
            for i, doc in enumerate(results["documents"]):
                memories.append({
                    "id": results["ids"][i],
                    "content": doc,
                    "metadata": results["metadatas"][i]
                })

        return memories

    def delete_memory(self, memory_id: str) -> bool:
        try:
            self.collection.delete(ids=[memory_id])
            return True
        except Exception:
            return False

    def clear_user_memories(self, user_id: str) -> int:
        results = self.collection.get(
            where={"user_id": {"$eq": user_id}},
            include=["ids"]
        )

        count = 0
        if results["ids"]:
            self.collection.delete(ids=results["ids"])
            count = len(results["ids"])

        return count

    def get_memory_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        if user_id:
            results = self.collection.get(
                where={"user_id": {"$eq": user_id}},
                include=[]
            )
            total = len(results["ids"]) if results["ids"] else 0

            by_type = {}
            for mtype in ["task", "preference", "knowledge", "general"]:
                type_results = self.collection.get(
                    where={
                        "$and": [
                            {"user_id": {"$eq": user_id}},
                            {"memory_type": {"$eq": mtype}}
                        ]
                    },
                    include=[]
                )
                by_type[mtype] = len(type_results["ids"]) if type_results["ids"] else 0

            return {
                "total": total,
                "by_type": by_type
            }
        else:
            return {"total": self.collection.count()}


memory = LongTermMemory()

# 初始化 SQLite 数据库
_init_sqlite_db()
