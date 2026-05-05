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
from app.utils.logger import memory_logger as logger

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
        
        # 用户记忆 collection（存储 task/question/conversation 类型）
        self.user_collection = self.client.get_or_create_collection(
            name="user_memories",
            metadata={"description": "用户会话记忆"}
        )
        
        # 知识库 collection（存储 knowledge/general 类型）
        self.knowledge_collection = self.client.get_or_create_collection(
            name="knowledge_base",
            metadata={"description": "知识库文档"}
        )
        
        # 默认使用用户记忆 collection
        self.collection = self.user_collection
        
        self.embedding_model = "nomic-embed-text"
        self._embeddings = None
        self._bm25_index = None
        self._bm25_corpus = None
        
        # 延迟初始化 BM25 索引
        self._bm25_initialized = False

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

    def _get_collection(self, memory_type: str):
        """根据 memory_type 选择对应的 collection"""
        if memory_type in ["task", "question", "conversation", "preference"]:
            return self.user_collection
        elif memory_type in ["knowledge", "general"]:
            return self.knowledge_collection
        else:
            return self.user_collection

    def add_memory(
            self,
            user_id: str,
            content: str,
            memory_type: str = "general",
            full_content: Optional[str] = None,
            metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """添加单条记忆"""
        # 批量添加的简化版本
        return self.add_memories(user_id, [(content, metadata or {})], memory_type)[0]

    def add_memories(
            self,
            user_id: str,
            contents: List[tuple],
            memory_type: str = "general"
    ) -> List[str]:
        """
        批量添加记忆
        
        Args:
            user_id: 用户ID
            contents: List[(content, metadata), ...]
            memory_type: 记忆类型
        
        Returns:
            List[memory_id]
        """
        if not contents:
            return []
        
        ids = []
        embeddings = []
        documents = []
        metadatas = []
        sqlite_data = []
        
        for content, metadata in contents:
            memory_id = str(uuid.uuid4())
            ids.append(memory_id)
            
            summary = content[:500] if len(content) > 500 else content
            
            metadata = metadata or {}
            # 过滤掉 None 值，ChromaDB 不接受 None
            metadata = {k: v for k, v in metadata.items() if v is not None}
            metadata.update({
                "user_id": user_id,
                "memory_type": memory_type,
                "created_at": datetime.now().isoformat(),
                "db_id": memory_id
            })
            metadatas.append(metadata)
            documents.append(summary)
            
            sqlite_data.append((memory_id, summary, content, user_id, memory_type, datetime.now().isoformat()))
        
        # 批量获取 embedding
        try:
            summaries = [doc[:500] if len(doc) > 500 else doc for doc in documents]
            embeddings = self._get_embeddings().embed_documents(summaries)
            logger.debug(f"批量获取embedding成功, {len(embeddings)} 条")
        except Exception as e:
            logger.error(f"批量获取embedding失败: {e}")
            # 使用单个 embedding
            embeddings = []
            for doc in documents:
                try:
                    emb = self._get_embedding(doc)
                    embeddings.append(emb)
                except:
                    embeddings.append([0] * 384)  # 默认维度
        
        # 获取 collection
        collection = self._get_collection(memory_type)
        
        # 批量添加到 ChromaDB
        try:
            collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas
            )
            logger.info(f"批量添加到collection成功: {len(ids)} 条")
        except Exception as e:
            logger.error(f"批量添加到collection失败: {e}")
        
        # 批量添加到 SQLite
        try:
            conn = _get_sqlite_conn()
            conn.executemany("""
                INSERT INTO memory_fulltext (id, summary, full_content, user_id, memory_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, sqlite_data)
            conn.commit()
            logger.info(f"批量保存到SQLite成功: {len(sqlite_data)} 条")
        except Exception as e:
            logger.error(f"批量保存到SQLite失败: {e}")
        
        return ids

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
                    logger.warning(f"读取全文失败: {e}")
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

    def _query_single_collection(self, collection, user_id: str, query: str, top_k: int):
        """查询单个 collection"""
        try:
            query_embedding = self._get_embedding(query)
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where={"user_id": {"$eq": user_id}},
                include=["documents", "metadatas", "distances"]
            )
            
            memories = []
            if results["documents"] and len(results["documents"]) > 0:
                for i, doc in enumerate(results["documents"][0]):
                    mem_id = results["ids"][0][i]
                    metadata = results["metadatas"][0][i]
                    similarity = 1 - results["distances"][0][i]
                    
                    try:
                        conn = _get_sqlite_conn()
                        row = conn.execute(
                            "SELECT full_content, created_at FROM memory_fulltext WHERE id=?",
                            [mem_id]
                        ).fetchone()
                        full_content = row[0] if row else None
                        created_at = row[1] if row else metadata.get("created_at", "")
                    except Exception:
                        full_content = None
                        created_at = metadata.get("created_at", "")
                    
                    memories.append({
                        "id": mem_id,
                        "content": doc,
                        "full_content": full_content or doc,
                        "metadata": metadata,
                        "similarity": similarity,
                        "created_at": created_at,
                        "collection": collection.name
                    })
            return memories
        except Exception as e:
            logger.error(f"查询 collection 失败: {e}")
            return []

    def _init_bm25_index(self):
        """初始化 BM25 索引"""
        if not hasattr(self, '_bm25_index') or self._bm25_index is None:
            from rank_bm25 import BM25Okapi
            self._BM25Okapi = BM25Okapi  # 保存类引用
            self._bm25_index = {}
            self._bm25_corpus = {}
        return self._bm25_index, self._bm25_corpus

    def _get_bm25_results(self, collection_name: str, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """BM25 关键词检索"""
        bm25_index, bm25_corpus = self._init_bm25_index()
        
        # 如果索引不存在，构建它
        if collection_name not in bm25_index or not bm25_corpus.get(collection_name):
            if collection_name == "user_memories":
                self._build_bm25_index(self.user_collection, "user_memories")
            elif collection_name == "knowledge_base":
                self._build_bm25_index(self.knowledge_collection, "knowledge_base")
        
        if collection_name not in bm25_index:
            return []
        
        if not bm25_corpus.get(collection_name):
            return []
        
        tokenized_query = query.lower().split()
        scores = bm25_index[collection_name].get_scores(tokenized_query)
        
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        
        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                doc = bm25_corpus[collection_name][idx]
                results.append({
                    "id": doc.get("id", f"bm25_{idx}"),
                    "content": doc.get("content", ""),
                    "full_content": doc.get("full_content", doc.get("content", "")),
                    "metadata": doc.get("metadata", {}),
                    "bm25_score": scores[idx],
                    "collection": collection_name
                })
        
        return results

    def _build_bm25_index(self, collection, collection_name: str):
        """构建 BM25 索引"""
        bm25_index, bm25_corpus = self._init_bm25_index()
        
        try:
            results = collection.get(include=["documents", "metadatas"])
            if not results.get("documents"):
                return
            
            ids = results.get("ids", [])
            corpus = []
            for i, doc in enumerate(results["documents"]):
                meta = results["metadatas"][i] if results.get("metadatas") else {}
                corpus.append({
                    "id": ids[i] if i < len(ids) else f"doc_{i}",
                    "content": doc,
                    "metadata": meta
                })
            
            bm25_corpus[collection_name] = corpus
            
            tokenized_corpus = [doc["content"].lower().split() for doc in corpus]
            bm25_index[collection_name] = self._BM25Okapi(tokenized_corpus)
            
            logger.info(f"BM25 索引构建完成: {collection_name}, {len(corpus)} 条文档")
        except Exception as e:
            logger.error(f"BM25 索引构建失败: {e}")

    def _rrf_fusion(self, results_list: List[List[Dict[str, Any]]], k: int = 60) -> List[Dict[str, Any]]:
        """RRF (Reciprocal Rank Fusion) 融合算法"""
        doc_scores = {}
        
        for results in results_list:
            for rank, doc in enumerate(results, 1):
                doc_id = doc.get("id", f"doc_{rank}")
                if doc_id not in doc_scores:
                    doc_scores[doc_id] = {
                        "doc": doc,
                        "score": 0.0,
                        "sources": []
                    }
                rrf_score = 1.0 / (k + rank)
                doc_scores[doc_id]["score"] += rrf_score
                doc_scores[doc_id]["sources"].append(doc.get("collection", "unknown"))
        
        fused = sorted(doc_scores.values(), key=lambda x: x["score"], reverse=True)
        # 保留 RRF 分数并添加到结果中
        result = []
        for item in fused:
            doc = item["doc"].copy()
            doc["rrf_score"] = item["score"]
            result.append(doc)
        return result

    def hybrid_retrieve(
            self,
            user_id: str,
            query: str,
            top_k: int = 5,
            user_top_k: int = 5,
            kb_top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """混合检索 + 重排序"""
        import concurrent.futures
        
        # 并行检索：向量检索 + BM25
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            user_vec_future = executor.submit(
                self._query_single_collection, 
                self.user_collection, user_id, query, user_top_k
            )
            kb_vec_future = executor.submit(
                self._query_single_collection,
                self.knowledge_collection, user_id, query, kb_top_k
            )
            user_bm25_future = executor.submit(
                self._get_bm25_results, "user_memories", query, user_top_k
            )
            kb_bm25_future = executor.submit(
                self._get_bm25_results, "knowledge_base", query, kb_top_k
            )
            
            user_vec = user_vec_future.result()
            kb_vec = kb_vec_future.result()
            user_bm25 = user_bm25_future.result()
            kb_bm25 = kb_bm25_future.result()
        
        # RRF 融合：合并向量检索和 BM25 结果
        results_list = [user_vec, kb_vec, user_bm25, kb_bm25]
        fused_memories = self._rrf_fusion(results_list, k=60)
        
        # 提升用户记忆权重（在 RRF 分数上）
        for m in fused_memories:
            if m.get("collection") == "user_memories":
                m["rrf_score"] = m.get("rrf_score", 1.0) * 1.3
        
        # 按 RRF 分数排序
        fused_memories.sort(key=lambda x: x.get("rrf_score", 0), reverse=True)
        
        return fused_memories[:top_k]

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
            limit: int = 100,
            include_knowledge: bool = False,
            offset: int = 0
    ) -> Dict[str, Any]:
        memories = []
        
        # 根据 memory_type 确定要查询的 collection
        user_types = ["task", "question", "conversation", "preference"]
        kb_types = ["knowledge", "general"]
        
        collections_to_query = []
        
        if memory_type:
            if memory_type in user_types:
                collections_to_query = [self.user_collection]
            elif memory_type in kb_types:
                collections_to_query = [self.knowledge_collection]
            else:
                collections_to_query = [self.user_collection]
        else:
            # 没有指定类型
            if include_knowledge:
                # 查询知识库
                collections_to_query = [self.knowledge_collection]
            else:
                # 默认只查询用户记忆
                collections_to_query = [self.user_collection]
        
        # 先获取总数
        total_count = 0
        for collection in collections_to_query:
            try:
                count_result = collection.get(
                    where={"user_id": {"$eq": user_id}},
                    include=[]
                )
                total_count += len(count_result.get("ids", []))
            except Exception:
                pass
        
        for collection in collections_to_query:
            try:
                results = collection.get(
                    where={"user_id": {"$eq": user_id}},
                    limit=limit,
                    offset=offset,
                    include=["documents", "metadatas"]
                )
                
                if results.get("documents"):
                    for i, doc in enumerate(results["documents"]):
                        memories.append({
                            "id": results["ids"][i],
                            "content": doc,
                            "metadata": results["metadatas"][i],
                            "collection": collection.name
                        })
            except Exception:
                pass

        # 按时间排序
        memories.sort(key=lambda x: x.get("metadata", {}).get("created_at", ""), reverse=True)
        
        return {
            "list": memories,
            "total": total_count,
            "offset": offset,
            "limit": limit
        }

    def delete_memory(self, memory_id: str) -> bool:
        try:
            # 尝试从两个 collection 删除
            deleted = False
            for collection in [self.user_collection, self.knowledge_collection]:
                try:
                    collection.delete(ids=[memory_id])
                    deleted = True
                except Exception:
                    pass
            
            # 删除 SQLite 中的记录
            conn = _get_sqlite_conn()
            conn.execute("DELETE FROM memory_fulltext WHERE id=?", [memory_id])
            conn.commit()
            
            return deleted
        except Exception:
            return False

    def clear_user_memories(self, user_id: str) -> int:
        count = 0
        
        # 清空用户记忆 collection
        user_results = self.user_collection.get(
            where={"user_id": {"$eq": user_id}},
            include=["metadatas"]
        )
        user_ids = user_results.get("ids", [])
        if user_ids:
            self.user_collection.delete(ids=user_ids)
            count += len(user_ids)
        
        # 清空知识库 collection
        kb_results = self.knowledge_collection.get(
            where={"user_id": {"$eq": user_id}},
            include=["metadatas"]
        )
        kb_ids = kb_results.get("ids", [])
        if kb_ids:
            self.knowledge_collection.delete(ids=kb_ids)
            count += len(kb_ids)
        
        # 清空 SQLite 记录
        conn = _get_sqlite_conn()
        conn.execute("DELETE FROM memory_fulltext WHERE user_id=?", [user_id])
        conn.commit()

        return count

    def get_memory_stats(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        if user_id:
            # 统计用户记忆 collection
            user_results = self.user_collection.get(
                where={"user_id": {"$eq": user_id}},
                include=[]
            )
            user_total = len(user_results.get("ids", []))
            
            # 统计知识库 collection
            kb_results = self.knowledge_collection.get(
                where={"user_id": {"$eq": user_id}},
                include=[]
            )
            kb_total = len(kb_results.get("ids", []))
            
            total = user_total + kb_total

            by_type = {}
            # 用户记忆类型
            for mtype in ["task", "question", "conversation", "preference"]:
                type_results = self.user_collection.get(
                    where={
                        "$and": [
                            {"user_id": {"$eq": user_id}},
                            {"memory_type": {"$eq": mtype}}
                        ]
                    },
                    include=[]
                )
                by_type[mtype] = len(type_results.get("ids", []))
            
            # 知识库类型
            for mtype in ["knowledge", "general"]:
                type_results = self.knowledge_collection.get(
                    where={
                        "$and": [
                            {"user_id": {"$eq": user_id}},
                            {"memory_type": {"$eq": mtype}}
                        ]
                    },
                    include=[]
                )
                by_type[mtype] = len(type_results.get("ids", []))

            return {
                "total": total,
                "by_type": by_type,
                "user_total": user_total,
                "knowledge_total": kb_total
            }
        else:
            return {"total": self.user_collection.count() + self.knowledge_collection.count()}

    def search_all_memories(
            self,
            query: str,
            memory_type: Optional[str] = None,
            user_id: Optional[str] = None,
            page: int = 1,
            page_size: int = 20
    ) -> Dict[str, Any]:
        where_filter = {}
        if memory_type:
            where_filter["memory_type"] = {"$eq": memory_type}
        if user_id:
            where_filter["user_id"] = {"$eq": user_id}

        query_embedding = self._get_embedding(query)
        total_count = self.collection.count()
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(page_size * page, total_count),
            where=where_filter if where_filter else None,
            include=["documents", "metadatas", "distances"]
        )

        memories = []
        if results["documents"] and len(results["documents"]) > 0:
            for i, doc in enumerate(results["documents"][0]):
                mem_id = results["ids"][0][i]
                metadata = results["metadatas"][0][i]
                similarity = 1 - results["distances"][0][i]

                try:
                    conn = _get_sqlite_conn()
                    row = conn.execute(
                        "SELECT full_content, created_at FROM memory_fulltext WHERE id=?",
                        [mem_id]
                    ).fetchone()
                    full_content = row[0] if row else None
                    created_at = row[1] if row else metadata.get("created_at", "")
                except Exception:
                    full_content = None
                    created_at = metadata.get("created_at", "")

                memories.append({
                    "id": mem_id,
                    "content": doc,
                    "full_content": full_content or doc,
                    "metadata": metadata,
                    "similarity": similarity,
                    "created_at": created_at
                })

        start = (page - 1) * page_size
        end = start + page_size
        return {
            "list": memories[start:end],
            "total": len(memories),
            "page": page,
            "page_size": page_size
        }

    def batch_delete_memories(
            self,
            memory_ids: List[str]
    ) -> int:
        deleted_count = 0
        for mem_id in memory_ids:
            if self.delete_memory(mem_id):
                deleted_count += 1
        return deleted_count


memory = LongTermMemory()

# 初始化 SQLite 数据库
_init_sqlite_db()
