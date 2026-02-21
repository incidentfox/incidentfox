import logging
import re
from typing import Dict, List, Set

import numpy as np
import tiktoken
from scipy import spatial

from .tree_structures import Node

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)


def _tok_len(tokenizer, s: str) -> int:
    return len(tokenizer.encode(s or ""))


def _chunk_by_token_budget(
    parts: List[str],
    tokenizer,
    max_tokens: int,
    *,
    overlap_tokens: int = 0,
) -> List[str]:
    """
    Given a sequence of text parts (already in a good order), pack them into chunks
    with a max token budget. Optionally keep a small token overlap between chunks.
    """
    if max_tokens < 1:
        raise ValueError("max_tokens must be >= 1")
    overlap_tokens = max(0, int(overlap_tokens))

    chunks: List[str] = []
    cur: List[str] = []
    cur_toks = 0

    for p in parts:
        p = (p or "").strip()
        if not p:
            continue
        pt = _tok_len(tokenizer, p)
        # If a single part is too big, fall back to the legacy splitter for that part.
        if pt > max_tokens:
            # Reuse the existing splitter to avoid pathological huge blocks.
            for sub in split_text(p, tokenizer, max_tokens, overlap=0):
                sub = sub.strip()
                if sub:
                    chunks.append(sub)
            cur = []
            cur_toks = 0
            continue

        if cur and (cur_toks + pt > max_tokens):
            chunks.append("\n\n".join(cur).strip())
            if overlap_tokens > 0:
                # Keep overlap by tokens from the end of the previous chunk.
                tail = chunks[-1]
                toks = tokenizer.encode(tail)
                toks = toks[-overlap_tokens:]
                carry = tokenizer.decode(toks).strip()
                cur = [carry] if carry else []
                cur_toks = _tok_len(tokenizer, carry)
            else:
                cur = []
                cur_toks = 0

        cur.append(p)
        cur_toks += pt

    if cur:
        chunks.append("\n\n".join(cur).strip())

    return [c for c in chunks if c.strip()]


def split_markdown_semantic(
    text: str,
    tokenizer: tiktoken.get_encoding("cl100k_base"),
    max_tokens: int,
    *,
    overlap_tokens: int = 40,
) -> List[str]:
    """
    A structure/semantic-aware splitter for Markdown-ish docs.

    Heuristics (fast, no extra model calls):
    - Split at headings (#, ##, ###...) to keep sections intact
    - Keep fenced code blocks (```...```) as atomic parts (do not split inside)
    - Pack parts into chunks by token budget with small overlap

    This usually produces much more coherent chunks for docs than sentence-only splitting.
    """
    s = (text or "").replace("\r\n", "\n")
    if not s.strip():
        return []

    lines = s.split("\n")
    parts: List[str] = []
    buf: List[str] = []
    in_fence = False

    heading_re = re.compile(r"^\s{0,3}#{1,6}\s+\S")
    fence_re = re.compile(r"^\s*```")

    def flush():
        nonlocal buf
        if buf:
            parts.append("\n".join(buf).strip())
            buf = []

    for line in lines:
        if fence_re.match(line):
            # Toggle fence state; keep fence markers with the code block.
            buf.append(line)
            if not in_fence:
                in_fence = True
            else:
                in_fence = False
            continue

        if not in_fence and heading_re.match(line):
            # Start a new semantic unit at each heading.
            flush()
            buf.append(line)
            continue

        buf.append(line)

    flush()

    # Pack semantic parts into token-bounded chunks.
    return _chunk_by_token_budget(
        parts, tokenizer, max_tokens, overlap_tokens=overlap_tokens
    )


def _unitize_text(text: str, unit: str) -> List[str]:
    s = (text or "").replace("\r\n", "\n")
    if not s.strip():
        return []
    unit = (unit or "").strip().lower()
    if unit == "paragraph":
        # Split on blank lines; keep paragraphs intact.
        paras = [p.strip() for p in re.split(r"\n\s*\n+", s) if p.strip()]
        return paras
    if unit == "sentence":
        # Simple sentence split; keeps newlines as boundaries.
        # (We don't use a heavy NLP model here to keep it fast/offline-friendly.)
        sentences = re.split(r"(?<=[\.!\?])\s+|\n+", s)
        return [x.strip() for x in sentences if x.strip()]
    raise ValueError("unit must be one of: sentence, paragraph")


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float32).reshape(-1)
    b = np.asarray(b, dtype=np.float32).reshape(-1)
    na = float(np.linalg.norm(a) + 1e-12)
    nb = float(np.linalg.norm(b) + 1e-12)
    return float(np.dot(a, b) / (na * nb))


