import logging
from types import SimpleNamespace
from typing import List, Dict

from duckduckgo_search import DDGS

logger = logging.getLogger(__name__)

def search(queries: List[str], max_results: int = 5) -> List[SimpleNamespace]:
    """Return search results for each query using DuckDuckGo."""
    ddgs = DDGS()
    results_list = []
    for q in queries:
        results: List[Dict[str, str]] = []
        try:
            for r in ddgs.text(q, max_results=max_results):
                results.append({
                    "title": r.get("title"),
                    "url": r.get("href"),
                    "snippet": r.get("body", ""),
                })
        except Exception as e:
            logger.error(f"Search error for '{q}': {e}")
        results_list.append(SimpleNamespace(results=results))
    return results_list
