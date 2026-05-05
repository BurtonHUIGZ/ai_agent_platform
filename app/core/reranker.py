from typing import List, Dict, Any, Optional
import torch
from app.utils.logger import rag_logger as logger


class CrossEncoderReranker:
    """Cross-Encoder 重排序"""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-6-256v2"):
        self.model_name = model_name
        self.model = None
        self.tokenizer = None
        self._enabled = False

    def enable(self):
        self._enabled = True

    def _load_model(self):
        if self.model is None:
            try:
                from transformers import AutoModelForSequenceClassification, AutoTokenizer
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
                self.model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
                self.model.eval()
                logger.info(f"Cross-Encoder模型加载成功: {self.model_name}")
            except Exception as e:
                logger.warning(f"Cross-Encoder模型加载失败: {e}, 将使用轻量重排")
                self._enabled = False

    def rerank(
        self, 
        query: str, 
        documents: List[Dict[str, Any]], 
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        重排序检索结果
        
        Args:
            query: 查询
            documents: 检索结果列表
            top_k: 返回数量
        
        Returns:
            重排序后的结果列表
        """
        if not documents or not self._enabled:
            return documents[:top_k]
        
        try:
            self._load_model()
        except Exception:
            return documents[:top_k]
        
        if self.model is None:
            return documents[:top_k]
        
        doc_texts = [doc.get("content", "") or doc.get("full_content", "") for doc in documents]
        doc_ids = [doc.get("id", f"doc_{i}") for i, doc in enumerate(documents)]
        
        try:
            with torch.no_grad():
                inputs = self.tokenizer(
                    [query] * len(doc_texts),
                    doc_texts,
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors="pt"
                )
                outputs = self.model(**inputs)
                scores = outputs.logits.squeeze(-1).tolist()
            
            reranked = []
            for i, (doc, score) in enumerate(zip(documents, scores)):
                new_doc = doc.copy()
                new_doc["rerank_score"] = score
                reranked.append(new_doc)
            
            reranked.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
            
            logger.info(f"重排序完成: {len(documents)} 条 -> {top_k} 条")
            return reranked[:top_k]
            
        except Exception as e:
            logger.warning(f"重排序失败: {e}")
            return documents[:top_k]

    def enable(self):
        self._enabled = True

    def disable(self):
        self._enabled = False


class LightweightReranker:
    """轻量级重排序（基于关键词匹配）"""

    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """基于关键词匹配的重排序"""
        if not documents:
            return []
        
        keywords = set(query.lower().split())
        
        reranked = []
        for doc in documents:
            content = (doc.get("content", "") or "").lower()
            keyword_matches = sum(1 for kw in keywords if kw in content)
            
            new_doc = doc.copy()
            new_doc["rerank_score"] = keyword_matches + doc.get("similarity", doc.get("rrf_score", 0))
            reranked.append(new_doc)
        
        reranked.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        
        return reranked[:top_k]


cross_encoder_reranker = CrossEncoderReranker()
lightweight_reranker = LightweightReranker()