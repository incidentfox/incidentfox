"""
Prompt templates for LLM-powered content analysis.

These prompts are designed to work with structured output parsing
(e.g., OpenAI's response_format=json_schema or function calling).
"""

# =============================================================================
# Knowledge Type Classification Prompt
# =============================================================================

KNOWLEDGE_TYPE_CLASSIFICATION_PROMPT = """You are an expert at classifying technical documentation and knowledge for incident response systems.

Analyze the following content and classify it into exactly ONE primary knowledge type.

## Knowledge Types

1. **PROCEDURAL**: How-to guides, runbooks, troubleshooting steps, remediation instructions, operational procedures.
   - Examples: "To restart the service, run kubectl rollout restart...", step-by-step debugging guides

2. **FACTUAL**: Facts, configurations, API specifications, architecture documentation, technical specifications.
   - Examples: Service configurations, API endpoints, system requirements, version compatibility

3. **RELATIONAL**: Service dependencies, system topology, ownership information, integration mappings.
   - Examples: "payment-service depends on redis-cluster", "Team Alpha owns user-service"

4. **TEMPORAL**: Time-bound information like incidents, deployments, changes, outages with timestamps.
   - Examples: Incident reports, deployment logs, change records, maintenance windows

5. **SOCIAL**: Contact information, team structures, escalation paths, communication channels.
   - Examples: On-call schedules, team rosters, Slack channels for incidents

6. **CONTEXTUAL**: Environment-specific information (prod vs staging vs dev), region-specific configs.
   - Examples: "In production, set replica count to 5", "EU region uses different endpoints"

7. **POLICY**: Rules, compliance requirements, SLAs, security policies, operational constraints.
   - Examples: "PII data must not be logged", "P1 incidents require VP notification within 15 min"

8. **META**: Information about the knowledge base itself, documentation standards, tagging conventions.
   - Examples: How to contribute to docs, naming conventions, template guidelines

## Content to Classify

{content}

## Instructions

1. Read the content carefully
2. Identify the PRIMARY purpose of this content
3. If content spans multiple types, choose the DOMINANT type
4. Provide a secondary type only if the content truly serves dual purposes
5. Assign a confidence score (0.0-1.0) based on how clearly the content fits the type
6. Explain your reasoning briefly

Return your analysis as structured JSON matching the KnowledgeTypeResult schema."""


# =============================================================================
# Entity Extraction Prompt
# =============================================================================

ENTITY_EXTRACTION_PROMPT = """You are an expert at extracting technical entities from infrastructure and incident response documentation.

Extract all relevant entities from the following content.

## Entity Types

1. **SERVICE**: Microservices, APIs, workers, databases, queues, caches, infrastructure components
   - Look for: service names, API endpoints, database names, Redis/Kafka topics

2. **TEAM**: Engineering teams, squads, departments
   - Look for: team names, squad names, department references

3. **PERSON**: Individual engineers, managers, on-call contacts
   - Look for: names, usernames, email handles (extract name, not full email)

4. **TECHNOLOGY**: Tools, frameworks, programming languages, cloud services, infrastructure
   - Look for: AWS/GCP/Azure services, Kubernetes, Docker, specific frameworks

5. **METRIC**: Monitoring metrics, SLIs, SLOs, performance indicators
   - Look for: metric names, latency thresholds, error rate targets

6. **RUNBOOK**: Documentation references, wiki pages, confluence links
   - Look for: document titles, wiki references, links to procedures

7. **ENVIRONMENT**: Deployment environments like production, staging, development
   - Look for: env names, region references, cluster names

8. **ALERT**: Alert rules, monitoring conditions, PagerDuty services
   - Look for: alert names, threshold conditions, notification rules

9. **INCIDENT**: References to past incidents, outages, issues
   - Look for: incident IDs, outage references, postmortem mentions

10. **NAMESPACE**: Kubernetes namespaces, cloud projects, organizational units
    - Look for: namespace names, project IDs, account references

## Content to Analyze

{content}

## Instructions

1. Extract ALL entities you can identify in the content
2. For each entity:
   - Provide the exact name as it appears in the text
   - Create a canonical_name (lowercase, hyphens instead of spaces, no special chars)
   - Classify the entity type
   - Rate your confidence (0.0-1.0)
   - Note the context in which it appears (1 sentence max)
3. Don't extract generic terms - only specific, named entities
4. If an entity could be multiple types, choose the most specific applicable type

Return your analysis as structured JSON matching the EntityExtractionResult schema."""


