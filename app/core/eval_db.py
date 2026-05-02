import sqlite3
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import contextmanager

from app.settings import BASE_DIR
from app.core.eval_types import FeedbackRecord


class EvalDB:
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_dir = os.path.join(BASE_DIR, "data")
            os.makedirs(db_dir, exist_ok=True)
            db_path = os.path.join(db_dir, "eval.db")
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    response TEXT,
                    retrieved_doc_ids TEXT,
                    retrieved_doc_count INTEGER,
                    latency_ms REAL,
                    rating INTEGER,
                    implicit_rating INTEGER,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_feedback_session 
                ON feedback(session_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_feedback_created 
                ON feedback(created_at)
            """)
            conn.commit()
    
    @contextmanager
    def _get_conn(self):
        conn = sqlite3.Connection(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def add_feedback(self, record: FeedbackRecord):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO feedback 
                (session_id, query, response, retrieved_doc_ids, 
                 retrieved_doc_count, latency_ms, rating, implicit_rating, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.session_id,
                    record.query,
                    record.response,
                    ",".join(record.retrieved_doc_ids),
                    record.retrieved_doc_count,
                    record.latency_ms,
                    record.rating,
                    record.implicit_rating,
                    datetime.now().isoformat()
                )
            )
            conn.commit()
    
    def update_rating(self, session_id: str, rating: int):
        with self._get_conn() as conn:
            cursor = conn.execute(
                """SELECT id FROM feedback 
                WHERE session_id = ? AND rating IS NULL
                ORDER BY created_at DESC LIMIT 1""",
                (session_id,)
            )
            row = cursor.fetchone()
            if row:
                conn.execute(
                    "UPDATE feedback SET rating = ? WHERE id = ?",
                    (rating, row[0])
                )
                conn.commit()
    
    def update_implicit_rating(self, session_id: str, implicit_rating: int):
        with self._get_conn() as conn:
            cursor = conn.execute(
                """SELECT id FROM feedback 
                WHERE session_id = ? AND implicit_rating IS NULL
                ORDER BY created_at DESC LIMIT 1""",
                (session_id,)
            )
            row = cursor.fetchone()
            if row:
                conn.execute(
                    "UPDATE feedback SET implicit_rating = ? WHERE id = ?",
                    (implicit_rating, row[0])
                )
                conn.commit()
    
    def get_feedbacks(
        self,
        start_date: str = None,
        end_date: str = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            query = "SELECT * FROM feedback WHERE 1=1"
            params = []
            
            if start_date:
                query += " AND created_at >= ?"
                params.append(start_date)
            if end_date:
                query += " AND created_at <= ?"
                params.append(end_date)
            
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                results.append({
                    "id": row["id"],
                    "session_id": row["session_id"],
                    "query": row["query"],
                    "response": row["response"],
                    "retrieved_doc_ids": row["retrieved_doc_ids"].split(",") if row["retrieved_doc_ids"] else [],
                    "retrieved_doc_count": row["retrieved_doc_count"],
                    "latency_ms": row["latency_ms"],
                    "rating": row["rating"],
                    "implicit_rating": row["implicit_rating"],
                    "created_at": row["created_at"]
                })
            
            return results
    
    def get_accuracy(self, use_implicit: bool = False) -> float:
        with self._get_conn() as conn:
            column = "implicit_rating" if use_implicit else "rating"
            cursor = conn.execute(
                f"""SELECT COUNT(*) as total, 
                      SUM(CASE WHEN {column} = 1 THEN 1 ELSE 0 END) as positive
                      FROM feedback 
                      WHERE {column} IS NOT NULL"""
            )
            row = cursor.fetchone()
            if row["total"] == 0:
                return 0.0
            return row["positive"] / row["total"]
    
    def get_trends(self, days: int = 7) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """SELECT DATE(created_at) as date,
                      COUNT(*) as total,
                      AVG(latency_ms) as avg_latency,
                      SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as positive,
                      SUM(CASE WHEN implicit_rating = 1 THEN 1 ELSE 0 END) as implicit_positive
                      FROM feedback
                      WHERE created_at >= DATE('now', '-' || ? || ' days')
                      GROUP BY DATE(created_at)
                      ORDER BY date""",
                (days,)
            )
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                total = row["total"]
                results.append({
                    "date": row["date"],
                    "total": total,
                    "avg_latency_ms": row["avg_latency"],
                    "explicit_accuracy": row["positive"] / total if total > 0 else 0.0,
                    "implicit_accuracy": row["implicit_positive"] / total if total > 0 else 0.0
                })
            
            return results
    
    def get_stats(self) -> Dict[str, Any]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """SELECT 
                      COUNT(*) as total_feedbacks,
                      SUM(CASE WHEN rating IS NOT NULL THEN 1 ELSE 0 END) as explicit_count,
                      SUM(CASE WHEN implicit_rating IS NOT NULL THEN 1 ELSE 0 END) as implicit_count,
                      AVG(latency_ms) as avg_latency
                      FROM feedback"""
            )
            row = cursor.fetchone()
            
            return {
                "total_feedbacks": row["total_feedbacks"] or 0,
                "explicit_count": row["explicit_count"] or 0,
                "implicit_count": row["implicit_count"] or 0,
                "avg_latency_ms": row["avg_latency"] or 0.0
            }


eval_db = EvalDB()