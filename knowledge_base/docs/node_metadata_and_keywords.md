# Node Metadata and Keyword System

## Node Metadata Structure

Each node in the RAPTOR tree can contain the following metadata:

### Core Node Fields
```python
class Node:
    text: str                    # The actual text content
    index: int                   # Unique node identifier
    children: Set[int]           # Child node indices
    embeddings: Dict[str, List[float]]  # Embedding vectors (per model)
    keywords: List[str]          # Extracted keywords/keyphrases
    metadata: Dict[str, Any]     # Rich metadata from ingestion
    original_content_ref: str     # Reference to original source
```

### Metadata Dictionary Structure

The `metadata` field contains a serialized `SourceMetadata` object with:

#### Source Identification
- `source_type`: Type of source ("web", "pdf", "video", "audio", "image", "api", "database", etc.)
- `source_url`: Original URL or file path
- `source_id`: Stable identifier (SHA1 hash)

#### Temporal Information
- `ingested_at`: When content was ingested (ISO datetime)
- `source_created_at`: Original creation time (if available)
- `source_modified_at`: Last modification time (if available)

#### Content Type
- `original_format`: File format ("mp4", "pdf", "png", "markdown", etc.)
- `mime_type`: MIME type ("video/mp4", "application/pdf", etc.)

#### Processing Pipeline
- `processing_steps`: List of processing steps (["web_extraction", "image_processing", "ocr"])
- `processing_model`: Model used ("whisper-large-v3", "gpt-4-vision", etc.)
- `processing_cost_usd`: Cost of processing (e.g., 0.025)
- `processing_duration_seconds`: Time taken (e.g., 2.5)

#### Provenance
- `parent_source_id`: For derived content (e.g., video transcript references parent video)
- `extraction_method`: How content was extracted ("scraping", "api", "manual_upload")

#### Quality Metrics
- `confidence_score`: Quality score (0.0-1.0) for OCR/transcription
- `language`: Detected language ("en", "es", etc.)

#### Organization
- `access_level`: Access control ("public", "private", etc.)
- `tags`: User-defined tags (["tutorial", "kubernetes", "deployment"])
- `custom_metadata`: Additional custom fields

### Example Node Metadata

```json
{
  "source_type": "video",
  "source_url": "https://example.com/tutorial.mp4",
  "source_id": "abc123...",
  "ingested_at": "2024-01-15T10:30:00Z",
  "original_format": "mp4",
  "mime_type": "video/mp4",
  "processing_steps": ["video_processing", "audio_transcription", "frame_extraction"],
  "processing_model": "whisper-1 + gpt-5.2",
  "processing_cost_usd": 0.25,
  "processing_duration_seconds": 15.3,
  "language": "en",
  "tags": ["tutorial", "kubernetes"],
  "custom_metadata": {
    "video_duration": 600,
    "video_resolution": "1920x1080"
  }
}
```

## Current Keyword Generation

### How It Works

Keywords are currently generated using **LLM calls** (primarily GPT models):

1. **OpenAIKeywordModel** (default):
   - Uses GPT model (default: gpt-5.2)
   - Prompt: "Extract keywords/keyphrases from the provided text. Return ONLY a JSON array of strings."
   - Returns 10-18 keywords per node
   - Applied to specific layers (configurable: `--keywords-min-layer`, `--keywords-max`)

2. **SimpleKeywordModel** (fallback):
   - Frequency-based extraction
   - Removes stopwords
   - No LLM calls (free but less accurate)

### Current Limitations

1. **Pure LLM approach**: No semantic understanding of keyword relationships
2. **No context awareness**: Keywords generated in isolation per node
3. **No hierarchical consistency**: Parent/child nodes may have unrelated keywords
4. **No search optimization**: Keywords not optimized for retrieval accuracy
5. **No synonym handling**: "pod" vs "pods" vs "container" treated separately
6. **No domain-specific tuning**: Generic prompts, not domain-aware

