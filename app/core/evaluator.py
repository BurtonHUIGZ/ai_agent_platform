import json
import os
import time
from typing import List, Dict, Any, Optional

from app.core.memory import memory
from app.core.eval_types import EvalCase, EvalResult
from app.core.eval_metrics import calculate_all_metrics
from app.settings import BASE_DIR


class RAGEvaluator:
    def __init__(self, test_dataset: List[EvalCase] = None, top_k: int = 5):
        self.test_dataset = test_dataset or []
        self.top_k = top_k
    
    def load_test_dataset(self, json_path: str = None):
        if json_path is None:
            json_path = os.path.join(BASE_DIR, "config", "eval_dataset.json")
        
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        self.test_dataset = [EvalCase(**item) for item in data.get("test_cases", [])]
        return len(self.test_dataset)
    
    def save_test_dataset(self, json_path: str = None):
        if json_path is None:
            json_path = os.path.join(BASE_DIR, "config", "eval_dataset.json")
        
        os.makedirs(os.path.dirname(json_path), exist_ok=True)
        
        data = {"test_cases": [case.model_dump() for case in self.test_dataset]}
        
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def add_test_case(self, case: EvalCase):
        self.test_dataset.append(case)
    
    def remove_test_case(self, query: str):
        self.test_dataset = [c for c in self.test_dataset if c.query != query]
    
    def evaluate_single(self, case: EvalCase) -> EvalResult:
        start = time.time()
        
        results = memory.retrieve_memories(
            user_id="default",
            query=case.query,
            top_k=self.top_k
        )
        
        latency_ms = (time.time() - start) * 1000
        retrieved_ids = [r["id"] for r in (results or [])]
        
        metrics = calculate_all_metrics(
            retrieved_ids,
            case.expected_docs,
            latency_ms,
            self.top_k
        )
        
        return EvalResult(
            query=case.query,
            retrieved_docs=retrieved_ids,
            recall=metrics["recall"],
            precision=metrics["precision"],
            mrr=metrics["mrr"],
            hit_at_k=metrics["hit_at_k"],
            latency_ms=metrics["latency_ms"],
            score=metrics["score"]
        )
    
    def evaluate_all(self) -> Dict[str, Any]:
        if not self.test_dataset:
            return {
                "error": "测试数据集为空，请先加载测试集",
                "total_cases": 0
            }
        
        results = []
        for case in self.test_dataset:
            result = self.evaluate_single(case)
            results.append({
                "query": result.query,
                "retrieved_docs": result.retrieved_docs,
                "expected_docs": case.expected_docs,
                "recall": result.recall,
                "precision": result.precision,
                "mrr": result.mrr,
                "hit_at_k": result.hit_at_k,
                "latency_ms": result.latency_ms,
                "score": result.score,
                "difficulty": case.difficulty,
                "category": case.category
            })
        
        total = len(results)
        avg_recall = sum(r["recall"] for r in results) / total
        avg_precision = sum(r["precision"] for r in results) / total
        avg_mrr = sum(r["mrr"] for r in results) / total
        avg_latency = sum(r["latency_ms"] for r in results) / total
        avg_score = sum(r["score"] for r in results) / total
        
        hit_at_1 = sum(1 for r in results if r["mrr"] == 1.0) / total
        hit_at_3 = sum(1 for r in results if r["mrr"] >= 1/3) / total
        hit_at_5 = sum(1 for r in results if r["mrr"] >= 1/5) / total
        
        return {
            "total_cases": total,
            "avg_recall": round(avg_recall, 4),
            "avg_precision": round(avg_precision, 4),
            "avg_mrr": round(avg_mrr, 4),
            "hit_at_1": round(hit_at_1, 4),
            "hit_at_3": round(hit_at_3, 4),
            "hit_at_5": round(hit_at_5, 4),
            "avg_latency_ms": round(avg_latency, 2),
            "avg_score": round(avg_score, 4),
            "by_category": self._group_by_category(results),
            "by_difficulty": self._group_by_difficulty(results),
            "details": results
        }
    
    def _group_by_category(self, results: List[Dict]) -> Dict[str, Dict]:
        groups = {}
        for r in results:
            cat = r["category"]
            if cat not in groups:
                groups[cat] = {"total": 0, "recall": 0, "score": 0}
            groups[cat]["total"] += 1
            groups[cat]["recall"] += r["recall"]
            groups[cat]["score"] += r["score"]
        
        for cat in groups:
            total = groups[cat]["total"]
            groups[cat]["avg_recall"] = round(groups[cat]["recall"] / total, 4)
            groups[cat]["avg_score"] = round(groups[cat]["score"] / total, 4)
        
        return groups
    
    def _group_by_difficulty(self, results: List[Dict]) -> Dict[str, Dict]:
        groups = {}
        for r in results:
            diff = r["difficulty"]
            if diff not in groups:
                groups[diff] = {"total": 0, "recall": 0, "score": 0}
            groups[diff]["total"] += 1
            groups[diff]["recall"] += r["recall"]
            groups[diff]["score"] += r["score"]
        
        for diff in groups:
            total = groups[diff]["total"]
            groups[diff]["avg_recall"] = round(groups[diff]["recall"] / total, 4)
            groups[diff]["avg_score"] = round(groups[diff]["score"] / total, 4)
        
        return groups


def create_sample_dataset():
    sample_cases = [
        {
            "query": "如何安装Python环境",
            "expected_docs": ["python_install"],
            "difficulty": "easy",
            "category": "setup"
        },
        {
            "query": "系统配置要求",
            "expected_docs": ["config"],
            "difficulty": "easy",
            "category": "faq"
        },
        {
            "query": "API调用方法",
            "expected_docs": ["api_doc"],
            "difficulty": "medium",
            "category": "usage"
        }
    ]
    
    json_path = os.path.join(BASE_DIR, "config", "eval_dataset.json")
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"test_cases": sample_cases}, f, ensure_ascii=False, indent=2)
    
    return json_path


evaluator = RAGEvaluator()