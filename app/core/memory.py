import chromadb
from chromadb.config import Settings as ChromaSettings
from typing import List, Dict, Optional, Any
from datetime import datetime
import uuid
from collections import OrderedDict

from app.settings import CHROMA_PATH


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
            metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        memory_id = str(uuid.uuid4())

        metadata = metadata or {}
        metadata.update({
            "user_id": user_id,
            "memory_type": memory_type,
            "created_at": datetime.now().isoformat()
        })

        embedding = self._get_embedding(content)

        self.collection.add(
            ids=[memory_id],
            embeddings=[embedding],
            documents=[content],
            metadatas=[metadata]
        )

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
            n_results=top_k,
            where=build_where_filter(user_id, memory_type),
            include=["documents", "metadatas", "distances"]
        )

        memories = []
        if results["documents"] and len(results["documents"]) > 0:
            for i, doc in enumerate(results["documents"][0]):
                memories.append({
                    "id": results["ids"][0][i],
                    "content": doc,
                    "metadata": results["metadatas"][0][i],
                    "similarity": 1 - results["distances"][0][i]
                })

        return memories

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
