# Ultimate Enterprise RAG Architecture

## Vision

Build the **ultimate knowledge system** for enterprise AI agents - one that doesn't just store and retrieve information, but actively learns, maintains itself, and understands the full context of enterprise operations.

---

## Part 1: First Principles - What Knowledge Does an Enterprise Agent Need?

### Knowledge Taxonomy

An enterprise agent needs **8 distinct types of knowledge**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ENTERPRISE KNOWLEDGE TAXONOMY                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. PROCEDURAL        "How to do things"                                    │
│     ├── Runbooks (incident response steps)                                  │
│     ├── SOPs (standard operating procedures)                                │
│     ├── Playbooks (decision trees)                                          │
│     ├── Workflows (approval chains, deployment processes)                   │
│     └── Troubleshooting guides                                              │
│                                                                              │
│  2. FACTUAL           "What things are"                                     │
│     ├── Service documentation                                               │
│     ├── API specifications                                                  │
│     ├── Configuration schemas                                               │
│     ├── Architecture documentation                                          │
│     └── Technology stack details                                            │
│                                                                              │
│  3. RELATIONAL        "How things connect"                                  │
│     ├── Service dependencies                                                │
│     ├── Data flow paths                                                     │
│     ├── Team ownership                                                      │
│     ├── Integration points                                                  │
│     └── Technology relationships                                            │
│                                                                              │
│  4. TEMPORAL          "What happened and when"                              │
│     ├── Incident history                                                    │
│     ├── Change logs                                                         │
│     ├── Deployment history                                                  │
│     ├── Postmortems                                                         │
│     └── Decision records (ADRs)                                             │
│                                                                              │
│  5. SOCIAL            "Who knows what"                                      │
│     ├── Subject matter experts                                              │
│     ├── Team responsibilities                                               │
│     ├── Escalation paths                                                    │
│     ├── On-call rotations                                                   │
│     └── Contact information                                                 │
│                                                                              │
│  6. CONTEXTUAL        "Current state"                                       │
│     ├── Active incidents                                                    │
│     ├── Maintenance windows                                                 │
│     ├── Feature flags                                                       │
│     ├── Health status                                                       │
│     └── Recent alerts                                                       │
│                                                                              │
│  7. POLICY            "Rules and constraints"                               │
│     ├── Compliance requirements                                             │
│     ├── Security policies                                                   │
│     ├── SLAs/SLOs                                                           │
│     ├── Change management rules                                             │
│     └── Access control policies                                             │
│                                                                              │
│  8. META-KNOWLEDGE    "Knowledge about knowledge"                           │
│     ├── What's stale/outdated                                               │
│     ├── What's authoritative                                                │
│     ├── Confidence levels                                                   │
│     ├── Knowledge gaps                                                      │
│     └── Contradictions                                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Storage Requirements by Type

| Type | Volatility | Query Pattern | Best Storage |
|------|------------|---------------|--------------|
| Procedural | Low | Sequential traversal | RAPTOR tree + Graph |
| Factual | Medium | Semantic search | RAPTOR tree |
| Relational | Medium | Graph traversal | Knowledge Graph |
| Temporal | High | Time-range + semantic | Time-indexed + RAPTOR |
| Social | Medium | Lookup + graph | Structured DB + Graph |
| Contextual | Very High | Real-time lookup | Cache + Live APIs |
| Policy | Low | Rule matching | Structured + RAPTOR |
| Meta | Continuous | Internal system | Metadata layer |

---