## Enhanced Keyword System Proposal

### 1. Hybrid Keyword Generation

Combine multiple approaches for better accuracy:

```python
class EnhancedKeywordModel:
    def extract_keywords(self, text, node_context=None):
        # 1. LLM extraction (semantic understanding)
        llm_keywords = self._llm_extract(text)
        
        # 2. TF-IDF extraction (statistical importance)
        tfidf_keywords = self._tfidf_extract(text, corpus_context)
        
        # 3. Entity extraction (named entities, technical terms)
        entities = self._extract_entities(text)
        
        # 4. Hierarchical propagation (inherit from children/parents)
        hierarchical = self._propagate_keywords(node_context)
        
        # 5. Merge and rank
        return self._merge_and_rank(llm_keywords, tfidf_keywords, entities, hierarchical)
```

### 2. Hierarchical Keyword Propagation

**Problem**: Parent nodes should reflect child node keywords.

**Solution**: 
- Generate keywords for leaf nodes first
- Aggregate child keywords for parent nodes
- Use LLM to synthesize parent keywords from child sets
- Maintain consistency across layers

```python
def propagate_keywords_upward(tree, keyword_model):
    """Generate keywords bottom-up for consistency."""
    # Start from leaf nodes
    for layer in range(tree.num_layers - 1, -1, -1):
        for node_idx in tree.layer_to_nodes.get(layer, []):
            node = tree.all_nodes[node_idx]
            
            if layer == 0:  # Leaf nodes
                # Generate fresh keywords
                node.keywords = keyword_model.extract_keywords(node.text)
            else:  # Parent nodes
                # Aggregate from children
                child_keywords = []
                for child_idx in node.children:
                    child = tree.all_nodes[child_idx]
                    child_keywords.extend(child.keywords)
                
                # Synthesize parent keywords from children
                node.keywords = keyword_model.synthesize_keywords(
                    node.text,
                    child_keywords=child_keywords
                )
```

### 3. Semantic Keyword Expansion

**Problem**: "pod" and "pods" are treated as different keywords.

**Solution**: Use embeddings to find semantic clusters:

```python
def expand_keywords_semantically(keywords, embedding_model):
    """Expand keywords with semantic variants."""
    expanded = set(keywords)
    
    # Get embeddings for all keywords
    keyword_embeddings = {
        kw: embedding_model.create_embedding(kw)
        for kw in keywords
    }
    
    # Find similar keywords (cosine similarity > 0.85)
    for kw1, emb1 in keyword_embeddings.items():
        for kw2, emb2 in keyword_embeddings.items():
            if kw1 != kw2:
                similarity = cosine_similarity(emb1, emb2)
                if similarity > 0.85:
                    expanded.add(kw2)  # Add variant
    
    return list(expanded)
```

### 4. Domain-Specific Keyword Extraction

**Problem**: Generic prompts don't capture domain-specific concepts.

**Solution**: Use domain-aware prompts and entity recognition:

```python
class DomainAwareKeywordModel:
    def __init__(self, domain="kubernetes"):
        self.domain = domain
        self.domain_entities = self._load_domain_entities(domain)
    
    def extract_keywords(self, text):
        # 1. Extract known domain entities
        domain_kws = self._extract_domain_entities(text)
        
        # 2. Use domain-specific LLM prompt
        llm_kws = self._llm_extract_with_domain_prompt(text)
        
        # 3. Combine
        return self._merge(domain_kws, llm_kws)
    
    def _llm_extract_with_domain_prompt(self, text):
        prompt = f"""
        Extract keywords/keyphrases from this {self.domain} documentation.
        Focus on:
        - Technical concepts and terminology
        - Resource types and API objects
        - Operational procedures
        - Configuration patterns
        
        Text: {text}
        """
        # ... LLM call
```

### 5. Keyword Scoring and Ranking

