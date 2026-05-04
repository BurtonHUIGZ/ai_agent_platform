"""
防幻觉模块 - 生产级 RAG 可靠性保障
"""
import re
from typing import List, Dict, Any, Tuple


class AntiHallucination:
    def __init__(self, llm=None):
        self.llm = llm
        self._prompts = None
    
    def _load_prompts(self):
        if self._prompts is None:
            from app.agent.tasks import load_prompts
            self._prompts = load_prompts()
        return self._prompts
    
    def add_citation_prompt(self, context: str, question: str) -> str:
        """生成带引用要求的 prompt"""
        prompts = self._load_prompts()
        citation_base = prompts.get("anti_hallucination_citation", "")
        
        return f"""基于以下检索到的信息回答问题。
你必须只使用这些信息，不要添加任何外部知识。
如果信息不足以回答，请明确说明"信息不足"。

检索信息：
{context}

问题：{question}

{citation_base}

回答："""

    def extract_citations(self, response: str) -> List[str]:
        """提取回答中的引用标记"""
        pattern = r'\[来源(\d+)\]|\[source(\d+)\]|\[(\d+)\]'
        matches = re.findall(pattern, response)
        return [m[0] or m[1] or m[2] for m in matches]

    def verify_citations(self, citations: List[str], retrieved_docs: List[Dict]) -> Tuple[bool, List[str]]:
        """验证引用的文档是否存在"""
        valid_citations = []
        invalid_citations = []
        
        for cite in citations:
            cite = cite.strip()
            try:
                idx = int(cite) - 1
                if 0 <= idx < len(retrieved_docs):
                    valid_citations.append(cite)
                else:
                    invalid_citations.append(cite)
            except ValueError:
                invalid_citations.append(cite)
        
        is_valid = len(invalid_citations) == 0
        return is_valid, invalid_citations

    def calculate_faithfulness(self, response: str, context: str, query: str) -> Dict[str, Any]:
        """计算回答的可信度分数"""
        if not self.llm:
            return {
                "faithfulness": 0.5,
                "supported_claims": [],
                "unsupported_claims": [],
                "note": "无 LLM，无法进行深入验证"
            }
        
        try:
            prompts = self._load_prompts()
            faithfulness_prompt = prompts.get("anti_hallucination_faithfulness", "")
            
            prompt = faithfulness_prompt.format(
                context=context[:2000],
                response=response[:2000]
            )
            
            result = self.llm.invoke(prompt)
            result_text = result.content if hasattr(result, 'content') else str(result)
            
            supported = []
            unsupported = []
            faithfulness = 50
            
            for line in result_text.split('\n'):
                if '支持陈述' in line:
                    supported = [s.strip() for s in line.split(':')[1].split(';') if s.strip()]
                elif '不支持陈述' in line:
                    unsupported = [s.strip() for s in line.split(':')[1].split(';') if s.strip()]
                elif '可信度' in line:
                    try:
                        faith_match = re.search(r'\d+', line)
                        if faith_match:
                            faithfulness = int(faith_match.group())
                    except:
                        pass
            
            return {
                "faithfulness": faithfulness / 100.0,
                "supported_claims": supported,
                "unsupported_claims": unsupported
            }
        except Exception as e:
            return {
                "faithfulness": 0.5,
                "error": str(e)
            }

    def fact_check(self, response: str, retrieved_docs: List[Dict]) -> Dict[str, Any]:
        """事实核查 - 检查回答中的关键claim是否在文档中"""
        if not retrieved_docs:
            return {"is_valid": True, "checked_claims": [], "warnings": []}
        
        doc_contents = "\n".join([
            f"[来源{i+1}] {doc.get('content', '')}" 
            for i, doc in enumerate(retrieved_docs)
        ])
        
        if not self.llm:
            return {
                "is_valid": True,
                "checked_claims": [],
                "warnings": ["无 LLM，跳过详细事实核查"]
            }
        
        try:
            prompts = self._load_prompts()
            fact_check_prompt = prompts.get("anti_hallucination_fact_check", "")
            
            prompt = fact_check_prompt.format(
                doc_contents=doc_contents[:3000],
                response=response[:2000]
            )
            
            result = self.llm.invoke(prompt)
            result_text = result.content if hasattr(result, 'content') else str(result)
            
            is_valid = "通过" in result_text and "不通过" not in result_text
            warnings = []
            
            if "有疑问" in result_text:
                warnings.append("发现可能存在问题的陈述")
            if "不通过" in result_text:
                warnings.append("发现与参考资料不一致的陈述")
            
            return {
                "is_valid": is_valid,
                "analysis": result_text[:500],
                "warnings": warnings
            }
        except Exception as e:
            return {
                "is_valid": True,
                "error": str(e)
            }

    def validate_response(self, response: str, retrieved_docs: List[Dict], context: str) -> Dict[str, Any]:
        """综合验证回答的可靠性"""
        citations = self.extract_citations(response)
        citation_valid, invalid_citations = self.verify_citations(citations, retrieved_docs)
        faithfulness = self.calculate_faithfulness(response, context, "")
        fact_check = self.fact_check(response, retrieved_docs)
        
        overall_score = (
            (1.0 if citation_valid else 0.5) * 0.3 +
            faithfulness.get("faithfulness", 0.5) * 0.4 +
            (1.0 if fact_check.get("is_valid", True) else 0.0) * 0.3
        )
        
        return {
            "overall_score": overall_score,
            "is_reliable": overall_score >= 0.6,
            "citations": {
                "found": citations,
                "valid": citation_valid,
                "invalid": invalid_citations
            },
            "faithfulness": faithfulness,
            "fact_check": fact_check,
            "recommendation": self._get_recommendation(overall_score)
        }
    
    def _get_recommendation(self, score: float) -> str:
        if score >= 0.8:
            return "回答可靠，可直接使用"
        elif score >= 0.6:
            return "回答基本可靠，建议人工复核关键信息"
        elif score >= 0.4:
            return "回答可靠性较低，建议补充检索或人工核实"
        else:
            return "回答可能存在幻觉，建议重新检索或更换问题"


anti_hallucination = AntiHallucination()