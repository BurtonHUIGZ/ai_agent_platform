import time
from typing import List, Dict, Any, Optional
from datetime import datetime

from app.llm.model_factory import ModelFactory
from app.core.eval_db import eval_db
from app.core.eval_types import FeedbackRecord
from app.settings import get_model_config, settings


class RAGRealTimeEvaluator:
    """RAG实时评估器，在检索时自动触发评估"""
    
    def __init__(self):
        self.eval_llm = None
        self._enabled = True
    
    def _get_eval_llm(self):
        """延迟加载评估LLM"""
        if self.eval_llm is None:
            self.eval_llm = ModelFactory.get_eval_llm()
        return self.eval_llm
    
    def evaluate_retrieval(
        self,
        query: str,
        retrieved_docs: List[Dict[str, Any]],
        session_id: str,
        latency_ms: float
    ) -> Dict[str, Any]:
        """评估检索结果的质量"""
        if not self._enabled:
            return {"enabled": False}
        
        try:
            eval_llm = self._get_eval_llm()
            
            doc_texts = [doc.get("content", "") for doc in retrieved_docs[:5]]
            doc_count = len(retrieved_docs)
            
            prompt = f"""请评估以下RAG检索结果的质量，以JSON格式返回评分。

用户查询：{query}

检索到的文档（前5条）：
{chr(10).join([f"{i+1}. {text}" for i, text in enumerate(doc_texts)])}

请评估以下指标（0-1分）：
1. relevance: 检索文档与查询的相关性
2. completeness: 检索结果是否涵盖了查询所需的信息
3. diversity: 检索结果的多样性（避免重复内容）

返回格式：
{{"relevance": 0.8, "completeness": 0.7, "diversity": 0.9}}"""

            response = eval_llm.call(prompt)
            print(f"[RAG评估] LLM原始返回(retrieval): {response}")

            import json
            import re
            try:
                cleaned = response.strip()
                match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
                if match:
                    cleaned = match.group(1)
                else:
                    match = re.search(r'(\{.*\})', cleaned, re.DOTALL)
                    if match:
                        cleaned = match.group(1)
                decoder = json.JSONDecoder()
                scores, _ = decoder.raw_decode(cleaned)
            except Exception as e:
                print(f"[RAG评估] JSON解析失败(retrieval): {e}, 原始返回: {response}")
                scores = {"relevance": 0.5, "completeness": 0.5, "diversity": 0.5}
            
            overall_score = (
                scores.get("relevance", 0.5) * 0.5 +
                scores.get("completeness", 0.5) * 0.3 +
                scores.get("diversity", 0.5) * 0.2
            )
            
            eval_db.add_feedback(FeedbackRecord(
                session_id=session_id,
                query=query,
                response="",
                retrieved_doc_ids=[doc.get("id", "") for doc in retrieved_docs],
                retrieved_doc_count=doc_count,
                latency_ms=latency_ms
            ))
            
            return {
                "enabled": True,
                "retrieved_count": doc_count,
                "latency_ms": latency_ms,
                "scores": scores,
                "overall_score": round(overall_score, 4)
            }
            
        except Exception as e:
            print(f"[RAGRealTimeEvaluator] 评估失败: {e}")
            return {"enabled": True, "error": str(e)}
    
    def evaluate_response(
        self,
        query: str,
        response: str,
        retrieved_docs: List[Dict[str, Any]],
        session_id: str
    ) -> Dict[str, Any]:
        """评估生成的回答质量"""
        if not self._enabled:
            return {"enabled": False}
        
        try:
            eval_llm = self._get_eval_llm()
            
            doc_texts = [doc.get("content", "") for doc in retrieved_docs[:3]]
            
            prompt = f"""请评估以下RAG系统生成的回答质量，以JSON格式返回评分。

用户查询：{query}

检索到的参考文档：
{chr(10).join([f"{i+1}. {text}" for i, text in enumerate(doc_texts)])}

系统回答：
{response}

请评估以下指标（0-1分）：
1. accuracy: 回答的准确性（基于参考文档）
2. completeness: 回答是否完整
3. groundedness: 回答是否基于检索的文档（避免幻觉）
4. helpfulness: 回答对用户的帮助程度

返回格式：
{{"accuracy": 0.8, "completeness": 0.7, "groundedness": 0.9, "helpfulness": 0.8}}"""

            response_text = eval_llm.call(prompt)
            print(f"[RAG评估] LLM原始返回(response): {response_text}")

            import json
            import re
            try:
                cleaned = response_text.strip()
                match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
                if match:
                    cleaned = match.group(1)
                else:
                    match = re.search(r'(\{.*\})', cleaned, re.DOTALL)
                    if match:
                        cleaned = match.group(1)
                decoder = json.JSONDecoder()
                scores, _ = decoder.raw_decode(cleaned)
            except Exception as e:
                print(f"[RAG评估] JSON解析失败(response): {e}, 原始返回: {response_text}")
                scores = {
                    "accuracy": 0.5,
                    "completeness": 0.5,
                    "groundedness": 0.5,
                    "helpfulness": 0.5
                }
            
            overall_score = (
                scores.get("accuracy", 0.5) * 0.3 +
                scores.get("completeness", 0.5) * 0.2 +
                scores.get("groundedness", 0.5) * 0.3 +
                scores.get("helpfulness", 0.5) * 0.2
            )
            
            eval_db.update_implicit_rating(
                session_id,
                1 if overall_score >= 0.6 else 0
            )
            
            return {
                "enabled": True,
                "scores": scores,
                "overall_score": round(overall_score, 4)
            }
            
        except Exception as e:
            print(f"[RAGRealTimeEvaluator] 回答评估失败: {e}")
            return {"enabled": True, "error": str(e)}
    
    def enable(self):
        self._enabled = True
    
    def disable(self):
        self._enabled = False


rag_realtime_evaluator = RAGRealTimeEvaluator()
