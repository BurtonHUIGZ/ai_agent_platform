import re
import os
from app.utils.logger import core_logger as logger
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import threading


@dataclass
class ChunkMetadata:
    """丰富的元数据结构"""
    source_file: str
    chunk_index: int
    total_chunks: int
    title: str = ""
    heading_level: int = 0
    page_num: Optional[int] = None
    section_path: str = ""
    chunk_size: int = 0
    word_count: int = 0
    created_at: str = ""
    doc_type: str = ""  # 文档类型：pdf/txt/docx/markdown

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_file": self.source_file,
            "chunk_index": self.chunk_index,
            "total_chunks": self.total_chunks,
            "title": self.title,
            "heading_level": self.heading_level,
            "page_num": self.page_num,
            "section_path": self.section_path,
            "chunk_size": self.chunk_size,
            "word_count": self.word_count,
            "created_at": self.created_at,
            "doc_type": self.doc_type
        }


@dataclass
class DocumentChunk:
    """文档块"""
    content: str
    metadata: ChunkMetadata


class DocumentParser:
    """文档解析器基类"""
    
    def extract_text(self, file_path: str) -> str:
        raise NotImplementedError
    
    def get_metadata(self, file_path: str) -> Dict[str, Any]:
        return {}


class PDFParser(DocumentParser):
    """PDF 解析器"""
    
    def extract_text(self, file_path: str) -> str:
        try:
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            pages = []
            for i, page in enumerate(reader.pages):
                text = page.extract_text()
                if text:
                    pages.append(f"--- 第{i+1}页 ---\n{text}")
            
            return "\n\n".join(pages)
        except Exception as e:
            raise ValueError(f"PDF解析失败: {e}")
    
    def get_metadata(self, file_path: str) -> Dict[str, Any]:
        try:
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            metadata = {}
            if reader.metadata:
                metadata = {
                    "title": reader.metadata.get("/Title", ""),
                    "author": reader.metadata.get("/Author", ""),
                    "page_count": len(reader.pages),
                }
            return metadata
        except:
            return {}


class DOCXParser(DocumentParser):
    """DOCX 解析器"""
    
    def extract_text(self, file_path: str) -> str:
        try:
            from docx import Document
            doc = Document(file_path)
            paragraphs = []
            for p in doc.paragraphs:
                if p.text.strip():
                    paragraphs.append(p.text)
            return "\n\n".join(paragraphs)
        except Exception as e:
            raise ValueError(f"DOCX解析失败: {e}")


class MarkdownParser(DocumentParser):
    """Markdown 解析器"""
    
    def extract_text(self, file_path: str) -> str:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            raise ValueError(f"Markdown解析失败: {e}")


class TxtParser(DocumentParser):
    """TXT 解析器"""
    
    def extract_text(self, file_path: str) -> str:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            raise ValueError(f"TXT解析失败: {e}")


class DocumentParserFactory:
    """文档解析器工厂"""
    
    _parsers: Dict[str, DocumentParser] = {
        ".pdf": PDFParser(),
        ".docx": DOCXParser(),
        ".doc": DOCXParser(),
        ".md": MarkdownParser(),
        ".markdown": MarkdownParser(),
        ".txt": TxtParser(),
    }
    
    @classmethod
    def get_parser(cls, file_path: str) -> DocumentParser:
        """根据文件扩展名获取解析器"""
        ext = os.path.splitext(file_path)[1].lower()
        parser = cls._parsers.get(ext)
        if parser is None:
            # 默认使用 TXT 解析器
            return TxtParser()
        return parser
    
    @classmethod
    def extract_text(cls, file_path: str) -> str:
        """提取文本"""
        ext = os.path.splitext(file_path)[1].lower()
        logger.info(f"[DocumentParser] 开始解析文件: {file_path}, 类型: {ext}")
        
        parser = cls.get_parser(file_path)
        text = parser.extract_text(file_path)
        
        logger.info(f"[DocumentParser] 解析完成, 文本长度: {len(text)} 字符")
        return text
    
    @classmethod
    def get_doc_type(cls, file_path: str) -> str:
        """获取文档类型"""
        ext = os.path.splitext(file_path)[1].lower()
        type_map = {
            ".pdf": "pdf",
            ".docx": "docx",
            ".doc": "docx",
            ".md": "markdown",
            ".markdown": "markdown",
            ".txt": "text"
        }
        doc_type = type_map.get(ext, "text")
        logger.info(f"[DocumentParser] 文档类型: {doc_type}")
        return doc_type