# =============================================================================
# Relationship Extraction Prompt
# =============================================================================

RELATIONSHIP_EXTRACTION_PROMPT = """You are an expert at identifying relationships between technical entities in infrastructure documentation.

Given the content and a list of previously extracted entities, identify relationships between them.

## Relationship Types

1. **DEPENDS_ON**: Technical dependency where one service requires another to function
   - Example: "payment-service DEPENDS_ON postgres-db"

2. **CALLS**: Active invocation - one service calls/invokes another
   - Example: "api-gateway CALLS user-service"

3. **OWNS**: Team/person ownership of a service or component
   - Example: "platform-team OWNS kubernetes-cluster"

4. **MEMBER_OF**: Person belonging to a team
   - Example: "john-smith MEMBER_OF infrastructure-team"

5. **MONITORS**: Observability relationship - something watches/monitors another
   - Example: "datadog MONITORS payment-service"

6. **DOCUMENTS**: Documentation covers/describes something
   - Example: "api-runbook DOCUMENTS api-gateway"

7. **TRIGGERS**: Causal relationship - one thing causes/triggers another
   - Example: "high-latency-alert TRIGGERS incident-response"

8. **SUPERSEDES**: Replacement relationship - newer replaces older
   - Example: "v2-api SUPERSEDES v1-api"

9. **RELATED_TO**: General association when more specific type doesn't apply
   - Example: "redis-cluster RELATED_TO session-management"

10. **DEPLOYED_TO**: Where something runs/is deployed
    - Example: "user-service DEPLOYED_TO production-cluster"

11. **USES**: Technology/tool usage
    - Example: "payment-service USES stripe-sdk"

## Content

{content}

## Previously Extracted Entities

{entities}

## Instructions

1. Review the content and the list of entities
2. Identify relationships between ANY pairs of entities mentioned
3. For each relationship:
   - Specify source entity (must be from the entity list or clearly mentioned)
   - Specify relationship type
   - Specify target entity
   - Rate confidence (0.0-1.0)
   - Quote the specific text that supports this relationship
4. Only extract relationships explicitly stated or strongly implied
5. Don't infer relationships that aren't supported by the text

Return your analysis as structured JSON matching the RelationshipExtractionResult schema."""


# =============================================================================
# Importance Assessment Prompt
# =============================================================================

