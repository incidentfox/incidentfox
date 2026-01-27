"""
Knowledge Graph implementation.

Provides entity and relationship management with graph traversal
capabilities for hybrid RAPTOR+Graph retrieval.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .entities import Entity, EntityType
from .relationships import Relationship, RelationshipType

logger = logging.getLogger(__name__)


@dataclass
class GraphPath:
    """
    A path through the knowledge graph.

    Represents a sequence of entities connected by relationships.
    """

    entities: List[Entity]
    relationships: List[Relationship]
    total_distance: int  # Number of hops

    @property
    def start(self) -> Optional[Entity]:
        return self.entities[0] if self.entities else None

    @property
    def end(self) -> Optional[Entity]:
        return self.entities[-1] if self.entities else None

    def get_raptor_node_ids(self) -> List[int]:
        """Get all RAPTOR node IDs from entities in this path."""
        node_ids = []
        for entity in self.entities:
            node_ids.extend(entity.node_ids)
        return list(set(node_ids))


@dataclass
class GraphQuery:
    """
    A query against the knowledge graph.
    """

    # Starting point(s)
    start_entities: List[str] = field(default_factory=list)  # Entity IDs
    start_types: List[EntityType] = field(default_factory=list)  # Or by type

    # Traversal constraints
    relationship_types: List[RelationshipType] = field(default_factory=list)
    max_hops: int = 2
    direction: str = "outgoing"  # outgoing, incoming, both

    # Filtering
    target_types: List[EntityType] = field(default_factory=list)
    min_confidence: float = 0.0

    # Results
    limit: int = 100


class KnowledgeGraph:
    """
    In-memory knowledge graph with entity and relationship management.

    For production, this could be backed by Neo4j, Amazon Neptune,
    or other graph databases.
    """

    def __init__(self):
        # Entity storage
        self._entities: Dict[str, Entity] = {}
        self._entities_by_type: Dict[EntityType, Set[str]] = {}
        self._entities_by_name: Dict[str, Set[str]] = {}  # name.lower() -> entity_ids

        # Relationship storage
        self._relationships: Dict[str, Relationship] = {}
        self._outgoing: Dict[str, Set[str]] = {}  # entity_id -> relationship_ids
        self._incoming: Dict[str, Set[str]] = {}  # entity_id -> relationship_ids
        self._by_type: Dict[RelationshipType, Set[str]] = (
            {}
        )  # rel_type -> relationship_ids

        # Metadata
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    # ==================== Entity Operations ====================

    def add_entity(self, entity: Entity) -> None:
        """Add an entity to the graph."""
        self._entities[entity.entity_id] = entity

        # Index by type
        if entity.entity_type not in self._entities_by_type:
            self._entities_by_type[entity.entity_type] = set()
        self._entities_by_type[entity.entity_type].add(entity.entity_id)

        # Index by name (lowercase for fuzzy matching)
        name_key = entity.name.lower()
        if name_key not in self._entities_by_name:
            self._entities_by_name[name_key] = set()
        self._entities_by_name[name_key].add(entity.entity_id)

        # Also index aliases
        for alias in entity.aliases:
            alias_key = alias.lower()
            if alias_key not in self._entities_by_name:
                self._entities_by_name[alias_key] = set()
            self._entities_by_name[alias_key].add(entity.entity_id)

        # Initialize relationship sets
        if entity.entity_id not in self._outgoing:
            self._outgoing[entity.entity_id] = set()
        if entity.entity_id not in self._incoming:
            self._incoming[entity.entity_id] = set()

        self.updated_at = datetime.utcnow()

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Get an entity by ID."""
        return self._entities.get(entity_id)

    def find_entity(self, name: str) -> Optional[Entity]:
        """Find an entity by name (case-insensitive)."""
        name_key = name.lower()
        entity_ids = self._entities_by_name.get(name_key, set())
        if entity_ids:
            return self._entities.get(next(iter(entity_ids)))
        return None

    def find_entities(
        self,
        name: Optional[str] = None,
        entity_type: Optional[EntityType] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Entity]:
        """Find entities matching criteria."""
        candidates = set(self._entities.keys())

        # Filter by type
        if entity_type:
            type_ids = self._entities_by_type.get(entity_type, set())
            candidates &= type_ids

        # Filter by name
        if name:
            name_key = name.lower()
            name_ids = self._entities_by_name.get(name_key, set())
            # Also do partial matching
            partial_ids = set()
            for key, ids in self._entities_by_name.items():
                if name_key in key:
                    partial_ids |= ids
            candidates &= name_ids | partial_ids

        # Get entities
        entities = [self._entities[eid] for eid in candidates if eid in self._entities]

        # Filter by tags
        if tags:
            tag_set = set(t.lower() for t in tags)
            entities = [
                e for e in entities if tag_set.issubset(set(t.lower() for t in e.tags))
            ]

        return entities

    def get_entities_by_type(self, entity_type: EntityType) -> List[Entity]:
        """Get all entities of a specific type."""
        entity_ids = self._entities_by_type.get(entity_type, set())
        return [self._entities[eid] for eid in entity_ids if eid in self._entities]

    def remove_entity(self, entity_id: str) -> bool:
        """Remove an entity and its relationships."""
        if entity_id not in self._entities:
            return False

        entity = self._entities[entity_id]

        # Remove from type index
        if entity.entity_type in self._entities_by_type:
            self._entities_by_type[entity.entity_type].discard(entity_id)

        # Remove from name index
        name_key = entity.name.lower()
        if name_key in self._entities_by_name:
            self._entities_by_name[name_key].discard(entity_id)

        # Remove relationships
        for rel_id in list(self._outgoing.get(entity_id, [])):
            self.remove_relationship(rel_id)
        for rel_id in list(self._incoming.get(entity_id, [])):
            self.remove_relationship(rel_id)

        # Remove entity
        del self._entities[entity_id]
        self._outgoing.pop(entity_id, None)
        self._incoming.pop(entity_id, None)

        self.updated_at = datetime.utcnow()
        return True

    # ==================== Relationship Operations ====================

    def add_relationship(self, rel: Relationship) -> None:
        """Add a relationship to the graph."""
        self._relationships[rel.relationship_id] = rel

        # Index by source/target
        if rel.source_id not in self._outgoing:
            self._outgoing[rel.source_id] = set()
        self._outgoing[rel.source_id].add(rel.relationship_id)

        if rel.target_id not in self._incoming:
            self._incoming[rel.target_id] = set()
        self._incoming[rel.target_id].add(rel.relationship_id)

        # Index by type
        if rel.relationship_type not in self._by_type:
            self._by_type[rel.relationship_type] = set()
        self._by_type[rel.relationship_type].add(rel.relationship_id)

        self.updated_at = datetime.utcnow()

    def get_relationship(self, rel_id: str) -> Optional[Relationship]:
        """Get a relationship by ID."""
        return self._relationships.get(rel_id)

    def get_relationships(
        self,
        entity_id: str,
        direction: str = "both",
        rel_types: Optional[List[RelationshipType]] = None,
    ) -> List[Relationship]:
        """Get relationships for an entity."""
        rel_ids = set()

        if direction in ("outgoing", "both"):
            rel_ids |= self._outgoing.get(entity_id, set())

        if direction in ("incoming", "both"):
            rel_ids |= self._incoming.get(entity_id, set())

        relationships = [
            self._relationships[rid] for rid in rel_ids if rid in self._relationships
        ]

        # Filter by type
        if rel_types:
            relationships = [
                r for r in relationships if r.relationship_type in rel_types
            ]

        # Filter to active only
        relationships = [r for r in relationships if r.is_active]

        return relationships

    def find_relationship(
        self,
        source_id: str,
        target_id: str,
        rel_type: Optional[RelationshipType] = None,
    ) -> Optional[Relationship]:
        """Find a specific relationship between two entities."""
        for rel_id in self._outgoing.get(source_id, set()):
            rel = self._relationships.get(rel_id)
            if rel and rel.target_id == target_id:
                if rel_type is None or rel.relationship_type == rel_type:
                    return rel
        return None

    def remove_relationship(self, rel_id: str) -> bool:
        """Remove a relationship."""
        if rel_id not in self._relationships:
            return False

        rel = self._relationships[rel_id]

        # Remove from indexes
        if rel.source_id in self._outgoing:
            self._outgoing[rel.source_id].discard(rel_id)
        if rel.target_id in self._incoming:
            self._incoming[rel.target_id].discard(rel_id)
        if rel.relationship_type in self._by_type:
            self._by_type[rel.relationship_type].discard(rel_id)

        del self._relationships[rel_id]
        self.updated_at = datetime.utcnow()
        return True

    # ==================== Graph Traversal ====================

    def traverse(
        self,
        start_entity_id: str,
        max_hops: int = 2,
        relationship_types: Optional[List[RelationshipType]] = None,
        direction: str = "outgoing",
        target_types: Optional[List[EntityType]] = None,
        min_confidence: float = 0.0,
    ) -> List[Tuple[Entity, int, List[Relationship]]]:
        """
        Traverse the graph from a starting entity.

        Args:
            start_entity_id: Starting entity
            max_hops: Maximum traversal depth
            relationship_types: Only follow these relationship types
            direction: 'outgoing', 'incoming', or 'both'
            target_types: Only return entities of these types
            min_confidence: Minimum relationship confidence

        Returns:
            List of (entity, distance, path_relationships) tuples
        """
        if start_entity_id not in self._entities:
            return []

        visited: Set[str] = {start_entity_id}
        results: List[Tuple[Entity, int, List[Relationship]]] = []
        queue: List[Tuple[str, int, List[Relationship]]] = [(start_entity_id, 0, [])]

        while queue:
            current_id, distance, path = queue.pop(0)

            if distance > 0:
                entity = self._entities.get(current_id)
                if entity:
                    # Check target type filter
                    if target_types is None or entity.entity_type in target_types:
                        results.append((entity, distance, path))

            if distance >= max_hops:
                continue

            # Get relationships
            relationships = self.get_relationships(
                current_id,
                direction=direction,
                rel_types=relationship_types,
            )

            for rel in relationships:
                # Check confidence
                if rel.confidence < min_confidence:
                    continue

                # Determine next entity
                next_id = (
                    rel.target_id if rel.source_id == current_id else rel.source_id
                )

                if next_id not in visited:
                    visited.add(next_id)
                    queue.append((next_id, distance + 1, path + [rel]))

        return results

    def find_paths(
        self,
        start_entity_id: str,
        end_entity_id: str,
        max_hops: int = 3,
        relationship_types: Optional[List[RelationshipType]] = None,
    ) -> List[GraphPath]:
        """
        Find all paths between two entities.

        Args:
            start_entity_id: Starting entity
            end_entity_id: Target entity
            max_hops: Maximum path length
            relationship_types: Only follow these relationship types

        Returns:
            List of GraphPath objects
        """
        if start_entity_id not in self._entities:
            return []
        if end_entity_id not in self._entities:
            return []

        paths: List[GraphPath] = []

        def dfs(
            current: str,
            target: str,
            visited: Set[str],
            entity_path: List[Entity],
            rel_path: List[Relationship],
            depth: int,
        ):
            if depth > max_hops:
                return

            if current == target:
                paths.append(
                    GraphPath(
                        entities=entity_path.copy(),
                        relationships=rel_path.copy(),
                        total_distance=len(rel_path),
                    )
                )
                return

            relationships = self.get_relationships(
                current,
                direction="both",
                rel_types=relationship_types,
            )

            for rel in relationships:
                next_id = rel.target_id if rel.source_id == current else rel.source_id

                if next_id not in visited:
                    next_entity = self._entities.get(next_id)
                    if next_entity:
                        visited.add(next_id)
                        entity_path.append(next_entity)
                        rel_path.append(rel)

                        dfs(next_id, target, visited, entity_path, rel_path, depth + 1)

                        entity_path.pop()
                        rel_path.pop()
                        visited.remove(next_id)

        start_entity = self._entities[start_entity_id]
        dfs(
            start_entity_id,
            end_entity_id,
            {start_entity_id},
            [start_entity],
            [],
            0,
        )

        return paths

    def get_neighborhood(
        self,
        entity_id: str,
        hops: int = 1,
    ) -> Dict[str, Any]:
        """
        Get the neighborhood of an entity.

        Returns a subgraph containing the entity and its neighbors.
        """
        if entity_id not in self._entities:
            return {"entities": [], "relationships": []}

        traversal = self.traverse(
            entity_id,
            max_hops=hops,
            direction="both",
        )

        # Collect entities
        entities = [self._entities[entity_id]]
        for entity, _, _ in traversal:
            entities.append(entity)

        # Collect relationships
        entity_ids = {e.entity_id for e in entities}
        relationships = []
        for eid in entity_ids:
            for rel in self.get_relationships(eid, direction="outgoing"):
                if rel.source_id in entity_ids and rel.target_id in entity_ids:
                    if rel not in relationships:
                        relationships.append(rel)

        return {
            "entities": entities,
            "relationships": relationships,
        }

    # ==================== Query Execution ====================

    def execute_query(
        self, query: GraphQuery
    ) -> List[Tuple[Entity, int, List[Relationship]]]:
        """
        Execute a graph query.

        Returns list of (entity, distance, path) tuples.
        """
        results = []

        # Get starting entities
        start_entities = []
        for eid in query.start_entities:
            entity = self._entities.get(eid)
            if entity:
                start_entities.append(entity)

        for etype in query.start_types:
            start_entities.extend(self.get_entities_by_type(etype))

        # Traverse from each start
        for start in start_entities:
            traversal = self.traverse(
                start.entity_id,
                max_hops=query.max_hops,
                relationship_types=(
                    query.relationship_types if query.relationship_types else None
                ),
                direction=query.direction,
                target_types=query.target_types if query.target_types else None,
                min_confidence=query.min_confidence,
            )
            results.extend(traversal)

        # Deduplicate and sort by distance
        seen = set()
        unique_results = []
        for entity, dist, path in results:
            if entity.entity_id not in seen:
                seen.add(entity.entity_id)
                unique_results.append((entity, dist, path))

        unique_results.sort(key=lambda x: x[1])

        return unique_results[: query.limit]

    # ==================== RAPTOR Integration ====================

    def get_raptor_nodes_for_entities(
        self,
        entity_ids: List[str],
    ) -> Dict[str, List[int]]:
        """
        Get RAPTOR node IDs for a list of entities.

        Returns mapping of entity_id -> node_ids.
        """
        result = {}
        for eid in entity_ids:
            entity = self._entities.get(eid)
            if entity and entity.node_ids:
                result[eid] = entity.node_ids
        return result

    def get_entities_for_raptor_node(self, node_id: int) -> List[Entity]:
        """Get all entities that reference a specific RAPTOR node."""
        return [e for e in self._entities.values() if node_id in e.node_ids]

    def expand_to_raptor_nodes(
        self,
        start_entity_id: str,
        max_hops: int = 2,
        relationship_types: Optional[List[RelationshipType]] = None,
    ) -> List[int]:
        """
        Expand from an entity to get all related RAPTOR node IDs.

        Useful for hybrid graph+tree retrieval.
        """
        # Get start entity's nodes
        node_ids = set()
        start_entity = self._entities.get(start_entity_id)
        if start_entity:
            node_ids.update(start_entity.node_ids)

        # Traverse and collect node IDs
        traversal = self.traverse(
            start_entity_id,
            max_hops=max_hops,
            relationship_types=relationship_types,
            direction="both",
        )

        for entity, _, _ in traversal:
            node_ids.update(entity.node_ids)

        return list(node_ids)

    # ==================== Serialization ====================

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the graph to a dictionary."""
        return {
            "entities": [e.to_dict() for e in self._entities.values()],
            "relationships": [r.to_dict() for r in self._relationships.values()],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KnowledgeGraph":
        """Deserialize a graph from a dictionary."""
        graph = cls()

        # Load entities
        for e_data in data.get("entities", []):
            entity = Entity.from_dict(e_data)
            graph.add_entity(entity)

        # Load relationships
        for r_data in data.get("relationships", []):
            rel = Relationship.from_dict(r_data)
            graph.add_relationship(rel)

        if data.get("created_at"):
            graph.created_at = datetime.fromisoformat(data["created_at"])
        if data.get("updated_at"):
            graph.updated_at = datetime.fromisoformat(data["updated_at"])

        return graph

    # ==================== Statistics ====================

    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics."""
        return {
            "total_entities": len(self._entities),
            "total_relationships": len(self._relationships),
            "entities_by_type": {
                etype.value: len(eids) for etype, eids in self._entities_by_type.items()
            },
            "relationships_by_type": {
                rtype.value: len(rids) for rtype, rids in self._by_type.items()
            },
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