class ProductionLevelSplitter:
    """生产级文档分块器"""
    
    # Markdown 标题: ## title 或 ### title
    MD_HEADING = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    # 中文标题: 第一章, 第一节
    CN_HEADING = re.compile(r'^(第[一二三四五六七八九十\d]+[章节])')
    # 数字标题: 1.1, 1.1.1
    NUM_HEADING = re.compile(r'^(\d+\.)+\d*\s*')
    
    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        min_chunk_size: int = 100
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
    
    def split(self, text: str, source_file: str = "") -> List[DocumentChunk]:
        """分块主入口"""
        # 1. 提取标题层级结构
        heading_tree = self._extract_heading_tree(text)
        logger.info(f"[Splitter] 发现 {len(heading_tree)} 个标题")
        
        # 2. 递归分块
        chunks = self._recursive_split(text, heading_tree)
        
        # 3. 添加元数据
        doc_type = DocumentParserFactory.get_doc_type(source_file)
        result = []
        for i, chunk in enumerate(chunks):
            # 使用 chunk 中已经保存的 title
            chunk_title = chunk.get("title", "") or self._extract_title(chunk["content"])
            chunk_meta = ChunkMetadata(
                source_file=source_file,
                chunk_index=i,
                total_chunks=len(chunks),
                title=chunk_title,
                heading_level=chunk.get("heading_level", 0),
                page_num=chunk.get("page_num"),
                section_path=chunk.get("section_path", ""),
                chunk_size=len(chunk["content"]),
                word_count=self._count_words(chunk["content"]),
                created_at=datetime.now().isoformat(),
                doc_type=doc_type
            )
            result.append(DocumentChunk(content=chunk["content"], metadata=chunk_meta))
        
        return result
    
    def _extract_heading_tree(self, text: str) -> List[Dict]:
        """提取标题层级结构"""
        headings = []
        
        # Markdown 标题: ## title
        for match in self.MD_HEADING.finditer(text):
            hashes = match.group(1)
            title = match.group(2).strip()
            headings.append({
                "level": len(hashes),  # # = 1, ## = 2
                "title": title,
                "position": match.start(),
                "type": "markdown"
            })
        
        # 中文标题: 第一章, 第一节
        for match in self.CN_HEADING.finditer(text):
            title = match.group(1).strip()
            headings.append({
                "level": 1,
                "title": title,
                "position": match.start(),
                "type": "chinese"
            })
        
        # 数字标题: 1.1, 1.1.1
        for match in self.NUM_HEADING.finditer(text):
            title = match.group(0).strip()
            headings.append({
                "level": 2,
                "title": title,
                "position": match.start(),
                "type": "number"
            })
        
        headings.sort(key=lambda x: x["position"])
        return headings
    
    def _infer_level(self, title: str) -> int:
        """推断标题层级"""
        # Markdown 标题: ### text
        md_match = re.match(r'^(#+)\s+', title)
        if md_match:
            return len(md_match.group(1))
        
        # 中文标题: 第一章, 第一节
        if re.match(r'^第[一二三四五六七八九十]+章', title):
            return 1
        if re.match(r'^第[一二三四五六七八九十]+节', title):
            return 2
        
        # 数字编号: 1.1.1, 1.1
        if re.match(r'^\d+\.\d+\.\d+', title):
            return 3
        if re.match(r'^\d+\.\d+', title):
            return 2
        
        return 3  # 默认层级
    
    def _recursive_split(self, text: str, headings: List[Dict]) -> List[Dict]:
        """递归分块 - 每个标题及其内容作为一块"""
        if not headings:
            return [{"content": text, "title": "", "heading_level": 0, "section_path": "", "page_num": None}]
        
        chunks = []
        
        for i, heading in enumerate(headings):
            title = heading["title"]
            # 找到标题在文本中的位置
            title_pos = text.find(title, heading["position"])
            if title_pos == -1:
                title_pos = heading["position"]
            
            # 内容开始位置 = 标题位置 + 标题长度 + 可能的首行换行
            content_start = title_pos + len(title)
            
            # 找到内容结束位置（下一个标题或文本结尾）
            if i + 1 < len(headings):
                # 下一个标题的起始位置 - 1（去掉可能的空行）
                content_end = headings[i + 1]["position"]
            else:
                content_end = len(text)
            
            # 提取完整块 = 标题 + 内容（带标题信息）
            block_content = title  # 以标题开头
            if content_start < content_end:
                content = text[content_start:content_end].strip()
                if content:
                    block_content = f"{title}\n\n{content}"
            
            if block_content and len(block_content) > 10:
                chunks.append({
                    "content": block_content,
                    "title": title,
                    "heading_level": heading.get("level", 1),
                    "section_path": self._build_section_path(headings[:i+1]),
                    "page_num": self._estimate_page_num(text, title_pos)
                })
        
        # 如果没有分出任何块，整个文本作为一个块
        if not chunks:
            chunks = [{"content": text, "title": "", "heading_level": 0, "section_path": "", "page_num": None}]
        
        # 不再自动合并，保持每个标题独立
        return chunks
    
    def _merge_small_chunks(self, chunks: List[Dict]) -> List[Dict]:
        """合并过小的块（只合并同级别的块）"""
        if not chunks:
            return []
        
        # 按级别分组，不同级别的块不合并
        by_level = {}
        for chunk in chunks:
            level = chunk.get("heading_level", 0)
            if level not in by_level:
                by_level[level] = []
            by_level[level].append(chunk)
        
        # 合并每个级别的块
        merged = []
        for level in sorted(by_level.keys()):
            level_chunks = by_level[level]
            if not level_chunks:
                continue
            
            # 同一级别的块可以合并
            current = level_chunks[0].copy()
            for chunk in level_chunks[1:]:
                if len(current["content"]) + len(chunk["content"]) <= self.chunk_size:
                    current["content"] += "\n\n" + chunk["content"]
                else:
                    merged.append(current)
                    current = chunk.copy()
            
            merged.append(current)
        
        # 按位置排序
        merged.sort(key=lambda x: x.get("page_num", 0))
        return merged
    
    def _build_section_path(self, headings: List[Dict]) -> str:
        """构建章节路径"""
        if not headings:
            return ""
        return " > ".join([h["title"][:50] for h in headings[:3]])
    
    def _extract_title(self, content: str) -> str:
        """提取第一行作为标题"""
        lines = content.strip().split("\n")
        for line in lines:
            line = line.strip()
            # 跳过空行和太短的行
            if line and len(line) > 2:
                # 如果是纯标题符（#）,继续
                if re.match(r'^[#\s]+$', line):
                    continue
                return line[:100]
        return ""
    
    def _estimate_page_num(self, text: str, position: int) -> Optional[int]:
        """估算页码"""
        if position <= 0:
            return 1
        newlines = text[:position].count("\n")
        return newlines // 50 + 1
    
    def _count_words(self, text: str) -> int:
        """统计词数"""
        import jieba
        return len(list(jieba.cut(text)))