IMPORTANCE_ASSESSMENT_PROMPT = """You are an expert at assessing the importance of technical documentation for incident response.

Evaluate the following content and assess its importance across multiple dimensions.

## Assessment Dimensions

### 1. Authority Score (0.0-1.0)
How authoritative is this content?
- 1.0: Official documentation, verified by subject matter experts, company policy
- 0.7-0.9: Well-maintained internal docs, experienced engineer's notes
- 0.4-0.6: Team wiki pages, informal documentation
- 0.1-0.3: Outdated docs, unverified information, personal notes

### 2. Criticality Score (0.0-1.0)
How critical is this for incident response?
- 1.0: Directly prevents/resolves P1 incidents, safety-critical systems
- 0.7-0.9: Important for quick resolution, affects production
- 0.4-0.6: Useful context, affects staging/dev environments
- 0.1-0.3: Nice to know, rarely needed during incidents

### 3. Uniqueness Score (0.0-1.0)
How unique is this information?
- 1.0: Only place this info exists, tribal knowledge documented
- 0.7-0.9: Hard to find elsewhere, specific to this org
- 0.4-0.6: Supplements common knowledge, org-specific context
- 0.1-0.3: Easily found in public docs, generic information

### 4. Actionability Score (0.0-1.0)
How actionable is the content?
- 1.0: Clear step-by-step instructions, immediately applicable
- 0.7-0.9: Good guidance with some interpretation needed
- 0.4-0.6: Provides context but not direct actions
- 0.1-0.3: Theoretical, requires significant translation to action

### 5. Freshness Score (0.0-1.0)
How current is the content?
- 1.0: Recently updated, actively maintained
- 0.7-0.9: Relatively current, minor updates needed
- 0.4-0.6: Somewhat dated, core info still valid
- 0.1-0.3: Significantly outdated, may be misleading

## Content to Assess

{content}

## Additional Context

Source: {source}
Last Modified: {last_modified}

## Instructions

1. Carefully evaluate each dimension
2. Provide a score for each with brief justification
3. Calculate overall_importance as a weighted combination:
   - Criticality: 30%
   - Actionability: 25%
   - Authority: 20%
   - Uniqueness: 15%
   - Freshness: 10%
4. Explain your overall assessment reasoning

Return your analysis as structured JSON matching the ImportanceAssessment schema."""


# =============================================================================
# Content Analysis Combined Prompt
# =============================================================================

CONTENT_ANALYSIS_PROMPT = """You are an expert at analyzing technical documentation for an incident response knowledge base.

Perform a comprehensive analysis of the following content chunk.

## Content Information

Chunk ID: {chunk_id}
Source URL: {source_url}
Content:

{content}

## Analysis Tasks

You must perform ALL of the following analyses:

### 1. Knowledge Type Classification
Classify this content into one of these types:
- PROCEDURAL: How-to guides, runbooks, troubleshooting steps
- FACTUAL: Facts, configurations, API specs, architecture
- RELATIONAL: Service dependencies, ownership, topology
- TEMPORAL: Incidents, deployments, changes with timestamps
- SOCIAL: Contact info, team structure, escalation paths
- CONTEXTUAL: Environment-specific (prod vs staging)
- POLICY: Rules, compliance, SLAs, security policies
- META: Knowledge about the KB itself

### 2. Entity Extraction
Extract all named entities (services, teams, people, technologies, metrics, alerts, etc.)

### 3. Relationship Extraction
Identify relationships between extracted entities (depends_on, calls, owns, etc.)

### 4. Importance Assessment
Score authority, criticality, uniqueness, actionability, and freshness (0.0-1.0 each)

### 5. Summary and Keywords
- Create a 1-2 sentence summary optimized for search
- Extract 5-10 keywords for indexing

## Output Requirements

Provide a complete ContentAnalysisResult with:
- Knowledge type with confidence and reasoning
- All extracted entities with types and confidence
- All relationships with evidence
- Importance scores with reasoning
- Concise summary
- Relevant keywords

Be thorough but precise. Only extract what is clearly present in the content."""


# =============================================================================
# Conflict Resolution Prompt
# =============================================================================

