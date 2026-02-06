# Multimodal Ingestion Layer - Feasibility Assessment

## Executive Summary

**Feasibility: ✅ HIGHLY FEASIBLE**

A multimodal ingestion layer is not only feasible but would significantly enhance the knowledge base system. Modern AI APIs (OpenAI, Anthropic, Google) provide excellent multimodal capabilities, and the existing RAPTOR architecture can accommodate enriched metadata.

## Current State

### Existing Ingestion Pipeline
- **Input Format**: JSONL with `{id, rel_path, source_url, text}`
- **Processing**: Text → Chunks → Embeddings → Tree
- **Metadata**: Minimal (source_url, rel_path)
- **Node Structure**: `{text, index, children, embeddings, keywords}`

### Limitations
- Text-only ingestion
- No source type tracking
- No processing history/audit trail
- No multimodal content support

## Proposed Architecture

### 1. Enhanced Metadata Model

```python
@dataclass
class SourceMetadata:
    """Rich metadata preserved throughout ingestion"""
    # Source identification
    source_type: str  # "web", "pdf", "video", "audio", "image", "api", "slack", etc.
    source_url: str
    source_id: str  # Stable identifier (hash or UUID)
    
    # Temporal
    ingested_at: datetime
    source_created_at: Optional[datetime]
    source_modified_at: Optional[datetime]
    
    # Content type
    original_format: str  # "mp4", "pdf", "png", "markdown", etc.
    mime_type: str
    
    # Processing pipeline
    processing_steps: List[str]  # ["download", "transcribe", "ocr", "summarize"]
    processing_model: Optional[str]  # "whisper-large-v3", "gpt-4-vision", etc.
    processing_cost_usd: Optional[float]
    processing_duration_seconds: Optional[float]
    
    # Provenance
    parent_source_id: Optional[str]  # For derived content (e.g., video → transcript)
    extraction_method: str  # "scraping", "api", "manual_upload", etc.
    
    # Quality/Confidence
    confidence_score: Optional[float]  # For OCR/transcription confidence
    language: Optional[str]  # Detected language
    
    # Access control (future)
    access_level: str = "public"
    tags: List[str] = field(default_factory=list)
```

### 2. Enhanced Node Structure

```python
class Node:
    def __init__(
        self,
        text: str,
        index: int,
        children: Set[int],
        embeddings,
        keywords: Optional[List[str]] = None,
        metadata: Optional[SourceMetadata] = None,  # NEW
        original_content_ref: Optional[str] = None,  # Reference to original file
    ):
        # ... existing fields ...
        self.metadata = metadata
        self.original_content_ref = original_content_ref
```

### 3. Ingestion Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Ingestion Orchestrator                    │
│  (knowledge_base/ingestion/orchestrator.py)                 │
└─────────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│   Source     │   │  Multimodal  │   │   Metadata   │
│  Extractors  │   │  Processors   │   │   Enricher   │
└──────────────┘   └──────────────┘   └──────────────┘
        │                   │                   │
        ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│              Unified Text Output + Metadata                   │
│              (compatible with existing RAPTOR)                │
└─────────────────────────────────────────────────────────────┘
```

## Implementation Plan

### Phase 1: Source Extractors (Weeks 1-2)

#### 1.1 Web Scraping
**Technology**: `playwright` or `beautifulsoup4` + `requests`
- **Pros**: Mature, handles JS-heavy sites
- **Cons**: Rate limiting, anti-bot measures
- **Cost**: Free (self-hosted) or $0.001-0.01/page (ScrapingBee/ScraperAPI)

**Implementation**:
```python
class WebExtractor:
    def extract(self, url: str) -> ExtractedContent:
        # Fetch page
        # Extract text, images, links
        # Return structured content + metadata
```

#### 1.2 File Extractors
**Technology**: 
- PDFs: `pypdf`, `pdfplumber`, or `unstructured.io` (paid, better quality)
- Images: Direct pass-through to multimodal processor
- Audio/Video: Pass-through to multimodal processor
- Office docs: `python-docx`, `openpyxl`, `unstructured.io`

**Cost**: Free (open source) or $0.01-0.05/doc (unstructured.io)

#### 1.3 API Extractors
**Technology**: Standard REST/GraphQL clients
- GitHub API
- Slack API
- Confluence API
- Custom REST endpoints

**Cost**: Usually free (API rate limits)

#### 1.4 Database Extractors
**Technology**: SQLAlchemy, pymongo
- PostgreSQL, MySQL, MongoDB
- Export queries as text documents

**Cost**: Free (self-hosted)

### Phase 2: Multimodal Processors (Weeks 3-4)

#### 2.1 Image Processing
**Options**:

**A. OpenAI GPT-4 Vision** (Recommended)
- **API**: `gpt-4-vision-preview` or `gpt-5.2`
- **Capability**: Describe images, extract text (OCR), summarize
- **Cost**: ~$0.01-0.03 per image
- **Quality**: Excellent, understands context
- **Code**:
```python
from openai import OpenAI
client = OpenAI()

