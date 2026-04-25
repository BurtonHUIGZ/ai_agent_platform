from typing import List, Set


def calculate_recall(retrieved: List[str], expected: List[str]) -> float:
    if not expected:
        return 0.0
    retrieved_set = set(retrieved)
    expected_set = set(expected)
    return len(retrieved_set & expected_set) / len(expected_set)


def calculate_precision(retrieved: List[str], expected: List[str]) -> float:
    if not retrieved:
        return 0.0
    retrieved_set = set(retrieved)
    expected_set = set(expected)
    return len(retrieved_set & expected_set) / len(retrieved_set)


def calculate_mrr(retrieved: List[str], expected: List[str]) -> float:
    expected_set = set(expected)
    for i, doc_id in enumerate(retrieved, 1):
        if doc_id in expected_set:
            return 1.0 / i
    return 0.0


def calculate_hit_at_k(retrieved: List[str], expected: List[str], k: int = 5) -> float:
    retrieved_k = retrieved[:k]
    expected_set = set(expected)
    return 1.0 if set(retrieved_k) & expected_set else 0.0


def calculate_all_metrics(
    retrieved: List[str],
    expected: List[str],
    latency_ms: float = 0.0,
    k: int = 5
) -> dict:
    recall = calculate_recall(retrieved, expected)
    precision = calculate_precision(retrieved, expected)
    mrr = calculate_mrr(retrieved, expected)
    hit_at_k = calculate_hit_at_k(retrieved, expected, k)
    score = (recall + precision + mrr + hit_at_k) / 4
    
    return {
        "recall": recall,
        "precision": precision,
        "mrr": mrr,
        "hit_at_k": hit_at_k,
        "latency_ms": latency_ms,
        "score": score
    }