from typing import List, Dict, Optional
from pydantic import BaseModel


class EvalCase(BaseModel):
    query: str
    expected_docs: List[str]
    expected_answer: Optional[str] = None
    difficulty: str = "medium"
    category: str = "general"


class EvalResult(BaseModel):
    query: str
    retrieved_docs: List[str]
    recall: float
    precision: float
    mrr: float
    hit_at_k: float
    latency_ms: float
    score: float


class FeedbackRecord(BaseModel):
    session_id: str
    query: str
    response: str
    retrieved_doc_ids: List[str]
    retrieved_doc_count: int
    latency_ms: float
    rating: Optional[int] = None
    implicit_rating: Optional[int] = None


class EvalReport(BaseModel):
    total_cases: int
    avg_recall: float
    avg_precision: float
    avg_mrr: float
    hit_at_1: float
    hit_at_3: float
    hit_at_5: float
    avg_latency_ms: float
    total_feedbacks: int
    explicit_accuracy: float
    implicit_accuracy: float
    details: List[Dict]