def process_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        response = client.chat.completions.create(
            model="gpt-5.2",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract all text and describe key visual elements. Format as markdown."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"}}
                ]
            }],
            max_tokens=1000
        )
    return response.choices[0].message.content
```

**B. Google Gemini Vision**
- **Cost**: ~$0.002-0.01 per image
- **Quality**: Very good, cheaper alternative

**C. Anthropic Claude Vision**
- **Cost**: ~$0.008-0.015 per image
- **Quality**: Excellent, great for complex images

**D. Hybrid Approach** (Best for cost optimization)
- Simple OCR: `pytesseract` (free) for text-heavy images
- Complex images: GPT-4 Vision for description
- Fallback: Google Vision API for structured data extraction

#### 2.2 Audio Processing
**Options**:

**A. OpenAI Whisper API** (Recommended)
- **API**: `whisper-1` endpoint
- **Capability**: Speech-to-text, multilingual, speaker diarization
- **Cost**: $0.006 per minute
- **Quality**: State-of-the-art
- **Code**:
```python
def transcribe_audio(audio_path: str) -> dict:
    with open(audio_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",  # Includes timestamps, confidence
            language="en"  # Optional, auto-detect if omitted
        )
    return {
        "text": transcript.text,
        "segments": transcript.segments,  # Timestamped segments
        "language": transcript.language
    }
```

**B. AssemblyAI** (Alternative)
- **Cost**: $0.00025-0.00075 per second (~$0.015-0.045/min)
- **Features**: Speaker diarization, sentiment, entity extraction
- **Quality**: Excellent

**C. Deepgram** (Alternative)
- **Cost**: $0.0043 per minute
- **Features**: Real-time, low latency
- **Quality**: Very good

**D. Self-hosted Whisper** (Cost optimization)
- **Model**: `openai/whisper-large-v3`
- **Cost**: Compute only (GPU required)
- **Quality**: Same as API, but slower

#### 2.3 Video Processing
**Strategy**: Extract frames + audio, process separately

**Technology**:
- **Extraction**: `ffmpeg-python` or `moviepy`
- **Frame sampling**: Key frames + uniform sampling
- **Audio extraction**: Extract audio track → Whisper
- **Frame processing**: GPT-4 Vision for key frames

**Cost Estimate**:
- 10-minute video:
  - Audio (10 min): $0.06 (Whisper)
  - Key frames (10 frames): $0.10-0.30 (GPT-4 Vision)
  - **Total**: ~$0.16-0.36 per video

**Code**:
```python
import ffmpeg
from pathlib import Path

def process_video(video_path: str) -> dict:
    # Extract audio
    audio_path = extract_audio(video_path)
    transcript = transcribe_audio(audio_path)
    
    # Extract key frames
    frames = extract_key_frames(video_path, n_frames=10)
    frame_descriptions = [process_image(f) for f in frames]
    
    # Combine
    return {
        "transcript": transcript,
        "visual_summary": "\n".join(frame_descriptions),
        "metadata": {
            "duration": get_video_duration(video_path),
            "fps": get_fps(video_path),
            "resolution": get_resolution(video_path)
        }
    }
```

#### 2.4 PDF Processing (Enhanced)
**Current**: Text extraction only
**Enhanced**: Extract images from PDFs → process with vision models

**Technology**: `pdfplumber` + `pymupdf` for image extraction
**Cost**: Same as image processing for extracted images

### Phase 3: Metadata Enrichment (Week 5)

#### 3.1 Automatic Tagging
**Technology**: GPT-4 or Claude for content analysis
- Extract topics, entities, categories
- Cost: ~$0.001-0.005 per document

#### 3.2 Language Detection
**Technology**: `langdetect` (free) or API-based
- Cost: Free (open source)

#### 3.3 Content Quality Scoring
**Technology**: Custom heuristics + LLM evaluation
- Completeness, clarity, relevance scores

### Phase 4: Integration with RAPTOR (Week 6)

#### 4.1 Enhanced Corpus Format
```json
{
  "id": "sha1_hash",
  "rel_path": "path/to/content",
  "source_url": "https://...",
  "text": "extracted/transcribed text",
  "metadata": {
    "source_type": "video",
    "original_format": "mp4",
    "processing_steps": ["extract_audio", "transcribe", "extract_frames", "describe_frames"],
    "processing_model": "whisper-large-v3",
    "processing_cost_usd": 0.25,
    "confidence_score": 0.95,
    "language": "en",
    "tags": ["tutorial", "kubernetes", "deployment"],
    "ingested_at": "2024-01-15T10:30:00Z"
  }
}
```

#### 4.2 Node Metadata Preservation
- Store `SourceMetadata` in Node
- Preserve through tree building
- Enable filtering/querying by source type, tags, etc.

#### 4.3 Retrieval Enhancements
- Filter by source type: "Show me only video transcripts"
- Filter by tags: "Show me Kubernetes tutorials"
- Show provenance: "This came from video X at timestamp Y"

## Cost Estimates

### Per-Item Processing Costs

| Content Type | Processing | Cost (USD) | Notes |
|-------------|------------|------------|-------|
| Web page | Scrape + extract | $0.001-0.01 | Depends on complexity |
| PDF (text) | Extract text | $0.001-0.01 | Free with pypdf |
| PDF (with images) | Extract + OCR images | $0.01-0.05 | Depends on image count |
| Image | GPT-4 Vision | $0.01-0.03 | Per image |
| Audio (1 min) | Whisper API | $0.006 | Per minute |
| Video (10 min) | Audio + frames | $0.16-0.36 | 10 key frames |
| Video (1 hour) | Audio + frames | $0.96-2.16 | 60 key frames |

### Monthly Cost Scenarios

**Light usage** (100 pages, 50 images, 10 videos):
- Web: $1
- Images: $1.50
- Videos: $2-4
- **Total**: ~$5-7/month

**Medium usage** (1000 pages, 500 images, 100 videos):
- Web: $10
- Images: $15
- Videos: $20-40
- **Total**: ~$45-65/month

**Heavy usage** (10k pages, 5k images, 1000 videos):
- Web: $100
- Images: $150
- Videos: $200-400
- **Total**: ~$450-650/month

## Technical Stack Recommendations

### Core Libraries
```python
# Web scraping
playwright>=1.40.0  # Modern, handles JS
beautifulsoup4>=4.12.0  # Fallback for simple sites