## Part 2: Core Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         ULTIMATE RAG SYSTEM                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     INGESTION LAYER                                  │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │    │
│  │  │Confluence│ │  GitHub  │ │  Slack   │ │  Notion  │ │ Custom   │  │    │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘  │    │
│  │       └────────────┴────────────┴────────────┴────────────┘        │    │
│  │                              ↓                                      │    │
│  │  ┌──────────────────────────────────────────────────────────────┐  │    │
│  │  │  Document Processor                                           │  │    │
│  │  │  ├── Change Detection (hash-based)                           │  │    │
│  │  │  ├── Entity Extraction (NER + LLM)                           │  │    │
│  │  │  ├── Relationship Extraction                                  │  │    │
│  │  │  ├── Knowledge Type Classification                           │  │    │
│  │  │  └── Importance Signal Extraction                            │  │    │
│  │  └──────────────────────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    ↓                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                      STORAGE LAYER                                   │    │
│  │                                                                      │    │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐     │    │
│  │  │  RAPTOR FOREST  │  │ KNOWLEDGE GRAPH │  │  META STORE     │     │    │
│  │  │  ┌───────────┐  │  │                 │  │                 │     │    │
│  │  │  │ Procedural│  │  │   Entities:     │  │ - Importance    │     │    │
│  │  │  │   Tree    │  │  │   - Services    │  │ - Freshness     │     │    │
│  │  │  └───────────┘  │  │   - Teams       │  │ - Confidence    │     │    │
│  │  │  ┌───────────┐  │  │   - People      │  │ - Access stats  │     │    │
│  │  │  │  Factual  │  │  │   - Runbooks    │  │ - Feedback      │     │    │
│  │  │  │   Tree    │  │  │   - Incidents   │  │ - Gaps          │     │    │
│  │  │  └───────────┘  │  │                 │  │ - Contradictions│     │    │
│  │  │  ┌───────────┐  │  │   Relations:    │  │                 │     │    │
│  │  │  │ Temporal  │  │  │   - DEPENDS_ON  │  └─────────────────┘     │    │
│  │  │  │   Tree    │  │  │   - OWNS        │                          │    │
│  │  │  └───────────┘  │  │   - DOCUMENTED  │  ┌─────────────────┐     │    │
│  │  │  ┌───────────┐  │  │   - RESOLVES    │  │  LIVE CONTEXT   │     │    │
│  │  │  │  Policy   │  │  │   - EXPERT_IN   │  │  - Active incidents│  │    │
│  │  │  │   Tree    │  │  │   - ESCALATES   │  │  - Health status │   │    │
│  │  │  └───────────┘  │  │                 │  │  - On-call now   │   │    │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────┘     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    ↓                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     RETRIEVAL LAYER                                  │    │
│  │                                                                      │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │    │
│  │  │Query Analyzer│→ │   Router     │→ │  Retriever   │               │    │
│  │  │- Intent      │  │- Tree select │  │- RAPTOR      │               │    │
│  │  │- Entities    │  │- Strategy    │  │- Graph walk  │               │    │
│  │  │- Complexity  │  │- Depth       │  │- Hybrid      │               │    │
│  │  └──────────────┘  └──────────────┘  └──────────────┘               │    │
│  │                                              ↓                       │    │
│  │  ┌──────────────────────────────────────────────────────────────┐  │    │
│  │  │  Result Processor                                             │  │    │
│  │  │  ├── Reranking (cross-encoder)                               │  │    │
│  │  │  ├── Importance weighting                                     │  │    │
│  │  │  ├── Freshness filtering                                      │  │    │
│  │  │  ├── Deduplication                                            │  │    │
│  │  │  └── Context assembly                                         │  │    │
│  │  └──────────────────────────────────────────────────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    ↓                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                     AGENTIC LAYER                                    │    │
│  │                                                                      │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │    │
│  │  │ Observation  │  │  Learning    │  │ Maintenance  │               │    │
│  │  │ Collector    │  │  Engine      │  │ Agent        │               │    │
│  │  │              │  │              │  │              │               │    │
│  │  │- Query logs  │  │- Corrections │  │- Stale detect│               │    │
│  │  │- Feedback    │  │- Patterns    │  │- Gap detect  │               │    │
│  │  │- Outcomes    │  │- Confidence  │  │- Conflict    │               │    │
│  │  │- Gaps        │  │  updates     │  │  resolution  │               │    │
│  │  └──────────────┘  └──────────────┘  └──────────────┘               │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Part 3: Importance Scoring System

### Multi-Signal Importance Model

