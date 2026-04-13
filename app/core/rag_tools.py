from typing import List
from langchain_core.tools import tool
from langchain_community.tools import DuckDuckGoSearchRun
from app.core.memory import memory


@tool
def search_knowledge_base(query: str, top_k: int = 5) -> str:
    """
    搜索知识库（RAG）获取相关信息。
    
    Args:
        query: 搜索关键词或问题
        top_k: 返回结果数量，默认5条
    
    Returns:
        搜索结果列表，如果没有结果返回空字符串
    """
    try:
        results = memory.retrieve_memories(
            user_id="default",
            query=query,
            top_k=top_k
        )
        
        if not results:
            return "知识库中未找到相关信息"
        
        formatted_results = []
        for i, item in enumerate(results, 1):
            content = item.get("content", "")
            similarity = item.get("similarity", 0)
            formatted_results.append(f"{i}. {content} (相关度: {similarity:.2f})")
        
        return "\n\n".join(formatted_results)
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
        results = memory.retrieve_memories(
            user_id="default",
            query=query,
            memory_type="preference",
            top_k=3
        )
        
        if not results:
            return "未找到用户相关偏好"
        
        return "\n".join([r.get("content", "") for r in results])
    except Exception as e:
        return f"记忆检索失败: {str(e)}"


def get_rag_tools():
    """获取RAG工具列表，转换为CrewAI兼容格式"""
    return [search_knowledge_base, search_user_memory]