# File processing
pypdf>=3.17.0  # PDF text
pdfplumber>=0.10.0  # PDF tables/images
python-docx>=1.1.0  # Word docs
openpyxl>=3.1.0  # Excel
pytesseract>=0.3.10  # OCR (free alternative)

# Media processing
ffmpeg-python>=0.2.0  # Video/audio extraction
moviepy>=1.0.3  # Video processing
Pillow>=10.0.0  # Image handling

# APIs
openai>=1.50.0  # GPT-4 Vision, Whisper
anthropic>=0.18.0  # Claude Vision (optional)
google-cloud-vision>=3.4.0  # Google Vision (optional)

# Utilities
langdetect>=1.0.9  # Language detection
tiktoken>=0.5.0  # Token counting (already used)
```

### Architecture Components

```
knowledge_base/
├── ingestion/
│   ├── __init__.py
│   ├── orchestrator.py          # Main ingestion coordinator
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── base.py               # Base extractor interface
│   │   ├── web.py                # Web scraping
│   │   ├── pdf.py                # PDF extraction
│   │   ├── api.py                # API extractors
│   │   ├── file.py               # Generic file handler
│   │   └── database.py           # Database extractors
│   ├── processors/
│   │   ├── __init__.py
│   │   ├── base.py               # Base processor interface
│   │   ├── image.py              # Image → text
│   │   ├── audio.py              # Audio → text
│   │   ├── video.py              # Video → text
│   │   └── pdf_enhanced.py       # PDF with image extraction
│   ├── metadata.py               # SourceMetadata dataclass
│   └── utils.py                  # Shared utilities
└── ...
```

## Implementation Priority

### MVP (Minimum Viable Product) - 2-3 weeks
1. ✅ Web scraping (playwright)
2. ✅ PDF text extraction (enhanced)
3. ✅ Image → text (GPT-4 Vision)
4. ✅ Audio → text (Whisper API)
5. ✅ Basic metadata preservation

### Phase 2 - 2 weeks
6. Video processing
7. Enhanced PDF (with images)
8. API extractors (GitHub, Slack)
9. Automatic tagging

### Phase 3 - 1-2 weeks
10. Database extractors
11. Advanced metadata enrichment
12. Cost tracking/optimization
13. Batch processing optimizations

## Risk Assessment

### Low Risk ✅
- Text extraction (mature tech)
- Audio transcription (Whisper is proven)
- Image description (GPT-4 Vision is excellent)

### Medium Risk ⚠️
- Video processing (cost can scale quickly)
- Web scraping (anti-bot measures, rate limits)
- Large file handling (memory/performance)

### Mitigation Strategies
1. **Cost controls**: Per-item cost limits, batch processing
2. **Rate limiting**: Respect API rate limits, queue system
3. **Caching**: Don't re-process same content
4. **Fallbacks**: Free alternatives (pytesseract, self-hosted Whisper)
5. **Monitoring**: Track costs, processing times, failures

## Success Metrics

1. **Coverage**: Support 10+ source types
2. **Quality**: >90% successful extraction rate
3. **Cost**: <$0.10 per average document
4. **Speed**: <30 seconds per document (excluding video)
5. **Metadata**: 100% metadata preservation

## Next Steps

1. **Prototype** (Week 1):
   - Implement web extractor
   - Implement image processor (GPT-4 Vision)
   - Test with 10-20 samples

2. **Validate** (Week 2):
   - Measure quality, cost, speed
   - Get user feedback
   - Refine approach

3. **Scale** (Weeks 3-6):
   - Add remaining extractors/processors
   - Integrate with RAPTOR
   - Production deployment

## Conclusion

A multimodal ingestion layer is **highly feasible** and would be a significant competitive advantage. The technology stack is mature, costs are reasonable, and integration with existing RAPTOR architecture is straightforward.

**Recommendation**: ✅ **Proceed with implementation**

Start with MVP (web + images + audio), validate, then expand to video and other sources.