def split_semantic_embedding(
    text: str,
    tokenizer: tiktoken.get_encoding("cl100k_base"),
    max_tokens: int,
    *,
    embedder,
    unit: str = "sentence",
    overlap_tokens: int = 40,
    similarity_threshold: float = 0.78,
    adaptive_threshold: bool = True,
    min_chunk_tokens: int = 120,
    max_units: int = 4000,
) -> List[str]:
    """
    "True semantic" chunking using embeddings to find topic shifts.

    How it works:
    - Split text into units (sentences or paragraphs)
    - Embed each unit
    - Compute cosine similarity between adjacent units
    - Start a new chunk when similarity drops below a threshold (topic shift)
    - Also respect token budget packing + overlap

    Notes:
    - This makes extra embedding calls (one per unit). Use a cache-backed embedder to keep it affordable.
    - This is still heuristic (no LLM calls), but usually much more coherent than sentence-length chunking.
    """
    if embedder is None:
        raise ValueError("embedder is required for semantic chunking")
    if max_tokens < 1:
        raise ValueError("max_tokens must be >= 1")

    units = _unitize_text(text, unit=unit)
    if not units:
        return []
    if len(units) > int(max_units):
        units = units[: int(max_units)]

    # Pre-embed units (cache makes this cheap on reruns).
    embs: List[np.ndarray] = []
    for u in units:
        e = embedder.create_embedding(u)
        embs.append(np.asarray(e, dtype=np.float32))

    sims: List[float] = []
    for i in range(len(embs) - 1):
        sims.append(_cosine_sim(embs[i], embs[i + 1]))

    # Adaptive cutoff helps across very different documents.
    cutoff = float(similarity_threshold)
    if adaptive_threshold and sims:
        mu = float(np.mean(sims))
        sigma = float(np.std(sims))
        # "low similarity" typically means topic shift; be at least as strict as (mu - 0.5*sigma)
        cutoff = min(cutoff, mu - 0.5 * sigma)
        cutoff = max(0.0, min(0.99, cutoff))

    # Build semantic segments (before token packing).
    segments: List[List[str]] = []
    cur: List[str] = []
    cur_tokens = 0

    def flush_segment():
        nonlocal cur, cur_tokens
        if cur:
            segments.append(cur)
        cur = []
        cur_tokens = 0

    for i, u in enumerate(units):
        ut = _tok_len(tokenizer, u)
        # Respect max token budget while assembling
        if cur and (cur_tokens + ut > max_tokens):
            flush_segment()
        cur.append(u)
        cur_tokens += ut

        # If next unit looks like a topic shift and we have enough substance, cut here.
        if i < len(sims) and sims[i] < cutoff:
            if cur_tokens >= int(min_chunk_tokens):
                flush_segment()

    flush_segment()

    # Pack segments into chunks by token budget (keeps overlap).
    parts = [" ".join(seg).strip() for seg in segments if seg]
    return _chunk_by_token_budget(
        parts, tokenizer, max_tokens, overlap_tokens=overlap_tokens
    )


def reverse_mapping(layer_to_nodes: Dict[int, List[Node]]) -> Dict[Node, int]:
    node_to_layer = {}
    for layer, nodes in layer_to_nodes.items():
        for node in nodes:
            node_to_layer[node.index] = layer
    return node_to_layer


