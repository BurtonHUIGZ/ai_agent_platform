from typing import List, Dict, Any, Optional
import re
from app.llm.model_factory import ModelFactory
from app.utils.logger import rag_logger as logger


class QueryUnderstander:
    """查询理解：改写、扩展、意图识别"""

    def __init__(self):
        self.eval_llm = None

    def _get_llm(self):
        if self.eval_llm is None:
            self.eval_llm = ModelFactory.get_eval_llm()
        return self.eval_llm

    def understand(self, query: str) -> Dict[str, Any]:
        """
        完整查询理解流程
        
        Returns:
            original_query: 原始查询
            rewritten_query: 改写后的查询
            expanded_query: 扩展后的查询  
            intent: 意图类型
            keywords: 关键词列表
        """
        intent = self.classify_intent(query)
        rewritten = self.rewrite_query(query, intent)
        expanded = self.expand_query(rewritten)
        keywords = self.extract_keywords(query)
        
        return {
            "original_query": query,
            "rewritten_query": rewritten,
            "expanded_query": expanded,
            "intent": intent,
            "keywords": keywords,
            "rewritten_for_search": expanded  # 综合改写用于检索
        }

    def classify_intent(self, query: str) -> str:
        """
        意图分类：task(任务执行)/question(问答)/conversation(闲聊)/fact(事实查询)
        """
        task_keywords = ["如何", "怎么", "怎样", "怎样要", "做", "完成", "创建", "编写", "配置"]
        question_keywords = ["是什么", "什么是", "为什么", "哪个", "哪些", "多少", "吗", "?"]
        fact_keywords = ["定义", "概念", "公式", "原理", "方法", "区别"]
        
        query_lower = query.lower()
        
        for kw in task_keywords:
            if kw in query:
                return "task"
        for kw in question_keywords:
            if kw in query:
                return "question"
        for kw in fact_keywords:
            if kw in query:
                return "fact"
        
        return "conversation"

    def rewrite_query(self, query: str, intent: str = None) -> str:
        """
        查询改写：口语化→规范化
        """
        if intent is None:
            intent = self.classify_intent(query)
            
        rewrites = {
            "task": [
                (r"咋(做|弄|搞)", r"如何\1"),
                (r"怎么(做|弄|搞)", r"如何\1"),
                (r"要(咋|怎么)", r"要如何"),
            ],
            "question": [
                (r"啥是", r"什么是"),
                (r"哪个(是|好)", r"哪个"),
                (r"(怎么|如何)样", r"如何"),
            ]
        }
        
        result = query
        for pattern, replacement in rewrites.get(intent, []):
            result = re.sub(pattern, replacement, result)
            
        return result

    def expand_query(self, query: str) -> str:
        """
        查询扩展：添加同义词/相关词
        """
        synonyms = {
            "配置": ["config", "设置", "配置方法", "setup", "configuration"],
            "安装": ["install", "部署", "setup", "安装方法"],
            "错误": ["error", "bug", "issue", "问题", "故障"],
            "学习": ["learn", "machine learning", "深度学习", "AI"],
            "部署": ["deploy", "部署", "发布", "上线"],
            "文档": ["doc", "documentation", "手册", "说明"],
            "API": ["api", "接口", "接口", "endpoint"],
            "数据库": ["database", "db", "数据库", "数据存储"],
            "认证": ["auth", "authentication", "登录", "授权"],
            "权限": ["permission", "权限", "access control"],
        }
        
        result = query
        for key, words in synonyms.items():
            if key in query:
                result = f"{query} {' '.join(words)}"
                
        return result

    def extract_keywords(self, query: str) -> List[str]:
        """提取关键词"""
        stopwords = {"的", "了", "在", "是", "我", "你", "他", "她", "它", "这", "那", "和", "与", "或"}
        words = re.findall(r'[\w]+', query)
        return [w for w in words if w not in stopwords and len(w) > 1]


query_understander = QueryUnderstander()