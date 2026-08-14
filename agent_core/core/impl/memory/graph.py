# -*- coding: utf-8 -*-
"""
Memory graph — the semantic layer over the indexed memory corpus.

Builds an in-memory entity/fact graph from the chunks already indexed in
ChromaDB (the same corpus BM25 uses), so the graph is a pure derived cache:
the markdown files remain the source of truth and the graph can always be
rebuilt from them.

Structure (three node kinds, bipartite-style edges):
- entity nodes  — LLM-extracted entities ("tham yik foong", "Living UI",
  ...). Size grows with mention count.
- memory nodes  — TWO equal-rank sources: MEMORY.md items (source
  "memory": distilled facts, editable, supersedable) and section chunks
  of indexed files (source "file": read-only, re-derived when the file
  changes).
- file nodes    — one per indexed non-memory file, grouping its chunk
  memories.

Edges: memory↔entity ("mentions") and file↔chunk-memory ("contains").
Entity co-occurrence is implicit through shared memory neighbours, which
keeps the edge count low and the visualisation readable.

A memory↔entity link is one of two states:
- CONFIRMED — recorded by the entity-indexer LLM: a MEMORY.md item's
  ``{entities: ...}`` field, or the ENTITIES.md registry for an indexed
  file whose content still matches the registry hash.
- PENDING — a deterministic provisional link. When a memory has NOT yet
  been reviewed by the entity-indexer, it is attached to any ALREADY-KNOWN
  entity whose name appears in its text. Pending links are shown distinctly
  and are confirmed-or-corrected on the next entity-indexer run. They never
  create entities — they only attach to entities the LLM has established.

ONLY THE ENTITY-INDEXER CREATES/EDITS ENTITIES:
- MEMORY.md items are annotated inline with ``{entities: Name1, Name2}`` by
  the entity-indexer (the memory-processor writes plain items and does no
  entity work). An item without the field is unreviewed → pending links.
- File chunks map to entities through the ENTITIES.md registry, maintained
  by the entity-indexer skill: per-section lines
  ``[path] [content-hash] [section key] Name1, Name2`` whose section keys
  are the chunker's exact section paths (supplied to the skill verbatim).
Confirmed links only ever PARSE those records; pending links only ever
match against entities those records have already created.

Communities are computed with deterministic label propagation (no LLM, no
external dependency) and are used for graph colouring and as retrieval
seed expansion.

Item grammar (superset of the historical format, so existing MEMORY.md
lines remain valid without migration):

    [YYYY-MM-DD HH:MM:SS] [category] content {entities: A, B} {superseded}

- ``{superseded}`` marks an invalidated fact. Superseded items are kept
  (never deleted — history is preserved) but excluded from retrieval.
- The item id is a deterministic hash of (timestamp, clean content), so
  the same line always maps to the same node/chunk id across rebuilds.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

# All numeric behavior constants live in tuning.py — the single typed home
# of the memory system's magic numbers.
from agent_core.core.impl.memory.tuning import (
    ENTITY_SEED_STRENGTH,
    LABEL_PROPAGATION_ROUNDS,
    SECOND_HOP_DECAY,
    STRING_SEEDS_MAX,
)

# ───────────────────────────── Item grammar ─────────────────────────────

# Marks an invalidated fact. The memory-processor appends this marker
# instead of deleting contradicted items.
SUPERSEDED_MARKER = "{superseded}"

# Structured entity field on an item line, written by the memory-processor:
# {entities: Name1, Name2}. An empty field ({entities:}) means "annotated,
# no entities"; an absent field means "not yet annotated".
ENTITIES_FIELD_RE = re.compile(r"\{entities:([^{}]*)\}")

# The per-file entity registry maintained by the entity-indexer skill.
# Two line shapes per indexed file:
#   [path] [content-hash]                          — processed marker
#   [path] [content-hash] [section key] Name1, ... — one per section with entities
# Section keys are the chunker's exact section paths, supplied to the skill
# verbatim in the task instruction so no fuzzy matching is ever needed.
ENTITY_REGISTRY_FILE = "ENTITIES.md"
_REGISTRY_MARKER_RE = re.compile(r"^\[([^\]]+)\]\s+\[([0-9a-fA-F]{6,40})\]\s*$")
_REGISTRY_SECTION_RE = re.compile(
    r"^\[([^\]]+)\]\s+\[([0-9a-fA-F]{6,40})\]\s+\[(.*)\]\s*(.*?)\s*$"
)



def normalize_timestamp(ts: str) -> str:
    """Validate an item timestamp against the canonical 'YYYY-MM-DD HH:MM:SS'.

    That is the ONLY stamp format; every writer emits it exactly. Returns
    the stamp when valid, '' when it is not. Every consumer that derives an
    item id MUST go through this so the same line always hashes to the same
    identity.
    """
    cleaned = (ts or "").strip()
    try:
        datetime.strptime(cleaned, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ""
    return cleaned


def compute_item_id(timestamp: str, content: str) -> str:
    """Deterministic id for a memory item line.

    Same (timestamp, content) → same id across processes and rebuilds,
    which lets the graph node, the Chroma chunk, and the UI item share
    one identity.
    """
    digest = hashlib.md5(f"{timestamp}|{content}".encode("utf-8")).hexdigest()
    return f"m{digest[:12]}"


def _dedup_names(names: List[str]) -> List[str]:
    """Order-preserving, case-insensitive dedup of entity names."""
    seen: Set[str] = set()
    out: List[str] = []
    for name in names:
        name = name.strip()
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def split_item_fields(content: str) -> Tuple[str, Optional[List[str]], bool]:
    """Parse an item's structured tail fields.

    Returns ``(clean_content, entities, superseded)``. ``entities`` is
    None when the line carries no ``{entities: ...}`` field at all (the
    memory-processor has not annotated it yet) and a list — possibly
    empty — when it does. This distinction is what lets the backfill
    trigger find unannotated items without re-processing annotated ones.
    """
    text = content or ""
    superseded = SUPERSEDED_MARKER in text
    if superseded:
        text = text.replace(SUPERSEDED_MARKER, " ")

    entities: Optional[List[str]] = None
    match = ENTITIES_FIELD_RE.search(text)
    if match:
        entities = _dedup_names(match.group(1).split(","))
        text = ENTITIES_FIELD_RE.sub(" ", text)

    clean = re.sub(r"\s{2,}", " ", text).strip()
    return clean, entities, superseded


def item_entities(content: str) -> List[str]:
    """Entity names for an item: its ``{entities: ...}`` field, nothing else.

    The field is written by the memory-processor LLM. Items without the
    field have no entities until its backfill phase annotates them.
    """
    entities = split_item_fields(content)[1]
    return entities or []


def registry_content_hash(content: bytes) -> str:
    """Fingerprint of an indexed file as recorded in ENTITIES.md.

    The entity-index pre-check writes this into the registry and the graph's
    confirmed-file check compares against it, so the derivation lives in ONE
    place: both sides must hash identically or staleness detection silently
    breaks.
    """
    return hashlib.md5(content).hexdigest()[:12]


def parse_entity_registry(content: str) -> Dict[str, Dict[str, Any]]:
    """Parse ENTITIES.md into ``{path: {"hash": str, "sections": {key: [names]}}}``.

    Registry lines are written by the entity-indexer skill. Each processed
    file has a marker line ``[path] [hash]`` plus one
    ``[path] [hash] [section key] Name1, Name2`` line per section with
    entities. The hash is the file's raw-content md5 prefix at extraction
    time, supplied to the skill by the trigger pre-check; comparing it
    against the current file hash is how staleness is detected.
    """
    registry: Dict[str, Dict[str, Any]] = {}

    def entry(path: str, digest: str) -> Dict[str, Any]:
        path = path.strip().replace("\\", "/")
        record = registry.setdefault(path, {"hash": "", "sections": {}})
        record["hash"] = digest.lower()
        return record

    for line in (content or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(">"):
            continue
        marker = _REGISTRY_MARKER_RE.match(line)
        if marker:
            entry(marker.group(1), marker.group(2))
            continue
        section = _REGISTRY_SECTION_RE.match(line)
        if section:
            record = entry(section.group(1), section.group(2))
            names = _dedup_names(section.group(4).split(",")) if section.group(4) else []
            if names:
                record["sections"][section.group(3).strip()] = names
    return registry


# ───────────────────────────── Graph model ─────────────────────────────


@dataclass
class _EntityNode:
    key: str  # normalised (lowercased) name
    name: str  # preferred display form
    item_ids: Set[str] = field(default_factory=set)
    file_paths: Set[str] = field(default_factory=set)
    # Memories provisionally attached to this entity (deterministic match,
    # not yet confirmed by the entity-indexer). Kept separate so the
    # canonical mention_count reflects CONFIRMED knowledge only.
    pending_item_ids: Set[str] = field(default_factory=set)

    @property
    def mention_count(self) -> int:
        return len(self.item_ids) + len(self.file_paths)


@dataclass
class _ItemNode:
    """A memory node. Two sources, equal rank in the brain:

    - ``source="memory"`` — a distilled MEMORY.md item (editable, can be
      superseded, entities from its {entities: ...} field).
    - ``source="file"`` — a section chunk of an indexed file (read-only,
      re-derived when the file changes, entities from the ENTITIES.md
      registry). Carries its file_path and section key.
    """

    item_id: str
    timestamp: str
    category: str
    content: str  # clean text, structured fields stripped
    entities: List[str] = field(default_factory=list)  # CONFIRMED entity keys
    # Provisional entity keys from the deterministic matcher, present only
    # on unreviewed memories. Confirmed by the entity-indexer on its next run.
    pending_entities: List[str] = field(default_factory=list)
    # True once the entity-indexer has reviewed this memory (MEMORY.md item
    # carries an {entities:} field / indexed file matches the registry hash).
    # Unreviewed memories are the ones that get pending links.
    reviewed: bool = False
    superseded: bool = False
    source: str = "memory"
    file_path: str = ""
    section: str = ""


@dataclass
class _FileNode:
    file_path: str
    entities: Set[str] = field(default_factory=set)
    chunk_ids: List[str] = field(default_factory=list)

    @property
    def chunk_count(self) -> int:
        return len(self.chunk_ids)


class MemoryGraph:
    """In-memory entity/item/file graph with traversal and communities.

    Node keys are namespaced to keep the adjacency map unambiguous:
    ``e:<entity key>``, ``i:<item id>``, ``f:<file path>``.
    """

    def __init__(self) -> None:
        self.entities: Dict[str, _EntityNode] = {}
        self.items: Dict[str, _ItemNode] = {}
        self.files: Dict[str, _FileNode] = {}
        self._adjacency: Dict[str, Set[str]] = {}
        self._communities: Dict[str, int] = {}

    # ───────────────────────────── Building ─────────────────────────────

    @classmethod
    def build(
        cls,
        chunks: List[Dict[str, Any]],
        file_registry: Optional[Dict[str, Dict[str, Any]]] = None,
        confirmed_files: Optional[Set[str]] = None,
    ) -> "MemoryGraph":
        """Build the graph from the indexed chunk corpus.

        Chunks of indexed files ARE memories: each section chunk becomes a
        memory node (source="file") grouped under its file node. Confirmed
        entities come from LLM-authored records only — each MEMORY.md item's
        ``{entities: ...}`` field, and the ENTITIES.md registry's
        per-section entries for file chunks whose file is up to date.
        Unreviewed memories then get PENDING links against the entity set
        those records established (see :meth:`_compute_pending_links`).

        Args:
            chunks: dicts with ``chunk_id``, ``document`` and ``metadata``
                (the full ChromaDB collection contents).
            file_registry: parse_entity_registry() output. Entries for
                files no longer indexed are ignored.
            confirmed_files: indexed-file paths whose current content still
                matches their ENTITIES.md registry hash. Only these files'
                chunks are treated as reviewed (their registry sections are
                authoritative, including "reviewed → no entities"); chunks
                of a file that is missing/stale in the registry are
                unreviewed and fall to pending links.
        """
        graph = cls()
        registry = file_registry or {}
        confirmed = confirmed_files or set()

        for chunk in chunks:
            meta = chunk.get("metadata") or {}
            file_path = meta.get("file_path", "")
            if meta.get("item_kind") == "memory_log":
                # Only MEMORY.md items are facts; EVENT_UNPROCESSED.md lines
                # are a transient buffer and would pollute the graph.
                if file_path == "MEMORY.md":
                    graph._add_item_chunk(
                        chunk.get("chunk_id", ""), chunk.get("document", ""), meta
                    )
            elif file_path and file_path != ENTITY_REGISTRY_FILE:
                # The registry file itself is bookkeeping, not a knowledge
                # source worth nodes.
                is_reviewed = file_path in confirmed
                sections = (
                    (registry.get(file_path) or {}).get("sections", {})
                    if is_reviewed
                    else {}
                )
                graph._add_file_memory_chunk(
                    chunk.get("chunk_id", ""),
                    chunk.get("document", ""),
                    meta,
                    sections,
                    is_reviewed,
                )

        # Deterministic provisional links come AFTER every confirmed record
        # is in, so the known-entity set they match against is complete.
        graph._compute_pending_links()
        graph._compute_communities()
        return graph

    def _link(self, a: str, b: str) -> None:
        self._adjacency.setdefault(a, set()).add(b)
        self._adjacency.setdefault(b, set()).add(a)

    def _ensure_entity(self, name: str) -> _EntityNode:
        key = name.strip().lower()
        node = self.entities.get(key)
        if node is None:
            node = _EntityNode(key=key, name=name.strip())
            self.entities[key] = node
        elif node.name.islower() and not name.islower():
            # Prefer a cased surface form for display.
            node.name = name.strip()
        return node

    def _add_item_chunk(self, chunk_id: str, document: str, meta: Dict[str, Any]) -> None:
        # The chunk document is the full bracketed line; clean content and
        # flags live in metadata written by the chunker. The entities value
        # is the item's {entities: ...} field — LLM-authored, parsed from
        # metadata (or re-parsed from the line itself, same record).
        content = meta.get("item_content") or split_item_fields(document)[0]
        superseded = bool(meta.get("superseded", False))
        file_path = meta.get("file_path", "MEMORY.md")

        if "entities" in meta:
            entity_names = _dedup_names((meta.get("entities") or "").split(","))
        else:
            entity_names = item_entities(document)

        item = _ItemNode(
            item_id=chunk_id,
            timestamp=meta.get("timestamp", ""),
            category=meta.get("category", "fact"),
            content=content,
            # Reviewed iff the item carries an {entities:} field (written by
            # the entity-indexer); the chunker records that as this flag.
            reviewed=bool(meta.get("entities_annotated")),
            superseded=superseded,
            file_path=file_path,
        )
        self.items[chunk_id] = item

        # MEMORY.md shows up as a normal file node, exactly like the other
        # indexed files: its items hang off it via contains edges.
        file_node = self.files.get(file_path)
        if file_node is None:
            file_node = _FileNode(file_path=file_path)
            self.files[file_path] = file_node
        file_node.chunk_ids.append(chunk_id)
        self._link(f"f:{file_path}", f"i:{chunk_id}")

        for name in entity_names:
            entity = self._ensure_entity(name)
            entity.item_ids.add(chunk_id)
            item.entities.append(entity.key)
            self._link(f"i:{chunk_id}", f"e:{entity.key}")

    def _add_file_memory_chunk(
        self,
        chunk_id: str,
        document: str,
        meta: Dict[str, Any],
        section_entities: Dict[str, List[str]],
        reviewed: bool,
    ) -> None:
        """A section chunk of an indexed file — a memory sourced from a file.

        Creates the chunk's memory node linked under its file node. When the
        file is reviewed (its registry hash matches), links it to the
        entities the ENTITIES.md registry records for its exact section key
        — and a reviewed section with no registry entities is genuinely
        entity-free, not pending. An unreviewed file's chunks get no
        confirmed entities and fall to pending links. The node carries the
        chunk's FULL text (the summary is a truncated derivative — showing
        it in detail views reads as the memory being cut off, which it is
        not).
        """
        file_path = meta.get("file_path", "")
        if not chunk_id or not file_path:
            return

        node = self.files.get(file_path)
        if node is None:
            node = _FileNode(file_path=file_path)
            self.files[file_path] = node
        node.chunk_ids.append(chunk_id)

        section = meta.get("section_path", "")
        item = _ItemNode(
            item_id=chunk_id,
            timestamp=meta.get("file_modified_at", ""),
            category="file",
            content=document,
            reviewed=reviewed,
            source="file",
            file_path=file_path,
            section=section,
        )
        self.items[chunk_id] = item
        self._link(f"f:{file_path}", f"i:{chunk_id}")

        for name in section_entities.get(section, []):
            entity = self._ensure_entity(name)
            entity.item_ids.add(chunk_id)
            entity.file_paths.add(file_path)
            item.entities.append(entity.key)
            node.entities.add(entity.key)
            self._link(f"i:{chunk_id}", f"e:{entity.key}")

    def _compute_pending_links(self) -> None:
        """Deterministic provisional memory→entity links.

        Runs once every confirmed record is loaded, so it matches against
        the COMPLETE known-entity set. For each unreviewed, non-superseded
        memory it attaches the memory to any already-known entity whose
        whole (normalised) name appears in the memory text. These links are
        marked pending on the item and mirrored into the adjacency (so the
        physics pulls the memory toward its provisional entity and the two
        colour together), but they never inflate an entity's canonical
        mention_count and never create a new entity.
        """
        if not self.entities:
            return

        # Precompute " normalised name " needles once.
        needles: List[Tuple[str, str]] = []
        for key in self.entities:
            norm = re.sub(r"[^a-z0-9]+", " ", key).strip()
            if norm:
                needles.append((f" {norm} ", key))
        if not needles:
            return

        for item in self.items.values():
            # A reviewed memory (or one that already carries confirmed
            # entities) has been decided — never guess over the top of it.
            if item.reviewed or item.entities or item.superseded:
                continue
            haystack = f" {re.sub(r'[^a-z0-9]+', ' ', item.content.lower())} "
            for needle, key in needles:
                if needle in haystack:
                    item.pending_entities.append(key)
                    self.entities[key].pending_item_ids.add(item.item_id)
                    self._link(f"i:{item.item_id}", f"e:{key}")

    # ─────────────────────────── Communities ───────────────────────────

    def _compute_communities(self) -> None:
        """Deterministic label propagation over the whole graph.

        Nodes are visited in sorted order every round with asynchronous
        updates, ties broken by the smallest label — fully deterministic
        for a given graph, so the panel colouring is stable across loads.
        """
        nodes = sorted(self._adjacency.keys())
        labels: Dict[str, int] = {key: i for i, key in enumerate(nodes)}

        for _ in range(LABEL_PROPAGATION_ROUNDS):
            changed = False
            for key in nodes:
                neighbour_labels = Counter(
                    labels[n] for n in self._adjacency.get(key, ()) if n in labels
                )
                if not neighbour_labels:
                    continue
                best_count = max(neighbour_labels.values())
                best = min(
                    label for label, count in neighbour_labels.items() if count == best_count
                )
                if labels[key] != best:
                    labels[key] = best
                    changed = True
            if not changed:
                break

        # Compact label ids to 0..n-1 ordered by community size (largest first)
        # so colour palettes assign their strongest colours to the big clusters.
        sizes = Counter(labels.values())
        order = {
            label: rank
            for rank, (label, _) in enumerate(
                sorted(sizes.items(), key=lambda kv: (-kv[1], kv[0]))
            )
        }
        self._communities = {key: order[label] for key, label in labels.items()}

    def community_of(self, node_key: str) -> int:
        return self._communities.get(node_key, 0)

    @property
    def community_count(self) -> int:
        return len(set(self._communities.values())) if self._communities else 0

    # ───────────────────────────── Retrieval ─────────────────────────────

    def match_entities(
        self, query: str, max_seeds: int = STRING_SEEDS_MAX
    ) -> List[Tuple[str, float]]:
        """Match query text against entity names.

        Returns (entity_key, strength) pairs. Exact phrase presence and
        all name tokens present both score ENTITY_SEED_STRENGTH.
        """
        if not query or not self.entities:
            return []

        query_lower = f" {re.sub(r'[^a-z0-9]+', ' ', query.lower())} "
        query_tokens = set(query_lower.split())

        matches: List[Tuple[str, float]] = []
        for key, entity in self.entities.items():
            name_norm = re.sub(r"[^a-z0-9]+", " ", key).strip()
            if not name_norm:
                continue
            if f" {name_norm} " in query_lower:
                matches.append((key, ENTITY_SEED_STRENGTH))
                continue
            tokens = name_norm.split()
            if len(tokens) > 1 and all(t in query_tokens for t in tokens):
                matches.append((key, ENTITY_SEED_STRENGTH))

        matches.sort(key=lambda pair: (-pair[1], pair[0]))
        return matches[:max_seeds]

    def bfs_item_scores(
        self, seeds: List[Tuple[str, float]], include_superseded: bool = False
    ) -> Dict[str, float]:
        """Score items reachable from seed entities within 2 hops.

        Hop 1 (items of a seed entity) scores the seed strength; hop 2
        (items of entities co-mentioned with a seed) decays. When several
        seeds reach the same item, the best score wins.
        """
        scores: Dict[str, float] = {}
        for entity_key, strength in seeds:
            entity = self.entities.get(entity_key)
            if entity is None:
                continue
            second_hop_entities: Set[str] = set()
            for item_id in entity.item_ids:
                item = self.items.get(item_id)
                if item is None or (item.superseded and not include_superseded):
                    continue
                scores[item_id] = max(scores.get(item_id, 0.0), strength)
                second_hop_entities.update(item.entities)
            second_hop_entities.discard(entity_key)
            for other_key in second_hop_entities:
                other = self.entities.get(other_key)
                if other is None:
                    continue
                for item_id in other.item_ids:
                    item = self.items.get(item_id)
                    if item is None or (item.superseded and not include_superseded):
                        continue
                    hop_score = strength * SECOND_HOP_DECAY
                    scores[item_id] = max(scores.get(item_id, 0.0), hop_score)
        return scores

    # ─────────────────────────── Introspection ───────────────────────────

    def entity_overview(self, name: str) -> Optional[Dict[str, Any]]:
        """Everything the graph knows about one entity."""
        key = (name or "").strip().lower()
        entity = self.entities.get(key)
        if entity is None:
            return None

        items = []
        related: Counter = Counter()
        for item_id in sorted(entity.item_ids):
            item = self.items.get(item_id)
            if item is None:
                continue
            items.append(
                {
                    "item_id": item.item_id,
                    "timestamp": item.timestamp,
                    "category": item.category,
                    "content": item.content,
                    "superseded": item.superseded,
                    "source": item.source,
                    "file": item.file_path,
                    "section": item.section,
                }
            )
            for other in item.entities:
                if other != key:
                    related[other] += 1

        items.sort(key=lambda i: i["timestamp"], reverse=True)
        return {
            "entity": entity.name,
            "mention_count": entity.mention_count,
            "items": items,
            "related_entities": [
                {"name": self.entities[k].name, "shared_items": count}
                for k, count in related.most_common(10)
                if k in self.entities
            ],
            "files": sorted(entity.file_paths),
        }

    def shortest_path(self, name_a: str, name_b: str) -> List[Dict[str, Any]]:
        """Shortest connection between two entities (BFS over all nodes).

        Returns the node sequence (entities, items, files) or [] when no
        path exists / an endpoint is unknown.
        """
        start = f"e:{(name_a or '').strip().lower()}"
        goal = f"e:{(name_b or '').strip().lower()}"
        if start not in self._adjacency or goal not in self._adjacency:
            return []
        if start == goal:
            return [self._node_payload(start)]

        parents: Dict[str, str] = {start: ""}
        frontier = [start]
        while frontier and goal not in parents:
            next_frontier: List[str] = []
            for node in frontier:
                for neighbour in sorted(self._adjacency.get(node, ())):
                    if neighbour not in parents:
                        parents[neighbour] = node
                        next_frontier.append(neighbour)
            frontier = next_frontier

        if goal not in parents:
            return []

        path: List[str] = []
        cursor = goal
        while cursor:
            path.append(cursor)
            cursor = parents[cursor]
        path.reverse()
        return [self._node_payload(key) for key in path]

    def _node_payload(self, node_key: str) -> Dict[str, Any]:
        kind, _, ref = node_key.partition(":")
        if kind == "e":
            entity = self.entities.get(ref)
            return {
                "kind": "entity",
                "id": node_key,
                "label": entity.name if entity else ref,
            }
        if kind == "i":
            item = self.items.get(ref)
            return {
                "kind": "item",
                "id": node_key,
                "label": (item.content[:80] if item else ref),
                "category": item.category if item else "",
                "superseded": item.superseded if item else False,
            }
        return {"kind": "file", "id": node_key, "label": ref}

    def snapshot(self) -> Dict[str, Any]:
        """Full graph serialisation for the Memory panel."""
        nodes: List[Dict[str, Any]] = []
        edges: List[Dict[str, str]] = []

        for key in sorted(self.entities):
            entity = self.entities[key]
            node_key = f"e:{key}"
            nodes.append(
                {
                    "id": node_key,
                    "kind": "entity",
                    "label": entity.name,
                    "size": entity.mention_count,
                    "community": self.community_of(node_key),
                }
            )

        for item_id in sorted(self.items):
            item = self.items[item_id]
            node_key = f"i:{item_id}"
            nodes.append(
                {
                    "id": node_key,
                    "kind": "item",
                    "label": item.content,
                    "category": item.category,
                    "timestamp": item.timestamp,
                    "superseded": item.superseded,
                    "source": item.source,
                    "file": item.file_path,
                    "section": item.section,
                    "community": self.community_of(node_key),
                }
            )
            for entity_key in item.entities:
                edges.append(
                    {
                        "source": node_key,
                        "target": f"e:{entity_key}",
                        "status": "confirmed",
                    }
                )
            for entity_key in item.pending_entities:
                edges.append(
                    {
                        "source": node_key,
                        "target": f"e:{entity_key}",
                        "status": "pending",
                    }
                )

        for file_path in sorted(self.files):
            file_node = self.files[file_path]
            node_key = f"f:{file_path}"
            nodes.append(
                {
                    "id": node_key,
                    "kind": "file",
                    "label": file_path,
                    "size": file_node.chunk_count,
                    "community": self.community_of(node_key),
                }
            )
            # Files group their chunk memories.
            for chunk_id in file_node.chunk_ids:
                edges.append({"source": node_key, "target": f"i:{chunk_id}"})

        memory_items = [i for i in self.items.values() if i.source == "memory"]
        return {
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "entity_count": len(self.entities),
                "item_count": len(memory_items),
                "file_memory_count": sum(
                    1 for i in self.items.values() if i.source == "file"
                ),
                "file_count": len(self.files),
                "edge_count": len(edges),
                "pending_link_count": sum(
                    len(i.pending_entities) for i in self.items.values()
                ),
                "community_count": self.community_count,
                "superseded_count": sum(1 for i in memory_items if i.superseded),
            },
        }
