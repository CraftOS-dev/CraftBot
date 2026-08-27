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

CONNECTIONS ARE ESTABLISHED IN EXACTLY ONE PLACE: the graph build. For
every memory, the deterministic matcher connects it to each known entity
whose name appears in its text. Nothing else creates a connection — not
the entity-indexer, not any record.

CONNECTIONS ARE RECORDED IN ENTITIES.md BY THE SYSTEM: after every build,
the ``## Connections`` section is re-synced to one line per memory —
``[chunk-id] [status] names :: text preview`` — carrying each established
connection's state as a mark on the entity name: plain = CONFIRMED,
``!`` = REJECTED (no edge), ``?`` = PENDING (edge drawn as provisional,
awaiting judgment). The entity-indexer's ONLY connection job is flipping
``?`` marks to plain or ``!`` and setting the line's status to [judged];
it never adds names. A mark on a name the matcher did not establish is
ignored — structurally, nothing but the matcher can introduce a
connection. Dead chunk ids (memory changed or deleted) drop out of the
section automatically at the next sync; changed content produces a new
chunk id whose line starts pending again, so the records self-invalidate
with no hashes and no staleness bookkeeping.

ENTITIES COME FROM EXACTLY ONE PLACE: the ``## Entities`` list in
ENTITIES.md (one name per line), created and maintained solely by the
entity-judge pipeline. The matcher's known-entity set IS that list. When a
new entity is created, the next build matches it and the sync appends it
as a ``?`` candidate on the affected memories' lines for judgment.

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
    CONNECTION_PREVIEW_MAX_CHARS,
    ENTITY_HUB_FRACTION,
    ENTITY_HUB_MIN_LINKS,
    ENTITY_SEED_STRENGTH,
    LABEL_PROPAGATION_ROUNDS,
    SECOND_HOP_DECAY,
    STRING_SEEDS_MAX,
)

# ───────────────────────────── Item grammar ─────────────────────────────

# Marks an invalidated fact. The memory-processor appends this marker
# instead of deleting contradicted items.
SUPERSEDED_MARKER = "{superseded}"

# Legacy structured entity field on an item line ({entities: Name1, ...}).
# It is part of the item-line grammar only so its markup is STRIPPED from
# item content; it plays no role in the connection system.
ENTITIES_FIELD_RE = re.compile(r"\{entities:([^{}]*)\}")

# The entity registry file, with two code-defined sections:
# - "## Entities": one entity name per line, created only by the
#   entity-judge pipeline. The graph's entire entity set.
# - "## Connections": one record per memory, WRITTEN AND RE-SYNCED BY THE
#   SYSTEM after every graph build. The entity judge only flips marks.
ENTITY_REGISTRY_FILE = "ENTITIES.md"

# A connection record line under "## Connections":
#   [<chunk-id>] [pending|judged] Name1, !Name2, ?Name3 :: <text preview>
# Chunk ids are the memory content hashes ("m"/"c" + 12 hex, optional "-N"
# duplicate suffix) — the one identity shared by Chroma, graph, and UI.
# Name marks: plain = confirmed, "!" = rejected, "?" = awaiting judgment.
# Status is [pending] while any "?" remains (or the memory was never
# judged), [judged] once the entity-indexer has decided every name.
CONNECTION_LINE_RE = re.compile(
    r"^\[([mc][0-9a-f]{12}(?:-\d+)?)\]\s+\[(pending|judged)\]\s*(.*)$"
)
_CONNECTION_TEXT_SEPARATOR = " :: "



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