def split_text(
    text: str,
    tokenizer: tiktoken.get_encoding("cl100k_base"),
    max_tokens: int,
    overlap: int = 0,
):
    """
    Splits the input text into smaller chunks based on the tokenizer and maximum allowed tokens.

    Args:
        text (str): The text to be split.
        tokenizer (CustomTokenizer): The tokenizer to be used for splitting the text.
        max_tokens (int): The maximum allowed tokens.
        overlap (int, optional): The number of overlapping tokens between chunks. Defaults to 0.

    Returns:
        List[str]: A list of text chunks.
    """
    # Split the text into sentences using multiple delimiters
    delimiters = [".", "!", "?", "\n"]
    regex_pattern = "|".join(map(re.escape, delimiters))
    sentences = re.split(regex_pattern, text)

    # Calculate the number of tokens for each sentence
    n_tokens = [len(tokenizer.encode(" " + sentence)) for sentence in sentences]

    chunks = []
    current_chunk = []
    current_length = 0

    for sentence, token_count in zip(sentences, n_tokens):
        # If the sentence is empty or consists only of whitespace, skip it
        if not sentence.strip():
            continue

        # If the sentence is too long, split it into smaller parts
        if token_count > max_tokens:
            sub_sentences = re.split(r"[,;:]", sentence)

            # there is no need to keep empty os only-spaced strings
            # since spaces will be inserted in the beginning of the full string
            # and in between the string in the sub_chuk list
            filtered_sub_sentences = [
                sub.strip() for sub in sub_sentences if sub.strip() != ""
            ]
            sub_token_counts = [
                len(tokenizer.encode(" " + sub_sentence))
                for sub_sentence in filtered_sub_sentences
            ]

            sub_chunk = []
            sub_length = 0

            for sub_sentence, sub_token_count in zip(
                filtered_sub_sentences, sub_token_counts
            ):
                if sub_length + sub_token_count > max_tokens:

                    # if the phrase does not have sub_sentences, it would create an empty chunk
                    # this big phrase would be added anyways in the next chunk append
                    if sub_chunk:
                        chunks.append(" ".join(sub_chunk))
                        sub_chunk = sub_chunk[-overlap:] if overlap > 0 else []
                        sub_length = sum(
                            sub_token_counts[
                                max(0, len(sub_chunk) - overlap) : len(sub_chunk)
                            ]
                        )

                sub_chunk.append(sub_sentence)
                sub_length += sub_token_count

            if sub_chunk:
                chunks.append(" ".join(sub_chunk))

        # If adding the sentence to the current chunk exceeds the max tokens, start a new chunk
        elif current_length + token_count > max_tokens:
            chunks.append(" ".join(current_chunk))
            current_chunk = current_chunk[-overlap:] if overlap > 0 else []
            current_length = sum(
                n_tokens[max(0, len(current_chunk) - overlap) : len(current_chunk)]
            )
            current_chunk.append(sentence)
            current_length += token_count

        # Otherwise, add the sentence to the current chunk
        else:
            current_chunk.append(sentence)
            current_length += token_count

    # Add the last chunk if it's not empty
    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


def distances_from_embeddings(
    query_embedding: List[float],
    embeddings: List[List[float]],
    distance_metric: str = "cosine",
) -> List[float]:
    """
    Calculates the distances between a query embedding and a list of embeddings.

    Args:
        query_embedding (List[float]): The query embedding.
        embeddings (List[List[float]]): A list of embeddings to compare against the query embedding.
        distance_metric (str, optional): The distance metric to use for calculation. Defaults to 'cosine'.

    Returns:
        List[float]: The calculated distances between the query embedding and the list of embeddings.
    """
    distance_metrics = {
        "cosine": spatial.distance.cosine,
        "L1": spatial.distance.cityblock,
        "L2": spatial.distance.euclidean,
        "Linf": spatial.distance.chebyshev,
    }

    if distance_metric not in distance_metrics:
        raise ValueError(
            f"Unsupported distance metric '{distance_metric}'. Supported metrics are: {list(distance_metrics.keys())}"
        )

    distances = [
        distance_metrics[distance_metric](query_embedding, embedding)
        for embedding in embeddings
    ]

    return distances


def get_node_list(node_dict: Dict[int, Node]) -> List[Node]:
    """
    Converts a dictionary of node indices to a sorted list of nodes.

    Args:
        node_dict (Dict[int, Node]): Dictionary of node indices to nodes.

    Returns:
        List[Node]: Sorted list of nodes.
    """
    indices = sorted(node_dict.keys())
    node_list = [node_dict[index] for index in indices]
    return node_list


def get_embeddings(node_list: List[Node], embedding_model: str) -> List:
    """
    Extracts the embeddings of nodes from a list of nodes.

    Args:
        node_list (List[Node]): List of nodes.
        embedding_model (str): The name of the embedding model to be used.

    Returns:
        List: List of node embeddings.
    """
    return [node.embeddings[embedding_model] for node in node_list]


def get_children(node_list: List[Node]) -> List[Set[int]]:
    """
    Extracts the children of nodes from a list of nodes.

    Args:
        node_list (List[Node]): List of nodes.

    Returns:
        List[Set[int]]: List of sets of node children indices.
    """
    return [node.children for node in node_list]


