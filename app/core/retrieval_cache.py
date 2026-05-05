from typing import List, Dict, Any, Optional
import hashlib
import time
from collections import OrderedDict
from app.utils.logger import rag_logger as logger


class RetrievalCache:
    """检索结果缓存 (LRU)"""

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict = OrderedDict()
        self._timestamps: Dict[str, float] = {}

    def _make_key(self, query: str, user_id: str = "default") -> str:
        """生成缓存key"""
        key_str = f"{user_id}:{query.lower().strip()}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def get(self, query: str, user_id: str = "default") -> Optional[List[Dict[str, Any]]]:
        """获取缓存结果"""
        key = self._make_key(query, user_id)
        
        if key not in self._cache:
            return None
        
        timestamp = self._timestamps.get(key, 0)
        if time.time() - timestamp > self.ttl_seconds:
            self._delete(key)
            return None
        
        self._cache.move_to_end(key)
        logger.info(f"缓存命中: {query[:30]}...")
        return self._cache[key]

    def set(self, query: str, results: List[Dict[str, Any]], user_id: str = "default"):
        """设置缓存结果"""
        key = self._make_key(query, user_id)
        
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self.max_size:
                oldest_key = next(iter(self._cache))
                self._delete(oldest_key)
            
            self._cache[key] = results
            self._timestamps[key] = time.time()
        
        logger.info(f"缓存写入: {query[:30]}...")

    def _delete(self, key: str):
        """删除缓存"""
        if key in self._cache:
            del self._cache[key]
        if key in self._timestamps:
            del self._timestamps[key]

    def invalidate(self, query: str = None, user_id: str = "default"):
        """使缓存失效"""
        if query:
            key = self._make_key(query, user_id)
            self._delete(key)
        else:
            self._cache.clear()
            self._timestamps.clear()

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "ttl_seconds": self.ttl_seconds
        }


retrieval_cache = RetrievalCache()