from fastapi import APIRouter, Header, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import jieba
from app.core.memory import memory, short_term_memory
from app.core.user_system import check
from app.core.document_splitter import (
    split_document,                   # 自动识别文档类型 + 生产级分块
    production_split_text,             # 文本直接分块
    DocumentParserFactory,           # 解析器工厂
    ProductionLevelSplitter        # 备用
)
import tempfile
import os

router = APIRouter(prefix="/api/memory")


class MemorySearch(BaseModel):
    user_id: str = "default"
    query: str
    top_k: int = 5
    memory_type: Optional[str] = None


class MemoryAdd(BaseModel):
    user_id: str = "default"
    content: str
    memory_type: str = "general"
    metadata: Optional[Dict[str, Any]] = None


class MemoryDelete(BaseModel):
    memory_id: str


class MemoryBatchDelete(BaseModel):
    memory_ids: List[str]


class MemorySearchAll(BaseModel):
    query: str
    memory_type: Optional[str] = None
    user_id: Optional[str] = None
    page: int = 1
    page_size: int = 20


@router.post("/search")
def search_memories(req: MemorySearch, token: str = Header(None)):
    check(token, "memory.view")
    results = memory.hybrid_retrieve(
        user_id=req.user_id,
        query=req.query,
        top_k=req.top_k,
        user_top_k=req.top_k,
        kb_top_k=req.top_k
    )
    return {"code": 200, "data": results}


@router.post("/add")
def add_memory(req: MemoryAdd, token: str = Header(None)):
    check(token, "memory.write")
    memory_id = memory.add_memory(
        user_id=req.user_id,
        content=req.content,
        memory_type=req.memory_type,
        metadata=req.metadata
    )
    return {"code": 200, "memory_id": memory_id}


@router.get("/list/{user_id}")
def list_memories(
    user_id: str, 
    memory_type: Optional[str] = None, 
    limit: int = 20,
    offset: int = 0,
    token: str = Header(None)
):
    check(token, "memory.view")
    # 默认只返回用户记忆（不含知识库）
    result = memory.get_user_memories(user_id, memory_type, include_knowledge=False, limit=limit, offset=offset)
    return {"code": 200, "data": result["list"], "total": result["total"], "limit": result["limit"], "offset": result["offset"]}


@router.get("/knowledge/{user_id}")
def list_knowledge(
    user_id: str,
    limit: int = 20,
    offset: int = 0,
    token: str = Header(None)
):
    check(token, "memory.view")
    result = memory.get_user_memories(user_id, memory_type=None, include_knowledge=True, limit=limit, offset=offset)
    return {"code": 200, "data": result["list"], "total": result["total"], "limit": result["limit"], "offset": result["offset"]}


@router.post("/delete")
def delete_memory(req: MemoryDelete, token: str = Header(None)):
    check(token, "memory.write")
    success = memory.delete_memory(req.memory_id)
    return {"code": 200, "success": success}


@router.post("/batch_delete")
def batch_delete_memories(req: MemoryBatchDelete, token: str = Header(None)):
    check(token, "memory.write")
    deleted_count = memory.batch_delete_memories(req.memory_ids)
    return {"code": 200, "deleted_count": deleted_count}


@router.post("/search_all")
def search_all_memories(req: MemorySearchAll, token: str = Header(None)):
    check(token, "memory.view")
    result = memory.search_all_memories(
        query=req.query,
        memory_type=req.memory_type,
        user_id=req.user_id,
        page=req.page,
        page_size=req.page_size
    )
    return {"code": 200, "data": result}


class MemoryDeleteByFilter(BaseModel):
    user_id: str
    memory_type: Optional[str] = None


@router.post("/delete_by_filter")
def delete_by_filter(req: MemoryDeleteByFilter, token: str = Header(None)):
    check(token, "memory.write")
    results = memory.get_user_memories(req.user_id, req.memory_type, limit=10000)
    if results:
        ids = [m["id"] for m in results]
        deleted_count = memory.batch_delete_memories(ids)
        return {"code": 200, "deleted_count": deleted_count}
    return {"code": 200, "deleted_count": 0}