```python
@dataclass
class ImportanceScore:
    """
    Composite importance score from multiple signals.
    Final score is weighted combination, normalized to [0, 1].
    """

    # Explicit signals (human-provided)
    explicit_priority: float      # 0-1, admin/author marked importance

    # Usage signals (observed behavior)
    access_frequency: float       # normalized query/citation count
    recency_of_access: float      # how recently accessed

    # Content signals (derived from content)
    authority_score: float        # author expertise, review status
    criticality_score: float      # related to critical services/P1 incidents
    uniqueness_score: float       # how unique is this information

    # Quality signals (feedback-based)
    user_rating: float            # explicit feedback
    outcome_success: float        # did using this lead to good outcomes

    # Freshness signals
    content_freshness: float      # how recently updated
    source_freshness: float       # is the source still valid

    def compute_final(self, weights: Dict[str, float]) -> float:
        """Weighted combination of all signals."""
        signals = {
            'explicit': self.explicit_priority,
            'frequency': self.access_frequency,
            'recency': self.recency_of_access,
            'authority': self.authority_score,
            'criticality': self.criticality_score,
            'uniqueness': self.uniqueness_score,
            'rating': self.user_rating,
            'outcome': self.outcome_success,
            'freshness': (self.content_freshness + self.source_freshness) / 2,
        }

        total_weight = sum(weights.values())
        score = sum(signals[k] * weights.get(k, 0) for k in signals)
        return score / total_weight if total_weight > 0 else 0.5
```

### Importance Decay Model

```
importance(t) = base_importance * decay_factor(t) * boost_factor(context)

where:
  decay_factor(t) = exp(-λ * (now - last_validated))
  boost_factor = 1.0 + Σ(contextual_boosts)

contextual_boosts:
  - Related to active incident: +0.3
  - Recently updated: +0.2
  - Frequently cited: +0.15
  - Author is SME: +0.1
```

---

## Part 4: Knowledge Graph Schema