# 全局单例（线程安全）
_splitter_instance = None
_splitter_lock = threading.Lock()


def get_production_splitter() -> ProductionLevelSplitter:
    """获取分块器单例"""
    global _splitter_instance
    if _splitter_instance is None:
        with _splitter_lock:
            if _splitter_instance is None:
                _splitter_instance = ProductionLevelSplitter()
    return _splitter_instance


def split_document(file_path: str, source_file: str = "") -> List[Dict[str, Any]]:
    """
    自动识别文档类型并分块
    自动调用对应的解析器 + 生产级分块算法
    
    Args:
        file_path: 文件路径
        source_file: 文件名（用于元数据）
    
    Returns:
        [{"content": "...", "metadata": {...}}, ...]
    """
    logger.info(f"[DocumentSplitter] 开始处理文件: {file_path}")
    
    # 1. 解析文档
    text = DocumentParserFactory.extract_text(file_path)
    
    # 2. 获取文档类型
    doc_type = DocumentParserFactory.get_doc_type(file_path)
    logger.info(f"[DocumentSplitter] 检测到文档类型: {doc_type}")
    
    if not text or not text.strip():
        logger.warning(f"[DocumentSplitter] 文件内容为空: {file_path}")
        return []
    
    # 3. 生产级分块
    splitter = get_production_splitter()
    chunks = splitter.split(text, source_file or file_path)
    
    logger.info(f"[DocumentSplitter] 分块完成, 块数: {len(chunks)}")
    
    # 4. 转换为 dict 格式
    result = []
    for chunk in chunks:
        result.append({
            "content": chunk.content,
            "metadata": chunk.metadata.to_dict()
        })
        logger.info(f"[DocumentSplitter] Chunk {chunk.metadata.chunk_index}: "
                  f"level={chunk.metadata.heading_level}, "
                  f"title={chunk.metadata.title[:20]}")
    
    logger.info(f"[DocumentSplitter] 处理完成, 共 {len(result)} 个块")
    return result


def production_split_text(text: str, source_file: str = "") -> List[Dict[str, Any]]:
    """
    直接对文本进行生产级分块（不经过文件解析）
    """
    splitter = get_production_splitter()
    chunks = splitter.split(text, source_file)
    
    return [
        {
            "content": chunk.content,
            "metadata": chunk.metadata.to_dict()
        }
        for chunk in chunks
    ]


if __name__ == "__main__":
    import logging as stdlib_logging
    stdlib_logging.basicConfig(level=stdlib_logging.INFO, format='%(message)s')
    
    from app.core.document_splitter import production_split_text
    
    test = """# 第一章 机器学习

## 1.1 什么是机器学习

机器学习是人工智能的一个分支。

## 1.2 监督学习

监督学习需要标签数据。
"""
    
    chunks = production_split_text(test, "test.md")
    logger.info(f"分块数量: {len(chunks)}")
    for i, c in enumerate(chunks):
        logger.info(f"[{i}] {c['metadata']['title']}")