import os
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
import sqlite3

from app.settings import BASE_DIR
from app.core.memory import memory
from app.core.eval_metrics import calculate_all_metrics
from app.utils.logger import rag_logger as logger


class EvalDataset:
    """评估数据集"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_dir = os.path.join(BASE_DIR, "data")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "eval_dataset.db")
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.Connection(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS eval_queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                expected_doc_ids TEXT NOT NULL,
                expected_type TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def add_query(self, query: str, expected_doc_ids: List[str], expected_type: str = None):
        conn = sqlite3.Connection(self.db_path)
        conn.execute(
            "INSERT INTO eval_queries (query, expected_doc_ids, expected_type, created_at) VALUES (?, ?, ?, ?)",
            (query, json.dumps(expected_doc_ids), expected_type, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

    def add_queries_batch(self, queries: List[Dict[str, Any]]):
        conn = sqlite3.Connection(self.db_path)
        now = datetime.now().isoformat()
        conn.executemany(
            "INSERT INTO eval_queries (query, expected_doc_ids, expected_type, created_at) VALUES (?, ?, ?, ?)",
            [(q["query"], json.dumps(q["expected_doc_ids"]), q.get("expected_type"), now) for q in queries]
        )
        conn.commit()
        conn.close()

    def get_all(self) -> List[Dict[str, Any]]:
        conn = sqlite3.Connection(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM eval_queries")
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "id": row["id"],
                "query": row["query"],
                "expected_doc_ids": json.loads(row["expected_doc_ids"]),
                "expected_type": row["expected_type"]
            }
            for row in rows
        ]

    def delete(self, query_id: int):
        conn = sqlite3.Connection(self.db_path)
        conn.execute("DELETE FROM eval_queries WHERE id=?", (query_id,))
        conn.commit()
        conn.close()

    def clear(self):
        conn = sqlite3.Connection(self.db_path)
        conn.execute("DELETE FROM eval_queries")
        conn.commit()
        conn.close()


class RAGOfflineEvaluator:
    """RAG离线评估器"""

    def __init__(self):
        self.dataset = EvalDataset()
        self.results: List[Dict[str, Any]] = []

    def load_sample_dataset(self):
        """加载示例评估数据集"""
        samples = [
            {
                "query": "如何安装Python包",
                "expected_doc_ids": ["py_install_1", "pip_doc"],
                "expected_type": "task"
            },
            {
                "query": "什么是机器学习",
                "expected_doc_ids": ["ml_def_1", "ai_intro"],
                "expected_type": "fact"
            },
            {
                "query": "怎样配置API密钥",
                "expected_doc_ids": ["api_config_1", "auth_doc"],
                "expected_type": "task"
            },
            {
                "query": "Python和Java的区别",
                "expected_doc_ids": ["py_vs_java", "lang_compare"],
                "expected_type": "fact"
            },
            {
                "query": "如何部署Docker容器",
                "expected_doc_ids": ["docker_deploy", "container_doc"],
                "expected_type": "task"
            },
            {
                "query": "RAG是什么",
                "expected_doc_ids": ["rag_def", "retrieval_ai"],
                "expected_type": "fact"
            },
            {
                "query": "怎么使用向量数据库",
                "expected_doc_ids": ["vec_db_usage", "chroma_doc"],
                "expected_type": "task"
            },
            {
                "query": "什么是嵌入向量",
                "expected_doc_ids": ["embedding_def", "vec_doc"],
                "expected_type": "fact"
            },
            {
                "query": "如何优化查询速度",
                "expected_doc_ids": ["query_opt", "perf_doc"],
                "expected_type": "task"
            },
            {
                "query": "知识图谱的作用",
                "expected_doc_ids": ["kg_purpose", "graph_doc"],
                "expected_type": "fact"
            }
        ]
        self.dataset.add_queries_batch(samples)
        logger.info(f"加载示例数据集: {len(samples)} 条")

    def run_evaluation(self, k: int = 5) -> Dict[str, Any]:
        """运行离线评估"""
        queries = self.dataset.get_all()
        
        if not queries:
            return {"error": "评估数据集为空", "total": 0}
        
        self.results = []
        total_latency = 0.0
        
        for item in queries:
            query = item["query"]
            expected = item["expected_doc_ids"]
            
            retrieved_docs = memory.hybrid_retrieve(
                user_id="eval",
                query=query,
                top_k=k,
                user_top_k=k,
                kb_top_k=k,
                use_cache=False,
                use_rerank=True,
                enable_query_understand=True
            )
            
            retrieved_ids = [doc.get("id", "") for doc in retrieved_docs]
            
            metrics = calculate_all_metrics(
                retrieved=retrieved_ids,
                expected=expected,
                latency_ms=0.0,
                k=k
            )
            
            self.results.append({
                "query": query,
                "expected": expected,
                "retrieved": retrieved_ids,
                **metrics
            })
            
            total_latency += metrics.get("latency_ms", 0)
        
        overall = self._aggregate_results(total_latency, len(queries))
        
        logger.info(f"离线评估完成: R@{k}={overall.get(f'recall@{k}')}, MRR={overall.get('mrr')}")
        
        return overall

    def _aggregate_results(self, total_latency: float, count: int) -> Dict[str, Any]:
        if not self.results:
            return {}
        
        recalls = [r.get("recall", 0) for r in self.results]
        precisions = [r.get("precision", 0) for r in self.results]
        mrrs = [r.get("mrr", 0) for r in self.results]
        hit_at_ks = [r.get("hit_at_k", 0) for r in self.results]
        
        return {
            "total": count,
            "recall": round(sum(recalls) / count, 4),
            "precision": round(sum(precisions) / count, 4),
            "mrr": round(sum(mrrs) / count, 4),
            "hit_at_k": round(sum(hit_at_ks) / count, 4),
            "avg_latency_ms": round(total_latency / count, 2),
            "details": self.results
        }

    def get_results(self) -> List[Dict[str, Any]]:
        return self.results


eval_dataset = EvalDataset()
rag_offline_evaluator = RAGOfflineEvaluator()