CONFLICT_RESOLUTION_PROMPT = """You are an expert at resolving conflicts between new and existing knowledge in a technical knowledge base.

A new piece of content has been identified as potentially conflicting with existing content.

## New Content

Source: {new_source}
Content:

{new_content}

## Existing Content

Node ID: {existing_node_id}
Source: {existing_source}
Last Updated: {existing_updated}
Content:

{existing_content}

## Similarity Score

These contents have a {similarity_score:.2f} similarity score.

## Conflict Analysis Tasks

### 1. Determine Relationship

Choose ONE of:
- **DUPLICATE**: Same information with no new value (exact or near-exact match)
- **SUPERSEDES**: New content is more current/complete and should replace existing
- **CONTRADICTS**: Information directly conflicts (different facts about same thing)
- **COMPLEMENTS**: New content adds information without conflicting
- **UNRELATED**: Despite similarity score, these are about different topics

### 2. Recommend Action

Based on the relationship, recommend ONE of:
- **SKIP**: New content is duplicate, don't store
- **REPLACE**: Update existing content with new content
- **MERGE**: Combine both into unified content (provide merged version)
- **ADD_AS_NEW**: Store new content separately, link as related
- **FLAG_REVIEW**: Human review needed (usually for CONTRADICTS)

### 3. Importance Adjustment

Recommend how to adjust importance scores:
- existing_multiplier: 0.0-1.0 (multiply existing node's importance by this)
- new_importance: 0.0-1.0 (importance to assign to new content if stored)

### 4. Confidence and Reasoning

- Rate your confidence in this decision (0.0-1.0)
- Explain your reasoning in detail

### 5. Merged Content (if MERGE recommended)

If recommending MERGE, provide the merged content that combines both sources.

## Decision Guidelines

- Prefer REPLACE for clearly newer/better information
- Use MERGE when both have unique valuable details
- FLAG_REVIEW when facts contradict and you can't determine which is correct
- SKIP only for true duplicates
- ADD_AS_NEW for complementary information on same topic

Return your analysis as structured JSON matching the ConflictResolutionResult schema."""


# =============================================================================
# Batch Processing Prompt
# =============================================================================

BATCH_ENTITY_EXTRACTION_PROMPT = """You are an expert at extracting technical entities from multiple content chunks efficiently.

Extract entities from the following content chunks. Process each chunk and return entities for all of them.

## Entity Types (for reference)
SERVICE, TEAM, PERSON, TECHNOLOGY, METRIC, RUNBOOK, ENVIRONMENT, ALERT, INCIDENT, NAMESPACE

## Content Chunks

{chunks}

## Instructions

For each chunk:
1. Extract all named entities
2. Provide canonical names (lowercase, hyphens)
3. Classify entity types
4. Rate confidence
5. Note context

Return a list of EntityExtractionResult objects, one per chunk, in the same order as the input chunks."""


# =============================================================================
# Query Understanding Prompt
# =============================================================================

QUERY_UNDERSTANDING_PROMPT = """You are an expert at understanding user queries for an incident response knowledge base.

Analyze the following query to understand what the user is looking for.

## Query

{query}

## Analysis Tasks

1. **Query Intent**: What is the user trying to accomplish?
   - TROUBLESHOOT: Looking for how to fix/debug something
   - UNDERSTAND: Wants to learn about a system/concept
   - FIND_CONTACT: Looking for who to contact
   - FIND_PROCEDURE: Looking for a specific runbook/process
   - SEARCH_INCIDENTS: Looking for past incidents
   - CHECK_DEPENDENCY: Understanding service relationships

2. **Entities Mentioned**: What specific entities are referenced?
   - Services, teams, technologies, etc.

3. **Temporal Context**: Is there a time component?
   - Current issue, historical lookup, etc.

4. **Urgency Indicators**: Does this seem urgent?
   - Incident-related keywords, time pressure mentions

5. **Query Expansion**: Suggest related search terms that might help.

Return structured analysis to guide knowledge retrieval."""


# =============================================================================
# Summary Generation Prompt
# =============================================================================

SUMMARY_GENERATION_PROMPT = """You are an expert at creating concise, search-optimized summaries of technical content.

Create a summary for the following content that will be used for:
1. Search result snippets
2. Quick content previews
3. RAG retrieval context

## Content

{content}

## Summary Requirements

1. **Length**: 1-2 sentences, maximum 150 characters
2. **Focus**: Lead with the most important/actionable information
3. **Keywords**: Include key technical terms for search matching
4. **Clarity**: Be specific, avoid vague language
5. **Context**: Include what type of content this is (runbook, spec, etc.)

Good summaries:
- "Runbook for restarting payment-service pods when OOM errors occur in production."
- "API specification for user-service v2 authentication endpoints using OAuth2."

Bad summaries:
- "This document contains information about the service."
- "Steps for handling issues."

Return only the summary text, no additional formatting."""
