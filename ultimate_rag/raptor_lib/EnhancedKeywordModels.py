"""
Enhanced keyword extraction with hybrid approaches and hierarchical consistency.

Improves keyword accuracy through:
1. Hybrid extraction (LLM + TF-IDF + entity extraction)
2. Hierarchical propagation (parent nodes inherit from children)
3. Semantic expansion (find variant terms)
4. Multi-factor scoring (rank by importance)
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

import numpy as np
from raptor.EmbeddingModels import BaseEmbeddingModel
from raptor.KeywordModels import (
    BaseKeywordModel,
    OpenAIKeywordModel,
    _normalize_keywords,
)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class EnhancedKeywordModel(BaseKeywordModel):
    """
    Enhanced keyword extraction combining multiple approaches.
    """

    def __init__(
        self,
        llm_model: Optional[BaseKeywordModel] = None,
        embedding_model: Optional[BaseEmbeddingModel] = None,
        use_tfidf: bool = True,
        use_entities: bool = True,
        use_semantic_expansion: bool = True,
        semantic_threshold: float = 0.85,
    ):
        """
        Initialize enhanced keyword model.

        Args:
            llm_model: LLM-based keyword extractor (default: OpenAIKeywordModel)
            embedding_model: For semantic expansion (optional)
            use_tfidf: Use TF-IDF for statistical keyword extraction
            use_entities: Extract named entities and technical terms
            use_semantic_expansion: Expand keywords with semantic variants
            semantic_threshold: Similarity threshold for semantic expansion
        """
        self.llm_model = llm_model or OpenAIKeywordModel()
        self.embedding_model = embedding_model
        self.use_tfidf = use_tfidf
        self.use_entities = use_entities
        self.use_semantic_expansion = (
            use_semantic_expansion and embedding_model is not None
        )
        self.semantic_threshold = semantic_threshold

        # Domain-specific entity patterns (can be extended)
        self.entity_patterns = [
            r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b",  # Proper nouns (e.g., "Kubernetes", "ConfigMap")
            r"\b[a-z]+-[a-z]+(?:\-[a-z]+)*\b",  # Kebab-case (e.g., "node-port", "load-balancer")
            r"\b[A-Z]+[A-Z0-9_]+\b",  # Acronyms (e.g., "API", "CRD", "PVC")
        ]

    def extract_keywords(
        self,
        text: str,
        *,
        max_keywords: int = 12,
        corpus_context: Optional[List[str]] = None,
        node_context: Optional[Dict] = None,
    ) -> List[str]:
        """
        Extract keywords using hybrid approach.

        Args:
            text: Text to extract keywords from
            max_keywords: Maximum number of keywords
            corpus_context: Optional corpus for TF-IDF calculation
            node_context: Optional node context (for hierarchical propagation)

        Returns:
            List of keywords ranked by importance
        """
        if not text or not text.strip():
            return []

        all_keywords: Set[str] = set()

        # 1. LLM extraction (semantic understanding)
        try:
            llm_keywords = self.llm_model.extract_keywords(
                text, max_keywords=max_keywords * 2
            )
            all_keywords.update(llm_keywords)
        except Exception:
            pass

        # 2. TF-IDF extraction (statistical importance)
        if self.use_tfidf:
            try:
                tfidf_keywords = self._extract_tfidf_keywords(
                    text, corpus_context, max_keywords
                )
                all_keywords.update(tfidf_keywords)
            except Exception:
                pass

        # 3. Entity extraction (named entities, technical terms)
        if self.use_entities:
            try:
                entities = self._extract_entities(text)
                all_keywords.update(entities)
            except Exception:
                pass

        # 4. Semantic expansion
        if self.use_semantic_expansion and all_keywords:
            try:
                expanded = self._semantic_expand(list(all_keywords))
                all_keywords.update(expanded)
            except Exception:
                pass

        # 5. Score and rank
        scored_keywords = self._score_keywords(
            list(all_keywords),
            text,
            corpus_context,
            node_context,
        )

        # Return top keywords
        return [kw for kw, _ in scored_keywords[:max_keywords]]

    def _extract_tfidf_keywords(
        self,
        text: str,
        corpus: Optional[List[str]] = None,
        max_keywords: int = 10,
    ) -> List[str]:
        """Extract keywords using TF-IDF."""
        if not corpus:
            corpus = [text]

        # Use n-grams (1-3 words)
        vectorizer = TfidfVectorizer(
            ngram_range=(1, 3),
            max_features=max_keywords * 2,
            stop_words="english",
            min_df=1,
        )

        try:
            # Fit on corpus + current text
            all_texts = corpus + [text]
            tfidf_matrix = vectorizer.fit_transform(all_texts)

            # Get top terms for the last document (our text)
            feature_names = vectorizer.get_feature_names_out()
            scores = tfidf_matrix[-1].toarray()[0]

            # Rank by TF-IDF score
            ranked = sorted(
                zip(feature_names, scores),
                key=lambda x: -x[1],
            )

            return [term for term, _ in ranked[:max_keywords]]
        except Exception:
            return []

    def _extract_entities(self, text: str) -> List[str]:
        """Extract named entities and technical terms."""
        entities = set()

        # Extract using patterns
        for pattern in self.entity_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                # Filter: must be 2+ chars, not all caps single word (likely acronym)
                if len(match) >= 2:
                    entities.add(match)

        # Extract technical terms (common patterns)
        # K8s resource types: ConfigMap, Secret, Deployment, etc.
        k8s_resources = re.findall(
            r"\b(ConfigMap|Secret|Deployment|StatefulSet|Service|Pod|Node|Namespace|PersistentVolume|StorageClass)\b",
            text,
            re.IGNORECASE,
        )
        entities.update(k8s_resources)

        return list(entities)[:15]  # Limit to avoid too many

    def _semantic_expand(self, keywords: List[str]) -> List[str]:
        """Expand keywords with semantic variants using embeddings."""
        if not self.embedding_model or len(keywords) < 2:
            return []

        expanded = set(keywords)

        try:
            # Get embeddings for all keywords
            keyword_embeddings = {}
            for kw in keywords:
                try:
                    emb = self.embedding_model.create_embedding(kw)
                    keyword_embeddings[kw] = np.array(emb)
                except Exception:
                    continue

            if len(keyword_embeddings) < 2:
                return list(expanded)

            # Find similar keywords
            kw_list = list(keyword_embeddings.keys())
            embeddings_matrix = np.array([keyword_embeddings[kw] for kw in kw_list])

            # Compute pairwise similarities
            similarities = cosine_similarity(embeddings_matrix)

            # Add variants (similarity > threshold)
            for i, kw1 in enumerate(kw_list):
                for j, kw2 in enumerate(kw_list):
                    if i != j and similarities[i][j] > self.semantic_threshold:
                        # If one is plural/singular variant, add both
                        if self._is_plural_variant(kw1, kw2):
                            expanded.add(kw1)
                            expanded.add(kw2)

        except Exception:
            pass

        return list(expanded)

    def _is_plural_variant(self, word1: str, word2: str) -> bool:
        """Check if two words are plural/singular variants."""
        w1_lower = word1.lower()
        w2_lower = word2.lower()

        # Simple heuristics
        if w1_lower + "s" == w2_lower or w2_lower + "s" == w1_lower:
            return True
        if w1_lower.endswith("s") and w1_lower[:-1] == w2_lower:
            return True
        if w2_lower.endswith("s") and w2_lower[:-1] == w1_lower:
            return True

        return False

    def _score_keywords(
        self,
        keywords: List[str],
        text: str,
        corpus: Optional[List[str]] = None,
        node_context: Optional[Dict] = None,
    ) -> List[tuple[str, float]]:
        """Score keywords by multiple factors."""
        scores: Dict[str, float] = {}

        text_lower = text.lower()

        for kw in keywords:
            if not kw or len(kw) < 2:
                continue

            score = 0.0
            kw_lower = kw.lower()

            # 1. TF-IDF score (if corpus available)
            if corpus:
                try:
                    vectorizer = TfidfVectorizer(
                        ngram_range=(1, 3), stop_words="english"
                    )
                    vectorizer.fit(corpus + [text])
                    if kw in vectorizer.vocabulary_:
                        tfidf_matrix = vectorizer.transform([text])
                        feature_index = vectorizer.vocabulary_[kw]
                        tfidf_score = tfidf_matrix[0, feature_index]
                        score += 0.3 * float(tfidf_score)
                except Exception:
                    pass

            # 2. Position score (titles/headings more important)
            # Check if keyword appears in headings (lines starting with #)
            heading_lines = [
                line for line in text.split("\n") if line.strip().startswith("#")
            ]
            heading_text = " ".join(heading_lines).lower()
            if kw_lower in heading_text:
                score += 0.2

            # 3. Frequency in text (normalized)
            count = text_lower.count(kw_lower)
            if count > 0:
                score += 0.15 * min(count / 10.0, 1.0)  # Cap at 10 occurrences

            # 4. Length preference (prefer phrases over single words, but not too long)
            word_count = len(kw.split())
            if 2 <= word_count <= 3:
                score += 0.15  # Prefer 2-3 word phrases
            elif word_count == 1:
                score += 0.05  # Single words less preferred

            # 5. Hierarchical consistency (if node context provided)
            if node_context:
                parent_keywords = node_context.get("parent_keywords", [])
                child_keywords = node_context.get("child_keywords", [])
                all_context_keywords = parent_keywords + child_keywords

                if kw_lower in [k.lower() for k in all_context_keywords]:
                    score += 0.2  # Boost if appears in parent/children

            scores[kw] = score

        # Sort by score
        return sorted(scores.items(), key=lambda x: -x[1])

    def synthesize_keywords(
        self,
        text: str,
        child_keywords: List[str],
        *,
        max_keywords: int = 12,
    ) -> List[str]:
        """
        Synthesize keywords for parent node from children.

        This ensures hierarchical consistency - parent keywords reflect child content.
        """
        # Combine child keywords
        child_kw_set = set(child_keywords)

        # Extract keywords from parent text
        parent_keywords = self.extract_keywords(text, max_keywords=max_keywords * 2)

        # Merge: prefer parent keywords that align with children
        merged = []
        seen = set()

        # First, add parent keywords that match or are similar to child keywords
        for pk in parent_keywords:
            pk_lower = pk.lower()
            # Check if similar to any child keyword
            for ck in child_keywords:
                ck_lower = ck.lower()
                if pk_lower == ck_lower or pk_lower in ck_lower or ck_lower in pk_lower:
                    if pk_lower not in seen:
                        merged.append(pk)
                        seen.add(pk_lower)
                        break

        # Add remaining parent keywords
        for pk in parent_keywords:
            pk_lower = pk.lower()
            if pk_lower not in seen:
                merged.append(pk)
                seen.add(pk_lower)
                if len(merged) >= max_keywords:
                    break

        # Add important child keywords not in parent
        for ck in child_keywords:
            ck_lower = ck.lower()
            if ck_lower not in seen and len(merged) < max_keywords:
                merged.append(ck)
                seen.add(ck_lower)

        return merged[:max_keywords]


def propagate_keywords_hierarchically(tree, keyword_model: EnhancedKeywordModel):
    """
    Generate keywords bottom-up for hierarchical consistency.

    This ensures parent nodes have keywords that reflect their children.
    """
    # Start from leaf nodes (layer 0) and work upward
    for layer in range(tree.num_layers):
        for node_idx in tree.layer_to_nodes.get(layer, []):
            node = tree.all_nodes[node_idx]

            if layer == 0:
                # Leaf nodes: generate fresh keywords
                try:
                    node.keywords = keyword_model.extract_keywords(node.text)
                except Exception:
                    node.keywords = []
            else:
                # Parent nodes: synthesize from children
                child_keywords = []
                for child_idx in node.children:
                    child = tree.all_nodes[child_idx]
                    child_keywords.extend(child.keywords or [])

                # Synthesize parent keywords
                try:
                    node.keywords = keyword_model.synthesize_keywords(
                        node.text,
                        child_keywords,
                    )
                except Exception:
                    # Fallback: just use child keywords
                    node.keywords = _normalize_keywords(child_keywords, max_keywords=12)