**Problem**: All keywords treated equally, but some are more important.

**Solution**: Score keywords by multiple factors:

```python
def score_keywords(keywords, text, node_context):
    """Score keywords by importance."""
    scores = {}
    
    for kw in keywords:
        score = 0.0
        
        # 1. TF-IDF score (statistical importance)
        score += 0.3 * tfidf_score(kw, text, corpus)
        
        # 2. Position score (titles/headings more important)
        score += 0.2 * position_score(kw, text)
        
        # 3. Domain relevance (domain entities weighted higher)
        score += 0.2 * domain_relevance_score(kw, domain)
        
        # 4. Hierarchical consistency (keywords in parent/children)
        score += 0.15 * hierarchical_score(kw, node_context)
        
        # 5. Length preference (prefer phrases over single words)
        score += 0.15 * length_score(kw)
        
        scores[kw] = score
    
    # Return top keywords by score
    return sorted(scores.items(), key=lambda x: -x[1])[:max_keywords]
```

### 6. Keyword-Based Search Enhancement

**Problem**: Simple keyword matching is not accurate.

**Solution**: Multi-stage search with keyword expansion:

```python
class KeywordSearchRetriever:
    def search(self, query_keywords, tree, top_k=10):
        # 1. Expand query keywords semantically
        expanded_query = self._expand_keywords(query_keywords)
        
        # 2. Find nodes with matching keywords
        candidates = self._find_by_keywords(expanded_query, tree)
        
        # 3. Score by keyword overlap + embedding similarity
        scored = []
        for node in candidates:
            keyword_score = self._keyword_match_score(expanded_query, node.keywords)
            embedding_score = self._embedding_similarity(query, node.embeddings)
            
            # Combined score (weighted)
            combined = 0.4 * keyword_score + 0.6 * embedding_score
            scored.append((node, combined))
        
        # 4. Return top-k
        return sorted(scored, key=lambda x: -x[1])[:top_k]
```

### 7. Keyword Indexing

**Problem**: Linear search through all nodes is slow.

**Solution**: Build inverted index for fast lookup:

```python
class KeywordIndex:
    def __init__(self, tree):
        # keyword -> [node_indices]
        self.index = defaultdict(list)
        
        for node_idx, node in tree.all_nodes.items():
            for kw in node.keywords:
                normalized = self._normalize(kw)
                self.index[normalized].append(node_idx)
    
    def find_nodes(self, keywords):
        """Find nodes containing any of the keywords."""
        node_sets = [set(self.index[self._normalize(kw)]) for kw in keywords]
        return set.union(*node_sets) if node_sets else set()
```

## Implementation Plan

### Phase 1: Enhanced Keyword Model
1. Implement hybrid extraction (LLM + TF-IDF + entities)
2. Add hierarchical propagation
3. Add semantic expansion

### Phase 2: Keyword Scoring
1. Implement multi-factor scoring
2. Add domain-specific weighting
3. Optimize keyword selection

### Phase 3: Search Enhancement
1. Build keyword index
2. Implement keyword-based retrieval
3. Combine with embedding search

### Phase 4: Evaluation
1. Create keyword search benchmarks
2. Measure accuracy improvements
3. Optimize based on results

## Expected Improvements

1. **Search Accuracy**: +20-30% improvement in keyword-based retrieval
2. **Consistency**: Hierarchical keywords ensure parent-child alignment
3. **Coverage**: Semantic expansion catches variant terms
4. **Performance**: Indexed search is 10-100x faster
5. **Domain Awareness**: Better handling of technical terminology

## Cost Considerations

- **Hybrid approach**: Reduces LLM calls (TF-IDF is free)
- **Batch processing**: Generate keywords for multiple nodes in one call
- **Caching**: Cache keyword embeddings for semantic expansion
- **Selective generation**: Only generate for important layers

Estimated cost increase: +10-20% (but with much better accuracy)