def get_text(node_list: List[Node]) -> str:
    """
    Generates a single text string by concatenating the text from a list of nodes.

    Args:
        node_list (List[Node]): List of nodes.

    Returns:
        str: Concatenated text.
    """
    text = ""
    for node in node_list:
        text += f"{' '.join(node.text.splitlines())}"
        text += "\n\n"
    return text


def get_text_with_citations(node_list: List[Node]) -> tuple:
    """
    Generates context text with [N] source labels for citation-aware QA.

    Each unique source gets a number [1], [2], etc. The context includes
    the source label and URL before each chunk.

    Args:
        node_list (List[Node]): List of nodes.

    Returns:
        tuple: (formatted_context, citations_list)
            - formatted_context: str with [N] labels
            - citations_list: list of {"index": N, "source": URL, "rel_path": path, "node_ids": [...]}
    """
    # Track unique sources and assign numbers
    source_to_index = {}  # source_url -> index
    citations = []  # list of citation dicts

    def get_source_index(node) -> int:
        """Get or assign a citation index for this node's source."""
        md = getattr(node, "metadata", None) or {}
        source = (
            md.get("source_url")
            or md.get("original_content_ref")
            or getattr(node, "original_content_ref", None)
        )
        rel_path = md.get("rel_path")

        if not source:
            return None

        source_str = str(source)
        if source_str in source_to_index:
            # Add node_id to existing citation
            idx = source_to_index[source_str]
            citations[idx - 1]["node_ids"].append(node.index)
            return idx

        # New source - assign next index
        idx = len(citations) + 1
        source_to_index[source_str] = idx
        citations.append(
            {
                "index": idx,
                "source": source_str,
                "rel_path": rel_path,
                "node_ids": [node.index],
            }
        )
        return idx

    # Build formatted context
    parts = []
    for node in node_list:
        idx = get_source_index(node)
        text = " ".join(node.text.splitlines())

        if idx:
            source = citations[idx - 1]["source"]
            # Shorten source for display (keep domain + path)
            short_source = source
            if len(short_source) > 80:
                short_source = short_source[:77] + "..."
            parts.append(f"[{idx}] {short_source}\n{text}")
        else:
            parts.append(text)

    formatted_context = "\n\n".join(parts)
    return formatted_context, citations


_PROVENANCE_HEADER_RE = re.compile(
    r"^\s*#\s+\S+\s*\n\s*Source:\s*\S+\s*\n+",
    re.MULTILINE,
)
_HUGO_SHORTCODE_RE = re.compile(r"\{\{<[^>]*>\}\}|\{\{%[^%]*%\}\}", re.MULTILINE)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def strip_provenance_and_shortcodes(text: str) -> str:
    """
    Remove repetitive provenance headers (added by ingest scripts) and noisy doc shortcodes
    from text used for *summarization/clustering context*.

    Important: this does NOT mutate stored node text; it's only used to build summarization context
    so higher-layer summaries don't become dominated by headers like:
      # concepts/...\\nSource: https://...\\n
    """
    s = (text or "").strip()
    if not s:
        return ""
    # Drop the common per-doc header if present
    s = _PROVENANCE_HEADER_RE.sub("", s, count=1).strip()
    # Remove Hugo shortcodes / templating that often pollute summaries
    s = _HUGO_SHORTCODE_RE.sub("", s)
    # Remove HTML comments like <!-- overview -->
    s = _HTML_COMMENT_RE.sub("", s)
    # Normalize whitespace a bit
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def get_text_for_summary(node_list: List[Node]) -> str:
    """
    Like get_text(), but strips provenance headers + shortcodes so parent summaries are more abstractive
    and less likely to copy doc headers verbatim.
    """
    parts: List[str] = []
    for node in node_list:
        cleaned = strip_provenance_and_shortcodes(node.text)
        if cleaned:
            parts.append(" ".join(cleaned.splitlines()))
    return "\n\n".join(parts)


def indices_of_nearest_neighbors_from_distances(distances: List[float]) -> np.ndarray:
    """
    Returns the indices of nearest neighbors sorted in ascending order of distance.

    Args:
        distances (List[float]): A list of distances between embeddings.

    Returns:
        np.ndarray: An array of indices sorted by ascending distance.
    """
    return np.argsort(distances)
