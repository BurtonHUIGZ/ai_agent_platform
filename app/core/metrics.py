import time
import threading
from collections import defaultdict
from typing import Dict, Any, Optional
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST


task_total = Counter(
    'task_total',
    'Total number of tasks processed',
    ['task_type', 'status']
)

task_duration = Histogram(
    'task_duration_seconds',
    'Task processing duration in seconds',
    ['task_type'],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
)

agent_calls = Counter(
    'agent_calls_total',
    'Total number of agent calls',
    ['agent_name']
)

agent_duration = Histogram(
    'agent_duration_seconds',
    'Agent execution duration in seconds',
    ['agent_name'],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0)
)

llm_calls = Counter(
    'llm_calls_total',
    'Total number of LLM calls'
)

llm_duration = Histogram(
    'llm_duration_seconds',
    'LLM call duration in seconds',
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0)
)

rag_retrieval_total = Counter(
    'rag_retrieval_total',
    'Total number of RAG retrievals',
    ['user_id', 'status']
)

rag_retrieval_latency = Histogram(
    'rag_retrieval_latency_seconds',
    'RAG retrieval latency in seconds',
    ['query_type'],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0)
)

rag_cache_hits = Counter(
    'rag_cache_hits_total',
    'Total number of RAG cache hits'
)

rag_retrieved_docs = Histogram(
    'rag_retrieved_docs_count',
    'Number of documents retrieved per query',
    buckets=(1, 3, 5, 10, 20)
)

rag_reranker_calls = Counter(
    'rag_reranker_total',
    'Total number of reranker calls',
    ['status']
)

concurrent_tasks = Gauge(
    'concurrent_tasks',
    'Number of concurrent tasks'
)

active_sessions = Gauge(
    'active_sessions',
    'Number of active sessions'
)


class MetricsCollector:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._data: Dict[str, Any] = {
            'task_counts': defaultdict(int),
            'task_durations': defaultdict(list),
            'agent_counts': defaultdict(int),
            'agent_durations': defaultdict(list),
            'llm_counts': 0,
            'llm_total_duration': 0.0,
            'start_time': time.time(),
            'rag_counts': defaultdict(int),
            'rag_latencies': [],
            'cache_hits': 0,
        }
        self._max_history = 1000

    @classmethod
    def get_instance(cls) -> 'MetricsCollector':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def record_task(self, task_type: str, status: str, duration: float):
        task_total.labels(task_type=task_type, status=status).inc()
        task_duration.labels(task_type=task_type).observe(duration)

        self._data['task_counts'][task_type] += 1
        self._data['task_durations'][task_type].append(duration)
        if len(self._data['task_durations'][task_type]) > self._max_history:
            self._data['task_durations'][task_type] = self._data['task_durations'][task_type][-self._max_history:]

    def record_agent(self, agent_name: str, duration: float):
        agent_calls.labels(agent_name=agent_name).inc()
        agent_duration.labels(agent_name=agent_name).observe(duration)

        self._data['agent_counts'][agent_name] += 1
        self._data['agent_durations'][agent_name].append(duration)
        if len(self._data['agent_durations'][agent_name]) > self._max_history:
            self._data['agent_durations'][agent_name] = self._data['agent_durations'][agent_name][-self._max_history:]

    def record_llm(self, duration: float):
        global llm_calls, llm_duration
        llm_calls.inc()
        llm_duration.observe(duration)

        self._data['llm_counts'] += 1
        self._data['llm_total_duration'] += duration

    def inc_concurrent(self):
        concurrent_tasks.inc()

    def dec_concurrent(self):
        concurrent_tasks.dec()

    def inc_sessions(self):
        active_sessions.inc()

    def dec_sessions(self):
        active_sessions.dec()

    def record_rag_retrieval(self, user_id: str, status: str, query_type: str, latency_seconds: float, doc_count: int):
        rag_retrieval_total.labels(user_id=user_id, status=status).inc()
        rag_retrieval_latency.labels(query_type=query_type).observe(latency_seconds)
        rag_retrieved_docs.observe(doc_count)
        
        self._data['rag_counts'][status] = self._data['rag_counts'].get(status, 0) + 1
        self._data['rag_latencies'].append(latency_seconds)
        if len(self._data['rag_latencies']) > self._max_history:
            self._data['rag_latencies'] = self._data['rag_latencies'][-self._max_history:]

    def record_cache_hit(self):
        rag_cache_hits.inc()
        self._data['cache_hits'] = self._data.get('cache_hits', 0) + 1

    def record_reranker(self, status: str):
        rag_reranker_calls.labels(status=status).inc()

    def get_stats(self) -> Dict[str, Any]:
        stats = {
            'uptime': time.time() - self._data['start_time'],
            'task_counts': dict(self._data['task_counts']),
            'agent_counts': dict(self._data['agent_counts']),
            'llm_counts': self._data['llm_counts'],
            'rag_counts': dict(self._data['rag_counts']),
            'cache_hits': self._data.get('cache_hits', 0),
            'llm_avg_duration': (
                self._data['llm_total_duration'] / self._data['llm_counts']
                if self._data['llm_counts'] > 0 else 0
            ),
            'concurrent_tasks': concurrent_tasks._value.get(),
            'active_sessions': active_sessions._value.get(),
        }

        if self._data['rag_latencies']:
            stats['rag_avg_latency'] = sum(self._data['rag_latencies']) / len(self._data['rag_latencies'])
        
        cache_total = stats['rag_counts'].get('success', 0) + stats['rag_counts'].get('cache', 0)
        if cache_total > 0:
            stats['rag_cache_hit_rate'] = stats['cache_hits'] / cache_total

        for task_type, durations in self._data['task_durations'].items():
            if durations:
                stats[f'task_avg_duration_{task_type}'] = sum(durations) / len(durations)
            else:
                stats[f'task_avg_duration_{task_type}'] = 0

        for agent_name, durations in self._data['agent_durations'].items():
            if durations:
                stats[f'agent_avg_duration_{agent_name}'] = sum(durations) / len(durations)
            else:
                stats[f'agent_avg_duration_{agent_name}'] = 0

        return stats

    def get_prometheus(self) -> bytes:
        return generate_latest()


metrics = MetricsCollector.get_instance()