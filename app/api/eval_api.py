from fastapi import APIRouter, Header
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from app.core.evaluator import evaluator, create_sample_dataset
from app.core.eval_types import EvalCase, EvalResult, FeedbackRecord
from app.core.eval_db import eval_db
from app.core.user_system import check
from app.core.rag_offline_eval import rag_offline_evaluator


router = APIRouter(prefix="/api/eval")

try:
    evaluator.load_test_dataset()
except Exception:
    pass


class FeedbackInput(BaseModel):
    session_id: str
    query: str
    response: str
    retrieved_doc_ids: List[str]
    retrieved_doc_count: int
    latency_ms: float


class RatingInput(BaseModel):
    session_id: str
    rating: int


class ImplicitRatingInput(BaseModel):
    session_id: str
    action: str


@router.get("/rag")
def eval_rag(top_k: int = 5, token: str = Header(None)):
    check(token, "eval.view")
    
    evaluator.top_k = top_k
    result = evaluator.evaluate_all()
    
    stats = eval_db.get_stats()
    explicit_acc = eval_db.get_accuracy(use_implicit=False)
    implicit_acc = eval_db.get_accuracy(use_implicit=True)
    
    result["total_feedbacks"] = stats["total_feedbacks"]
    result["explicit_accuracy"] = round(explicit_acc, 4)
    result["implicit_accuracy"] = round(implicit_acc, 4)
    result["avg_response_latency"] = round(stats["avg_latency_ms"], 2)
    
    return {"code": 200, "data": result}


@router.get("/rag/dataset")
def get_dataset(token: str = Header(None)):
    check(token, "eval.view")
    
    return {
        "code": 200,
        "data": {
            "total": len(evaluator.test_dataset),
            "cases": [c.model_dump() for c in evaluator.test_dataset]
        }
    }


@router.post("/rag/dataset")
def add_test_case(case: EvalCase, token: str = Header(None)):
    check(token, "eval.write")
    
    evaluator.add_test_case(case)
    evaluator.save_test_dataset()
    
    return {"code": 200, "msg": "添加成功"}


@router.delete("/rag/dataset")
def remove_test_case(query: str, token: str = Header(None)):
    check(token, "eval.write")
    
    evaluator.remove_test_case(query)
    evaluator.save_test_dataset()
    
    return {"code": 200, "msg": "删除成功"}


@router.post("/rag/dataset/load")
def load_test_dataset(token: str = Header(None)):
    check(token, "eval.write")
    
    count = evaluator.load_test_dataset()
    
    return {"code": 200, "msg": f"加载成功，共{count}条测试用例"}


@router.post("/rag/dataset/sample")
def create_sample(token: str = Header(None)):
    check(token, "eval.write")
    
    path = create_sample_dataset()
    count = evaluator.load_test_dataset()
    
    return {"code": 200, "msg": f"样例数据集创建成功，共{count}条", "path": path}


@router.post("/feedback")
def add_feedback(feedback: FeedbackInput, token: str = Header(None)):
    check(token, "eval.write")
    
    eval_db.add_feedback(FeedbackRecord(
        session_id=feedback.session_id,
        query=feedback.query,
        response=feedback.response[:500] if feedback.response else "",
        retrieved_doc_ids=feedback.retrieved_doc_ids,
        retrieved_doc_count=feedback.retrieved_doc_count,
        latency_ms=feedback.latency_ms
    ))
    
    return {"code": 200, "msg": "记录成功"}


@router.post("/feedback/rating")
def rate_interaction(rating: RatingInput, token: str = Header(None)):
    check(token, "eval.write")
    
    eval_db.update_rating(rating.session_id, rating.rating)
    
    return {"code": 200, "msg": "评分成功"}


@router.post("/feedback/implicit")
def implicit_rate_interaction(rating: ImplicitRatingInput, token: str = Header(None)):
    check(token, "eval.write")
    
    action_map = {
        "ask_followup": 1,
        "copy": 1,
        "new_topic": 0,
        "complain": 0,
        "end_session": 0
    }
    
    implicit_rating = action_map.get(rating.action, 0)
    eval_db.update_implicit_rating(rating.session_id, implicit_rating)
    
    return {"code": 200, "msg": "隐式评分记录成功"}


@router.get("/feedback")
def get_feedbacks(
    start_date: str = None,
    end_date: str = None,
    limit: int = 100,
    token: str = Header(None)
):
    check(token, "eval.view")
    
    feedbacks = eval_db.get_feedbacks(start_date, end_date, limit)
    
    return {"code": 200, "data": feedbacks}


@router.get("/feedback/stats")
def get_feedback_stats(token: str = Header(None)):
    check(token, "eval.view")
    
    stats = eval_db.get_stats()
    explicit_acc = eval_db.get_accuracy(use_implicit=False)
    implicit_acc = eval_db.get_accuracy(use_implicit=True)
    trends = eval_db.get_trends(7)
    
    return {
        "code": 200,
        "data": {
            "total": stats["total_feedbacks"],
            "explicit_count": stats["explicit_count"],
            "implicit_count": stats["implicit_count"],
            "explicit_accuracy": round(explicit_acc, 4),
            "implicit_accuracy": round(implicit_acc, 4),
            "avg_latency_ms": round(stats["avg_latency_ms"], 2),
            "trends": trends
        }
    }


class OfflineEvalInput(BaseModel):
    k: int = 5
    load_samples: bool = False


@router.post("/offline/run")
def run_offline_eval(input: OfflineEvalInput):
    if input.load_samples:
        rag_offline_evaluator.load_sample_dataset()
    
    result = rag_offline_evaluator.run_evaluation(k=input.k)
    return result


@router.get("/offline/results")
def get_offline_results():
    return {"results": rag_offline_evaluator.get_results()}