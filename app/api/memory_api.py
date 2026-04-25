from fastapi import APIRouter, Header, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import jieba
from app.core.memory import memory, short_term_memory
from app.core.user_system import check
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


@router.post("/search")
def search_memories(req: MemorySearch, token: str = Header(None)):
    check(token, "memory.view")
    results = memory.retrieve_memories(
        user_id=req.user_id,
        query=req.query,
        top_k=req.top_k,
        memory_type=req.memory_type
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
def list_memories(user_id: str, memory_type: Optional[str] = None, token: str = Header(None)):
    check(token, "memory.view")
    results = memory.get_user_memories(user_id, memory_type)
    return {"code": 200, "data": results}


@router.post("/delete")
def delete_memory(req: MemoryDelete, token: str = Header(None)):
    check(token, "memory.write")
    success = memory.delete_memory(req.memory_id)
    return {"code": 200, "success": success}


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
    check(token, "memory.write")
    
    if not file.filename:
        return {"code": 400, "msg": "未选择文件"}
    
    file_extension = os.path.splitext(file.filename)[1].lower()
    if file_extension not in [".txt", ".pdf", ".docx"]:
        return {"code": 400, "msg": "不支持的文件格式，仅支持 PDF/TXT/DOCX"}
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        text = extract_text_from_file(tmp_path, file_extension)
        
        if not text.strip():
            return {"code": 400, "msg": "文件内容为空"}
        
        chunks = split_text(text)
        
        added_count = 0
        for i, chunk in enumerate(chunks):
            memory.add_memory(
                user_id=user_id,
                content=chunk,
                memory_type=memory_type,
                metadata={
                    "source_file": file.filename,
                    "chunk_index": i,
                    "total_chunks": len(chunks)
                }
            )
            added_count += 1
        
        return {"code": 200, "msg": "上传成功", "chunks": added_count}
    
    except Exception as e:
        return {"code": 500, "msg": str(e)}
    finally:
        os.unlink(tmp_path)
