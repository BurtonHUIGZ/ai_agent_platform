from typing import List
from langchain_core.tools import tool
from langchain_community.tools import DuckDuckGoSearchRun
from app.core.memory import memory
from app.core.rag_eval import rag_realtime_evaluator
from app.core.metrics import metrics
from app.utils.logger import rag_logger as logger
from app.core.query_understander import query_understander
import time


@tool
def search_knowledge_base(query: str, top_k: int = 5, session_id: str = "default") -> str:
    """
    搜索知识库（RAG）获取相关信息。
    
    Args:
        query: 搜索关键词或问题
        top_k: 返回结果数量，默认5条
        session_id: 会话ID，用于评估追踪
    
    Returns:
        搜索结果列表，如果没有结果返回空字符串
    """
    try:
        start = time.time()
        query_info = query_understander.understand(query)
        query_type = query_info.get("intent", "unknown")
        
        results = memory.hybrid_retrieve(
            user_id="default",
            query=query,
            top_k=top_k,
            user_top_k=top_k,
            kb_top_k=top_k
        )
        latency_ms = (time.time() - start) * 1000
        latency_seconds = latency_ms / 1000
        
        status = "success" if results else "empty"
        metrics.record_rag_retrieval(
            user_id="default",
            status=status,
            query_type=query_type,
            latency_seconds=latency_seconds,
            doc_count=len(results)
        )
        
        if not results:
            return "知识库中未找到相关信息"
        
        formatted_results = []
        for i, item in enumerate(results, 1):
            content = item.get("content", "")
            similarity = item.get("similarity", item.get("bm25_score", 0))
            formatted_results.append(f"{i}. {content} (相关度: {similarity:.2f})")
        
        result_text = "\n\n".join(formatted_results)
        
        try:
            eval_result = rag_realtime_evaluator.evaluate_retrieval(
                query=query,
                retrieved_docs=results,
                session_id=session_id,
                latency_ms=latency_ms
            )
            logger.info(f"检索评估完成: {eval_result.get('overall_score', 'N/A')}")
        except Exception as eval_error:
            logger.warning(f"评估失败: {eval_error}")
        
        return result_text
    except Exception as e:
        return f"知识库检索失败: {str(e)}"


@tool
def search_user_memory(query: str) -> str:
    """
    搜索用户的历史记忆和偏好。
    
    Args:
        query: 搜索关键词
    
    Returns:
        用户相关记忆
    """
    try:
        results = memory.hybrid_retrieve(
            user_id="default",
            query=query,
            top_k=3,
            user_top_k=3,
            kb_top_k=3
        )
        
        if not results:
            return "未找到用户相关偏好"
        
        return "\n".join([r.get("content", "") for r in results])
    except Exception as e:
        return f"记忆检索失败: {str(e)}"


def get_rag_tools():
    """获取RAG工具列表，转换为CrewAI兼容格式"""
    return [search_knowledge_base, search_user_memory]