def parse_entity_registry(content: str) -> Dict[str, Any]:
    """Parse ENTITIES.md into ``{"entities": [...], "connections": {...}}``.

    - ``entities``: the names listed one-per-line under ``## Entities``
      (entity-indexer-owned; the graph's entire entity set).
    - ``connections``: ``{chunk_id: {"status", "confirmed", "rejected",
      "pending"}}`` from the system-synced connection record lines. Name
      marks: plain = confirmed, ``!`` = rejected, ``?`` = awaiting
      judgment. The text preview after ``" :: "`` is display-only and
      ignored here (the sync regenerates it).
    """
    entities: List[str] = []
    connections: Dict[str, Dict[str, Any]] = {}
    in_entities_section = False

    for line in (content or "").splitlines():
        line = line.strip()
        if line.startswith("#"):
            in_entities_section = line.lstrip("#").strip().lower() == "entities"
            continue
        if not line or line.startswith(">"):
            continue
        match = CONNECTION_LINE_RE.match(line)
        if match:
            names_part = match.group(3).split(_CONNECTION_TEXT_SEPARATOR, 1)[0]
            confirmed: List[str] = []
            rejected: List[str] = []
            pending: List[str] = []
            for raw in names_part.split(","):
                name = raw.strip()
                if not name:
                    continue
                if name.startswith("!"):
                    rejected.append(name[1:].strip())
                elif name.startswith("?"):
                    pending.append(name[1:].strip())
                else:
                    confirmed.append(name)
            connections[match.group(1)] = {
                "status": match.group(2),
                "confirmed": _dedup_names(confirmed),
                "rejected": _dedup_names(rejected),
                "pending": _dedup_names(pending),
            }
            continue
        if in_entities_section:
            entities.append(line)

    return {"entities": _dedup_names(entities), "connections": connections}


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
    # Matcher-established connections the entity-indexer REJECTED — no
    # edge, kept so the connection-record sync preserves the "!" marks.
    rejected_entities: List[str] = field(default_factory=list)
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
        # Parsed ## Connections records keyed by chunk id: each holds the
        # lowered confirmed / rejected name sets and the line status. A
        # matched entity's state comes from its mark; matched entities with
        # no mark (or no record) are pending.
        self._records: Dict[str, Dict[str, Any]] = {}

    # ───────────────────────────── Building ─────────────────────────────

    @classmethod
    def build(
        cls,
        chunks: List[Dict[str, Any]],
        registry: Optional[Dict[str, Any]] = None,
    ) -> "MemoryGraph":
        """Build the graph from the indexed chunk corpus.

        Chunks of indexed files ARE memories: each section chunk becomes a
        memory node (source="file") grouped under its file node. Entities
        come solely from the registry's ``## Entities`` list. Connections
        are then established here — and only here — by the deterministic
        matcher (:meth:`_establish_connections`); the ``## Connections``
        records supply each matched name's mark (confirmed / rejected /
        pending).

        Args:
            chunks: dicts with ``chunk_id``, ``document`` and ``metadata``
                (the full ChromaDB collection contents).
            registry: parse_entity_registry() output. Records for chunk ids
                no longer in the corpus are ignored (and dropped by the
                next connection-record sync).
        """
        graph = cls()
        registry = registry or {}
        graph._records = registry.get("connections", {})

        # Entities exist ONLY from the ## Entities list — including ones
        # nothing connects to yet.
        for name in registry.get("entities", []):
            graph._ensure_entity(name)

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
                graph._add_file_memory_chunk(
                    chunk.get("chunk_id", ""),
                    chunk.get("document", ""),
                    meta,
                )

        # THE single connection-establishment pass, then hub exclusion over
        # the complete link set (pending + confirmed).
        graph._establish_connections()
        graph._prune_hub_entities()
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

        item = _ItemNode(
            item_id=chunk_id,
            timestamp=meta.get("timestamp", ""),
            category=meta.get("category", "fact"),
            content=content,
            # Reviewed iff the connection record for this chunk id says
            # [judged] — the entity-indexer has decided every mark on it.
            reviewed=(self._records.get(chunk_id) or {}).get("status") == "judged",
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

    def _add_file_memory_chunk(
        self,
        chunk_id: str,
        document: str,
        meta: Dict[str, Any],
    ) -> None:
        """A section chunk of an indexed file — a memory sourced from a file.

        Creates the chunk's memory node linked under its file node. Its
        connection marks come from the chunk id's ## Connections record,
        exactly like MEMORY.md items — chunk ids are content-derived, so a
        changed section is a new id with no record: automatically pending.
        The node carries the chunk's FULL text (the summary is a truncated
        derivative — showing it in detail views reads as the memory being
        cut off, which it is not).
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
            reviewed=(self._records.get(chunk_id) or {}).get("status") == "judged",
            source="file",
            file_path=file_path,
            section=section,
        )
        self.items[chunk_id] = item
        self._link(f"f:{file_path}", f"i:{chunk_id}")

    def _prune_hub_entities(self) -> None:
        """Exclude over-connected entities from the derived graph.

        An entity connected (pending or confirmed) to more than
        ENTITY_HUB_FRACTION of all memories (past the ENTITY_HUB_MIN_LINKS
        floor) is ambient context: a link that attaches to almost
        everything carries no information, floods the graph retrieval
        channel, and collapses communities into one blob. The entity list
        and verdict records stay untouched — exclusion is recomputed on
        every build, so a hub drops out while it is over the threshold and
        returns automatically (links intact) when the corpus shifts below
        it.
        """
        total = len(self.items)
        if total == 0:
            return
        limit = max(ENTITY_HUB_MIN_LINKS, ENTITY_HUB_FRACTION * total)
        hub_keys = [
            key
            for key, entity in self.entities.items()
            if len(entity.item_ids | entity.pending_item_ids) > limit
        ]
        for key in hub_keys:
            entity = self.entities.pop(key)
            entity_node = f"e:{key}"
            for item_id in entity.item_ids | entity.pending_item_ids:
                item = self.items.get(item_id)
                if item is not None:
                    if key in item.entities:
                        item.entities.remove(key)
                    if key in item.pending_entities:
                        item.pending_entities.remove(key)
                self._adjacency.get(f"i:{item_id}", set()).discard(entity_node)
            for file_path in entity.file_paths:
                file_node = self.files.get(file_path)
                if file_node is not None:
                    file_node.entities.discard(key)
            self._adjacency.pop(entity_node, None)

    def _establish_connections(self) -> None:
        """THE single place memory↔entity connections are made.

        For every memory, the deterministic matcher connects it to each
        known entity (the ``## Entities`` list) whose whole normalised name
        appears in the memory's text. The chunk id's ## Connections record
        then sets each matched name's state by its mark:
        - confirmed mark (plain name) → CONFIRMED edge;
        - rejected mark (``!``) → no edge (kept for the record sync);
        - ``?`` mark, unmarked, or no record → PENDING edge.
        A mark on a name the matcher did not establish does nothing — the
        entity-indexer structurally cannot introduce a connection.
        """
        if not self.entities:
            return

        # Precompute " normalised name " needles once, in deterministic order.
        needles: List[Tuple[str, str]] = []
        for key in sorted(self.entities):
            norm = re.sub(r"[^a-z0-9]+", " ", key).strip()
            if norm:
                needles.append((f" {norm} ", key))
        if not needles:
            return

        for item in self.items.values():
            record = self._records.get(item.item_id) or {}
            confirmed = {n.lower() for n in record.get("confirmed", [])}
            rejected = {n.lower() for n in record.get("rejected", [])}
            haystack = f" {re.sub(r'[^a-z0-9]+', ' ', item.content.lower())} "
            for needle, key in needles:
                if needle not in haystack:
                    continue
                entity = self.entities[key]
                if key in confirmed:
                    item.entities.append(key)
                    entity.item_ids.add(item.item_id)
                    if item.source == "file" and item.file_path:
                        entity.file_paths.add(item.file_path)
                        file_node = self.files.get(item.file_path)
                        if file_node is not None:
                            file_node.entities.add(key)
                    self._link(f"i:{item.item_id}", f"e:{key}")
                elif key in rejected:
                    item.rejected_entities.append(key)
                else:
                    # Superseded memories keep their judged history but
                    # never accrue new provisional links.
                    if item.superseded:
                        continue
                    item.pending_entities.append(key)
                    entity.pending_item_ids.add(item.item_id)
                    self._link(f"i:{item.item_id}", f"e:{key}")

    def connection_lines(self) -> List[str]:
        """Render the ## Connections record lines for this build.

        One line per memory that has any established (or previously judged)
        connection state, sorted by chunk id for a deterministic file. Marks
        carry each matched name's state: plain = confirmed, ``!`` =
        rejected, ``?`` = pending. Chunk ids no longer in the graph simply
        aren't rendered — that IS the record cleanup. Superseded memories
        render only their judged marks (never ``?``), and a memory with no
        connection state at all still gets a ``[pending]`` line so the
        entity-indexer reviews its text once for new entities.
        """
        lines: List[str] = []
        for item_id in sorted(self.items):
            item = self.items[item_id]
            parts: List[str] = []
            for key in sorted(item.entities):
                entity = self.entities.get(key)
                if entity is not None:
                    parts.append(entity.name)
            for key in sorted(item.rejected_entities):
                entity = self.entities.get(key)
                if entity is not None:
                    parts.append(f"!{entity.name}")
            for key in sorted(item.pending_entities):
                entity = self.entities.get(key)
                if entity is not None:
                    parts.append(f"?{entity.name}")
            if item.superseded and not parts:
                continue
            status = (
                "judged"
                if item.reviewed and not item.pending_entities
                else "pending"
            )
            if item.superseded:
                status = "judged"
            preview = " ".join((item.content or "").split())
            if len(preview) > CONNECTION_PREVIEW_MAX_CHARS:
                preview = preview[: CONNECTION_PREVIEW_MAX_CHARS - 3] + "..."
            names = f" {', '.join(parts)}" if parts else ""
            lines.append(
                f"[{item_id}] [{status}]{names}"
                f"{_CONNECTION_TEXT_SEPARATOR}{preview}"
            )
        return lines

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
