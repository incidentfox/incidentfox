"""
Keyword index for fast keyword-based search.

Builds an inverted index: keyword -> [node_indices]
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Set

from raptor.tree_structures import Tree


class KeywordIndex:
    """Inverted index for fast keyword-based node lookup."""

    def __init__(self, tree: Tree):
        """
        Build keyword index from tree.

        Args:
            tree: RAPTOR tree to index
        """
        # keyword (normalized) -> set of node indices
        self.index: Dict[str, Set[int]] = defaultdict(set)

        # Build index
        for node_idx, node in tree.all_nodes.items():
            if hasattr(node, "keywords") and node.keywords:
                for kw in node.keywords:
                    normalized = self._normalize_keyword(kw)
                    self.index[normalized].add(node_idx)

    def _normalize_keyword(self, keyword: str) -> str:
        """Normalize keyword for indexing (lowercase, strip)."""
        return keyword.lower().strip()

    def find_nodes(self, keywords: List[str], match_all: bool = False) -> Set[int]:
        """
        Find nodes containing the given keywords.

        Args:
            keywords: List of keywords to search for
            match_all: If True, node must contain all keywords; if False, any keyword

        Returns:
            Set of node indices
        """
        if not keywords:
            return set()

        normalized_keywords = [self._normalize_keyword(kw) for kw in keywords]

        if match_all:
            # Node must contain all keywords
            if not normalized_keywords:
                return set()

            # Start with nodes for first keyword
            result = self.index.get(normalized_keywords[0], set()).copy()

            # Intersect with nodes for other keywords
            for kw in normalized_keywords[1:]:
                result &= self.index.get(kw, set())

            return result
        else:
            # Node can contain any keyword (union)
            result = set()
            for kw in normalized_keywords:
                result |= self.index.get(kw, set())
            return result

    def find_nodes_with_scores(
        self,
        keywords: List[str],
        tree: Tree,
        match_all: bool = False,
    ) -> List[tuple[int, float]]:
        """
        Find nodes and score by keyword overlap.

        Args:
            keywords: List of keywords to search for
            tree: RAPTOR tree (for accessing node data)
            match_all: If True, node must contain all keywords

        Returns:
            List of (node_idx, score) tuples, sorted by score descending
        """
        node_indices = self.find_nodes(keywords, match_all=match_all)

        scored = []
        normalized_keywords = {self._normalize_keyword(kw) for kw in keywords}

        for node_idx in node_indices:
            node = tree.all_nodes[node_idx]
            node_keywords = {
                self._normalize_keyword(kw) for kw in (node.keywords or [])
            }

            # Score: fraction of query keywords found in node
            overlap = normalized_keywords & node_keywords
            score = (
                len(overlap) / len(normalized_keywords) if normalized_keywords else 0.0
            )

            scored.append((node_idx, score))

        # Sort by score descending
        return sorted(scored, key=lambda x: -x[1])

    def get_keyword_stats(self) -> Dict[str, int]:
        """Get statistics about keyword frequency."""
        return {kw: len(nodes) for kw, nodes in self.index.items()}

    def get_top_keywords(self, top_n: int = 20) -> List[tuple[str, int]]:
        """Get most common keywords."""
        stats = self.get_keyword_stats()
        return sorted(stats.items(), key=lambda x: -x[1])[:top_n]