### Entity Types

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        KNOWLEDGE GRAPH ENTITIES                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  SERVICE                          PERSON                                    │
│  ├── name: str                    ├── name: str                             │
│  ├── tier: P1|P2|P3               ├── email: str                            │
│  ├── team_id: str                 ├── team_id: str                          │
│  ├── repo_url: str                ├── expertise: List[str]                  │
│  ├── docs_tree_id: str            └── slack_handle: str                     │
│  └── health_endpoint: str                                                    │
│                                                                              │
│  TEAM                             RUNBOOK                                   │
│  ├── name: str                    ├── title: str                            │
│  ├── slack_channel: str           ├── node_id: int (RAPTOR ref)             │
│  ├── oncall_schedule_id: str      ├── applies_to: List[ServiceID]           │
│  └── escalation_policy: str       ├── symptoms: List[str]                   │
│                                   └── last_used: datetime                    │
│                                                                              │
│  INCIDENT                         DOCUMENT                                  │
│  ├── id: str                      ├── id: str                               │
│  ├── severity: P1-P5              ├── title: str                            │
│  ├── services_affected: List      ├── node_ids: List[int] (RAPTOR refs)     │
│  ├── root_cause: str              ├── knowledge_type: KnowledgeType         │
│  ├── resolution: str              ├── source_url: str                       │
│  └── postmortem_node_id: int      └── importance: ImportanceScore           │
│                                                                              │
│  TECHNOLOGY                       ALERT_RULE                                │
│  ├── name: str                    ├── name: str                             │
│  ├── category: str                ├── query: str                            │
│  ├── docs_node_ids: List[int]     ├── services: List[ServiceID]             │
│  └── experts: List[PersonID]      └── runbook_id: str                       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Relationship Types

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       KNOWLEDGE GRAPH RELATIONSHIPS                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Service → Service                                                          │
│  ├── DEPENDS_ON (criticality: float)                                        │
│  ├── CALLS (protocol: str, endpoint: str)                                   │
│  └── SHARES_DATA_WITH (data_type: str)                                      │
│                                                                              │
│  Team → Service                                                             │
│  └── OWNS (since: date)                                                     │
│                                                                              │
│  Person → Service                                                           │
│  ├── EXPERT_IN (level: junior|senior|principal)                             │
│  └── ON_CALL_FOR (schedule: str)                                            │
│                                                                              │
│  Person → Team                                                              │
│  └── MEMBER_OF (role: str)                                                  │
│                                                                              │
│  Runbook → Service                                                          │
│  └── RESOLVES_ISSUES_FOR (symptom_match: float)                             │
│                                                                              │
│  Runbook → Incident                                                         │
│  └── USED_IN (success: bool, duration: int)                                 │
│                                                                              │
│  Document → Service                                                         │
│  └── DOCUMENTS (coverage: float)                                            │
│                                                                              │
│  Document → Document                                                        │
│  ├── REFERENCES                                                             │
│  ├── SUPERSEDES                                                             │
│  └── CONTRADICTS (field: str, resolution: str)                              │
│                                                                              │
│  Incident → Service                                                         │
│  └── AFFECTED (impact_level: float)                                         │
│                                                                              │
│  AlertRule → Runbook                                                        │
│  └── TRIGGERS (auto_link: bool)                                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Graph + RAPTOR Integration

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    HYBRID GRAPH-TREE ARCHITECTURE                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Knowledge Graph (NetworkX/Neo4j)          RAPTOR Forest                    │
│  ┌─────────────────────────────┐          ┌─────────────────────────────┐  │
│  │                             │          │                             │  │
│  │  [Service: payment-api]─────┼──────────┼─→ Tree: service_docs        │  │
│  │       │                     │          │      Node #1234 (leaf)      │  │
│  │       │ DEPENDS_ON          │          │      Node #1235 (leaf)      │  │
│  │       ↓                     │          │                             │  │
│  │  [Service: postgres-db]─────┼──────────┼─→ Tree: infra_docs          │  │
│  │       │                     │          │      Node #5678 (leaf)      │  │
│  │       │ RESOLVES_ISSUES_FOR │          │                             │  │
│  │       ↓                     │          │                             │  │
│  │  [Runbook: db-failover]─────┼──────────┼─→ Tree: runbooks            │  │
│  │       │                     │          │      Node #9012 (leaf)      │  │
│  │       │ USED_IN             │          │                             │  │
│  │       ↓                     │          │                             │  │
│  │  [Incident: INC-2024-001]───┼──────────┼─→ Tree: postmortems         │  │
│  │                             │          │      Node #3456 (leaf)      │  │
│  │                             │          │                             │  │
│  └─────────────────────────────┘          └─────────────────────────────┘  │
│                                                                              │
│  Query: "How do I fix database connection issues for payment-api?"          │
│                                                                              │
│  1. Extract entities: [payment-api, database, connection]                   │
│  2. Graph traversal: payment-api → DEPENDS_ON → postgres-db                │
│  3. Find related: postgres-db → RESOLVES_ISSUES_FOR → [runbooks]           │
│  4. Get RAPTOR nodes: runbook.node_ids → [#9012, #9013, ...]              │
│  5. RAPTOR retrieve: hierarchical search in runbooks tree                  │
│  6. Merge & rank: combine graph context + RAPTOR results                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Part 5: Agentic Integration

### The Learning Loop

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AGENTIC LEARNING LOOP                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│                        ┌──────────────────┐                                 │
│                        │   Agent Works    │                                 │
│                        │  (uses knowledge)│                                 │
│                        └────────┬─────────┘                                 │
│                                 │                                            │
│        ┌────────────────────────┼────────────────────────┐                  │
│        ↓                        ↓                        ↓                  │
│  ┌───────────┐          ┌───────────────┐        ┌────────────┐            │
│  │  Success  │          │  Correction   │        │   Failure  │            │
│  │  Outcome  │          │   Received    │        │  (no info) │            │
│  └─────┬─────┘          └───────┬───────┘        └──────┬─────┘            │
│        │                        │                       │                   │
│        ↓                        ↓                       ↓                   │
│  ┌───────────┐          ┌───────────────┐        ┌────────────┐            │
│  │  Boost    │          │   Update      │        │  Log Gap   │            │
│  │ importance│          │   knowledge   │        │  Request   │            │
│  │  + signal │          │   + retrain   │        │  human fill│            │
│  └───────────┘          └───────────────┘        └────────────┘            │
│        │                        │                       │                   │
│        └────────────────────────┴───────────────────────┘                   │
│                                 │                                            │
│                                 ↓                                            │
│                   ┌─────────────────────────┐                               │
│                   │   Knowledge Base        │                               │
│                   │   (continuously learns) │                               │
│                   └─────────────────────────┘                               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Observation Events

```python
@dataclass
class AgentObservation:
    """Events the agent reports back to the KB."""

    observation_type: Literal[
        'query_success',      # Found relevant info, task succeeded
        'query_partial',      # Found some info, needed more
        'query_failure',      # Couldn't find needed info
        'correction',         # User corrected agent's answer
        'contradiction',      # Found conflicting information
        'outdated',           # Information was stale/wrong
        'new_knowledge',      # Learned something new during task
        'runbook_success',    # Runbook worked for incident
        'runbook_failure',    # Runbook didn't work
    ]

    # Context
    query: str
    retrieved_nodes: List[int]
    task_id: str
    timestamp: datetime

    # Outcome details
    success_score: float          # 0-1, how successful was the retrieval
    user_feedback: Optional[str]  # explicit feedback if any
    correction_text: Optional[str]  # what the correct info should be
    gap_description: Optional[str]  # what info was missing

    # For learning
    should_create_node: bool      # should we add new knowledge
    should_invalidate: List[int]  # nodes to mark as stale
    should_boost: List[int]       # nodes to boost importance
    should_demote: List[int]      # nodes to demote
```

### Proactive Maintenance Agent

```python
class MaintenanceAgent:
    """
    Background agent that keeps the knowledge base healthy.
    """

    async def run_maintenance_cycle(self):
        """Periodic maintenance tasks."""

        # 1. Detect stale content
        stale_nodes = await self.detect_stale_content()
        for node in stale_nodes:
            await self.request_refresh(node)

        # 2. Detect knowledge gaps
        gaps = await self.analyze_query_logs_for_gaps()
        for gap in gaps:
            await self.create_gap_ticket(gap)

        # 3. Detect contradictions
        contradictions = await self.find_contradictions()
        for c in contradictions:
            await self.flag_for_resolution(c)

        # 4. Suggest consolidation
        duplicates = await self.find_near_duplicates()
        for dup_set in duplicates:
            await self.suggest_merge(dup_set)

        # 5. Update importance scores
        await self.recalculate_importance_scores()

        # 6. Prune low-value content
        await self.archive_low_value_nodes()

    async def detect_stale_content(self) -> List[Node]:
        """Find nodes that haven't been validated recently."""
        cutoff = datetime.now() - timedelta(days=90)
        return [
            node for node in self.kb.all_nodes()
            if node.metadata.get('last_validated', datetime.min) < cutoff
            and node.importance.content_freshness < 0.3
        ]

    async def analyze_query_logs_for_gaps(self) -> List[KnowledgeGap]:
        """Find patterns in failed/partial queries."""
        failed_queries = await self.get_recent_failed_queries(days=7)

        # Cluster similar failed queries
        clusters = self.cluster_queries(failed_queries)

        gaps = []
        for cluster in clusters:
            if len(cluster) >= 3:  # Multiple users hit same gap
                gaps.append(KnowledgeGap(
                    description=self.summarize_cluster(cluster),
                    frequency=len(cluster),
                    example_queries=cluster[:5],
                    suggested_sources=self.suggest_sources(cluster),
                ))

        return gaps
```

### Teaching Interface

```python
class TeachingInterface:
    """
    Interface for agents to teach the KB new knowledge.
    """

    async def teach(
        self,
        content: str,
        knowledge_type: KnowledgeType,
        source: str,
        confidence: float,
        related_entities: List[str],
        learned_from: str,  # 'incident_resolution', 'user_correction', etc.
    ) -> TeachResult:
        """
        Agent teaches KB something new.

        Flow:
        1. Check for duplicates/contradictions
        2. Extract entities and relationships
        3. Create provisional node (low confidence)
        4. Queue for human review if confidence < threshold
        5. Link to knowledge graph
        """

        # Check for existing similar knowledge
        similar = await self.find_similar(content, threshold=0.85)
        if similar:
            if self.is_contradiction(content, similar):
                return TeachResult(
                    status='contradiction',
                    existing_nodes=similar,
                    action='queued_for_review'
                )
            else:
                # Potential duplicate - merge or skip
                return TeachResult(
                    status='duplicate',
                    existing_nodes=similar,
                    action='merged' if self.should_merge(content, similar) else 'skipped'
                )

        # Create new node
        node = await self.create_provisional_node(
            content=content,
            knowledge_type=knowledge_type,
            source=source,
            confidence=confidence,
            metadata={
                'learned_from': learned_from,
                'requires_review': confidence < 0.8,
                'created_by': 'agent',
            }
        )

        # Extract and link entities
        entities = await self.extract_entities(content)
        for entity in entities:
            await self.link_to_graph(node, entity, related_entities)

        return TeachResult(
            status='created',
            node_id=node.index,
            action='active' if confidence >= 0.8 else 'pending_review'
        )
```

---

## Part 6: Advanced Retrieval Strategies

### Multi-Strategy Retriever

```python
class UltimateRetriever:
    """
    Combines multiple retrieval strategies based on query analysis.
    """

    async def retrieve(
        self,
        query: str,
        context: Optional[Dict] = None,
    ) -> RetrievalResult:

        # 1. Analyze query
        analysis = await self.analyze_query(query)

        # 2. Select strategies based on analysis
        strategies = self.select_strategies(analysis)

        # 3. Execute strategies (possibly in parallel)
        all_results = []
        for strategy in strategies:
            results = await strategy.execute(query, analysis, context)
            all_results.extend(results)

        # 4. Merge and rerank
        merged = self.merge_results(all_results, analysis)
        reranked = await self.rerank(merged, query)

        # 5. Apply importance weighting
        weighted = self.apply_importance_weights(reranked)

        # 6. Assemble context
        return self.assemble_context(weighted, analysis)

    def select_strategies(self, analysis: QueryAnalysis) -> List[Strategy]:
        strategies = []

        # Always include semantic search on relevant trees
        strategies.append(RAPTORStrategy(
            trees=analysis.relevant_trees,
            depth='adaptive' if analysis.complexity > 0.5 else 'shallow'
        ))

        # Add graph traversal for relational queries
        if analysis.has_entity_relationships:
            strategies.append(GraphTraversalStrategy(
                start_entities=analysis.entities,
                max_hops=2
            ))

        # Add HyDE for complex/abstract queries
        if analysis.complexity > 0.7:
            strategies.append(HyDEStrategy())

        # Add multi-query expansion for ambiguous queries
        if analysis.ambiguity > 0.5:
            strategies.append(MultiQueryStrategy(variations=3))

        # Add temporal filtering for time-sensitive queries
        if analysis.temporal_context:
            strategies.append(TemporalFilterStrategy(
                time_range=analysis.temporal_context
            ))

        return strategies
```

### Retrieval Strategies

```python
class RAPTORStrategy:
    """Standard RAPTOR hierarchical retrieval."""

    async def execute(self, query, analysis, context):
        results = []
        for tree_name in self.trees:
            tree = self.get_tree(tree_name)

            if self.depth == 'adaptive':
                # Start high, go deeper if results are poor
                for start_layer in range(tree.num_layers, -1, -1):
                    layer_results = tree.retrieve(
                        query,
                        start_layer=start_layer,
                        num_layers=min(3, start_layer + 1)
                    )
                    if self.results_sufficient(layer_results):
                        results.extend(layer_results)
                        break
            else:
                # Shallow retrieval from top layers only
                results.extend(tree.retrieve(
                    query,
                    start_layer=tree.num_layers,
                    num_layers=2
                ))

        return results


class GraphTraversalStrategy:
    """Graph-based entity expansion."""

    async def execute(self, query, analysis, context):
        results = []

        for entity in self.start_entities:
            # Find entity in graph
            graph_node = self.graph.find_entity(entity)
            if not graph_node:
                continue

            # Traverse relationships
            related = self.graph.traverse(
                graph_node,
                max_hops=self.max_hops,
                relationship_types=['DEPENDS_ON', 'DOCUMENTED_BY', 'RESOLVES']
            )

            # Get RAPTOR nodes for related entities
            for rel_entity in related:
                if rel_entity.raptor_node_ids:
                    for node_id in rel_entity.raptor_node_ids:
                        node = self.get_raptor_node(node_id)
                        results.append(RetrievalResult(
                            node=node,
                            score=1.0 / (1 + rel_entity.distance),
                            source='graph',
                            path=rel_entity.path
                        ))

        return results


class HyDEStrategy:
    """Hypothetical Document Embedding."""

    async def execute(self, query, analysis, context):
        # Generate hypothetical answer
        hypothetical = await self.llm.generate(
            f"Write a detailed answer to this question as if you were "
            f"an expert. Question: {query}"
        )

        # Embed the hypothetical answer
        hyde_embedding = self.embed(hypothetical)

        # Search with hypothetical embedding
        results = []
        for tree in self.all_trees:
            similar = tree.retrieve_by_embedding(
                hyde_embedding,
                top_k=10
            )
            results.extend(similar)

        return results


class MultiQueryStrategy:
    """Generate query variations for better recall."""

    async def execute(self, query, analysis, context):
        # Generate variations
        variations = await self.llm.generate(
            f"Generate {self.variations} different ways to ask this question, "
            f"focusing on different aspects or phrasings: {query}"
        )

        all_results = []
        for variation in [query] + variations:
            for tree in self.relevant_trees:
                results = tree.retrieve(variation, top_k=5)
                all_results.extend(results)

        # Dedupe by node ID, keeping highest score
        return self.dedupe_by_score(all_results)
```

---

## Part 7: API Design

### Core Endpoints

```yaml
# Knowledge Retrieval
POST /api/v1/retrieve
  - query: str
  - context: Optional[Dict]  # active incident, user role, etc.
  - strategies: Optional[List[str]]  # force specific strategies
  - filters: Optional[Dict]  # knowledge_type, freshness, etc.

POST /api/v1/answer
  - question: str
  - context: Optional[Dict]
  - include_sources: bool
  - include_confidence: bool

# Knowledge Teaching
POST /api/v1/teach
  - content: str
  - knowledge_type: str
  - source: str
  - confidence: float
  - related_entities: List[str]

# Agent Feedback
POST /api/v1/feedback
  - observation: AgentObservation

# Graph Queries
POST /api/v1/graph/traverse
  - start_entity: str
  - relationship_types: List[str]
  - max_hops: int

GET /api/v1/graph/entity/{entity_id}
  - include_relationships: bool
  - include_raptor_context: bool

# Maintenance
GET /api/v1/health/knowledge
  - Returns: stale count, gap count, contradiction count

POST /api/v1/maintenance/refresh
  - node_ids: List[int]
  - force: bool

GET /api/v1/gaps
  - Returns: current knowledge gaps with suggestions
```

---

## Part 8: Implementation Phases

### Phase 1: Foundation (Week 1-2)
- [ ] Core data structures (Node, Tree, Entity, Relationship)
- [ ] Port RAPTOR tree building and retrieval
- [ ] Basic importance scoring
- [ ] Simple knowledge graph (NetworkX)

### Phase 2: Integration (Week 3-4)
- [ ] Graph-RAPTOR hybrid retrieval
- [ ] Query analyzer
- [ ] Multi-strategy retriever
- [ ] API server

### Phase 3: Agentic Features (Week 5-6)
- [ ] Observation collector
- [ ] Teaching interface
- [ ] Maintenance agent
- [ ] Feedback loop

### Phase 4: Advanced (Week 7-8)
- [ ] HyDE and multi-query strategies
- [ ] Real-time ingestion pipeline
- [ ] Quality monitoring dashboard
- [ ] Production hardening

---

## Appendix: Example Queries

```
Query: "How do I fix OOMKilled pods for payment-service?"

Analysis:
  - Intent: troubleshooting
  - Entities: [OOMKilled, pods, payment-service]
  - Knowledge types needed: [procedural, factual, temporal]
  - Complexity: 0.6

Retrieval Path:
  1. Graph: payment-service → DEPENDS_ON → [postgres, redis, auth-service]
  2. Graph: OOMKilled → RESOLVES → [runbook-memory-issues]
  3. RAPTOR: Search runbooks tree for "OOM memory kubernetes"
  4. RAPTOR: Search service-docs tree for "payment-service memory"
  5. Temporal: Recent incidents involving payment-service + OOM

Result Assembly:
  - Primary: Runbook "Handling OOMKilled Pods" (importance: 0.95)
  - Supporting: Payment-service memory configuration docs
  - Context: Recent incident INC-2024-042 had similar symptoms
  - Related: postgres-db memory tuning guide
  - Expert: @jane-doe is SME for payment-service memory issues
```
