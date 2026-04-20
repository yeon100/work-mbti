"""Tavily Search API — optional web context for nutrition estimates."""
from __future__ import annotations

from typing import Any, Dict, List

import requests

from src.config import TAVILY_API_KEY


def tavily_search(query: str, max_results: int = 5) -> List[Dict[str, Any]]:
    if not TAVILY_API_KEY or not query.strip():
        return []
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query.strip()[:400],
                "search_depth": "basic",
                "max_results": max_results,
                "include_answer": False,
            },
            timeout=25,
        )
        resp.raise_for_status()
        data = resp.json()
        return list(data.get("results") or [])
    except Exception:
        return []


def snippets_for_diet_query(question: str, max_results: int = 4) -> str:
    q = question.strip().replace("\n", " ")[:320]
    if len(q) < 3:
        return ""
    hits = tavily_search(
        f"nutrition diet marathon runner carbohydrate protein {q}",
        max_results=max_results,
    )
    if not hits:
        return ""
    lines: List[str] = []
    for i, h in enumerate(hits[:max_results], 1):
        title = str(h.get("title", "")).strip()
        content = str(h.get("content", "")).strip()[:450]
        url = str(h.get("url", "")).strip()
        if content:
            lines.append(f"[{i}] {title}\n{content}\n출처: {url}")
    return "\n\n".join(lines)


def snippets_for_running_query(question: str, max_results: int = 4) -> str:
    """러닝/마라톤 관련 질문용 Tavily 스니펫."""
    q = question.strip().replace("\n", " ")[:320]
    if len(q) < 3:
        return ""
    hits = tavily_search(f"running marathon training {q}", max_results=max_results)
    if not hits:
        return ""
    lines: List[str] = []
    for i, h in enumerate(hits[:max_results], 1):
        title = str(h.get("title", "")).strip()
        content = str(h.get("content", "")).strip()[:450]
        url = str(h.get("url", "")).strip()
        if content:
            lines.append(f"[{i}] {title}\n{content}\n출처: {url}")
    return "\n\n".join(lines)


def snippets_for_meal(meal_text: str) -> str:
    """Build a short context string from Tavily hits for LLM consumption."""
    q = meal_text.strip().replace("\n", " ")[:200]
    if len(q) < 8:
        return ""
    hits = tavily_search(f"음식 영양 정보 칼로리 단백질 탄수화물 지방 100g {q}", max_results=5)
    if not hits:
        return ""
    lines: List[str] = []
    for i, h in enumerate(hits[:5], 1):
        title = str(h.get("title", "")).strip()
        content = str(h.get("content", "")).strip()[:500]
        url = str(h.get("url", "")).strip()
        if content:
            lines.append(f"[{i}] {title}\n{content}\n출처: {url}")
    return "\n\n".join(lines)