@router.post("/clear/{user_id}")
def clear_memories(user_id: str, token: str = Header(None)):
    check(token, "memory.write")
    count = memory.clear_user_memories(user_id)
    return {"code": 200, "deleted_count": count}


@router.get("/stats/{user_id}")
def get_stats(user_id: str, token: str = Header(None)):
    check(token, "memory.view")
    stats = memory.get_memory_stats(user_id)
    return {"code": 200, "data": stats}


class ShortTermContext(BaseModel):
    session_id: str
    last_n: int = 10


@router.post("/short_term/context")
def get_short_term_context(req: ShortTermContext, token: str = Header(None)):
    check(token, "memory.view")
    messages = short_term_memory.get_messages(req.session_id, req.last_n)
    return {"code": 200, "data": messages}


@router.post("/short_term/clear")
def clear_short_term_context(session_id: str = Form(...), token: str = Header(None)):
    check(token, "memory.write")
    short_term_memory.clear(session_id)
    return {"code": 200, "msg": "短期记忆已清除"}


@router.post("/short_term/add")
def add_short_term_message(
    session_id: str = Form(...),
    role: str = Form(...),
    content: str = Form(...),
    token: str = Header(None)
):
    check(token, "memory.write")
    short_term_memory.add(session_id, role, content)
    return {"code": 200, "msg": "已添加"}


def extract_text_from_file(file_path: str, file_extension: str) -> str:
    text = ""
    if file_extension == ".txt":
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
    elif file_extension == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(file_path)
            for page in reader.pages:
                text += page.extract_text() or ""
        except Exception as e:
            raise ValueError(f"PDF解析失败: {str(e)}")
    elif file_extension == ".docx":
        try:
            from docx import Document
            doc = Document(file_path)
            text = "\n".join([p.text for p in doc.paragraphs])
        except Exception as e:
            raise ValueError(f"DOCX解析失败: {str(e)}")
    else:
        raise ValueError(f"不支持的文件格式: {file_extension}")
    return text


def split_text(text: str, chunk_size: int = 500) -> List[str]:
    words = list(jieba.cut(text))
    chunks = []
    current_chunk = []
    current_len = 0

    for word in words:
        word_len = len(word)
        if word_len == 0:
            continue
        if current_len + word_len > chunk_size and current_chunk:
            chunks.append("".join(current_chunk))
            current_chunk = []
            current_len = 0
        current_chunk.append(word)
        current_len += word_len

    if current_chunk:
        chunks.append("".join(current_chunk))

    return chunks


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    user_id: str = Form("default"),
    memory_type: str = Form("knowledge"),
    token: str = Header(None)
):
    """
    上传知识库文档
    
    自动识别文档类型（PDF/TXT/DOCX/Markdown）
    自动使用生产级分块（层级感知 + 丰富元数据）
    """
    check(token, "memory.write")
    
    if not file.filename:
        return {"code": 400, "msg": "未选择文件"}
    
    file_extension = os.path.splitext(file.filename)[1].lower()
    supported = [".txt", ".pdf", ".docx", ".md", ".markdown"]
    if file_extension not in supported:
        return {"code": 400, "msg": f"不支持的文件格式，仅支持 {', '.join(supported)}"}
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        # 自动检测文档类型 + 生产级分块
        chunks = split_document(tmp_path, source_file=file.filename)
        
        if not chunks:
            return {"code": 400, "msg": "文件内容为空"}
        
        doc_type = chunks[0]["metadata"].get("doc_type", "unknown")
        
        # 批量添加
        contents = [
            (chunk["content"], {
                "source_file": file.filename,
                "memory_type": memory_type,
                **chunk.get("metadata", {})
            })
            for chunk in chunks
        ]
        
        memory_ids = memory.add_memories(user_id, contents, memory_type)
        
        return {
            "code": 200, 
            "msg": f"上传成功 (文档类型: {doc_type})", 
            "chunks": len(memory_ids),
            "doc_type": doc_type
        }
    
    except Exception as e:
        return {"code": 500, "msg": str(e)}
    finally:
        os.unlink(tmp_path)
