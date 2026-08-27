# -*- coding: utf-8 -*-
"""Every tuning number of the memory system, in one typed place.

Retrieval weights, thresholds, seed caps, chunking sizes, processing
defaults, and scan bounds all live here — no other memory-system module
defines a numeric behavior constant. Change a value here and every
consumer (manager, graph, BM25, injector, settings, adapter) follows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


# ───────────────────────── Hybrid retrieval ─────────────────────────

@dataclass(frozen=True)
class HybridWeights:
    """Channel weights of the hybrid score. Vector is the primary signal,
    BM25 backstops proper nouns and dates, the graph channel boosts items
    connected to entities mentioned in the query (including 2-hop
    neighbours the other channels can miss entirely)."""

    vector: float
    bm25: float
    graph: float


HYBRID_WEIGHTS: Final[HybridWeights] = HybridWeights(
    vector=0.55,
    bm25=0.30,
    graph=0.15,
)

# Default result count and relevance floor of MemoryManager.retrieve().
RETRIEVE_TOP_K: Final[int] = 5
RETRIEVE_MIN_RELEVANCE: Final[float] = 0.55

# Per-channel candidate net cast before the hybrid re-rank:
# max(top_k * multiplier, floor).
CANDIDATE_POOL_MULTIPLIER: Final[int] = 4
CANDIDATE_POOL_FLOOR: Final[int] = 20

# A strongly graph-connected item is eligible even when its combined score
# sits below min_relevance — this is what lets 2-hop related memories
# surface despite sharing no words with the query.
GRAPH_ELIGIBILITY_SCORE: Final[float] = 0.5

# Recency bonus: newest items get up to +RECENCY_MAX_BONUS, halving every
# RECENCY_HALF_LIFE_DAYS. Small on purpose — recency is a tiebreaker, not
# a ranking signal of its own.
RECENCY_MAX_BONUS: Final[float] = 0.05
RECENCY_HALF_LIFE_DAYS: Final[float] = 30.0

# Default result count of BM25Index.search().
BM25_SEARCH_TOP_K: Final[int] = 20


# ───────────────────────── Graph channel seeds ─────────────────────────

# Strength assigned to every string-matched entity seed (exact phrase and
# all-tokens-present alike).
ENTITY_SEED_STRENGTH: Final[float] = 1.0

# Minimum cosine similarity for the SEMANTIC entity match (graph channel).
# The query is embedded and compared against each entity's name embedding;
# below this a match is treated as noise. This is what resolves partial names
# ("Tobias" → "Tobias Garcia") without hand-rolled token rules. The string
# matcher still catches exact / all-token hits at full strength regardless.
ENTITY_MATCH_MIN_SCORE: Final[float] = 0.6

# Seed caps: string-matched seeds, semantic seeds, and the union of both.
STRING_SEEDS_MAX: Final[int] = 5
SEMANTIC_SEEDS_MAX: Final[int] = 5
MERGED_SEEDS_MAX: Final[int] = 8

# Hub-entity exclusion: an entity confirmed on more than this fraction of
# all memories is ambient context, not information — it is left out of the
# derived graph entirely (no node, no links, no retrieval seeding). The
# annotations themselves are never touched, so exclusion is recomputed on
# every build and reverses itself when the corpus shifts. The absolute
# floor keeps small corpora intact (with 20 memories, 25% would be 5
# links — normal for any legitimate entity).
ENTITY_HUB_FRACTION: Final[float] = 0.25
ENTITY_HUB_MIN_LINKS: Final[int] = 10

# BFS scoring: items directly attached to a seed entity score full seed
# strength; items reached through one intermediate entity decay by this.
SECOND_HOP_DECAY: Final[float] = 0.45

# Community detection rounds. The graph is small (hundreds of nodes); label
# propagation converges in a handful of rounds.
LABEL_PROPAGATION_ROUNDS: Final[int] = 10


# ───────────────────────────── Chunking ─────────────────────────────

# Max characters per chunk before splitting, and the character overlap
# carried between chunks when a large section is split.
CHUNK_SIZE_LIMIT: Final[int] = 1500
CHUNK_OVERLAP: Final[int] = 100


# ──────────────────────── Previews and logging ────────────────────────

# Query-aware preview window. The injected memory preview is centred on the
# query match instead of the chunk's head, so the fact that made the chunk
# relevant is not truncated away (a from-the-start summary once cut off
# "Tobias Garcia" and the agent had to grep for it). PREVIEW_MAX_CHARS bounds
# the snippet; PREVIEW_LEAD keeps a little context before the match.
PREVIEW_MAX_CHARS: Final[int] = 180
PREVIEW_LEAD: Final[int] = 40

# Log-line preview limits. Keep multi-line queries and long summaries from
# bleeding across log entries.
LOG_QUERY_MAX_CHARS: Final[int] = 300
LOG_SUMMARY_MAX_CHARS: Final[int] = 120

# Text preview appended to each ## Connections record line in ENTITIES.md —
# display-only context for the Memory panel and logs.
CONNECTION_PREVIEW_MAX_CHARS: Final[int] = 160


# ──────────────────────── Entity-judge pipeline ────────────────────────

# Evidence cap per record handed to the judge LLM call — the chunk's FULL
# text truncated here (much richer than the 160-char record preview).
ENTITY_JUDGE_TEXT_CAP: Final[int] = 800

# Records per judge call, bounded both by count and by summed evidence
# characters so file-section-heavy batches don't balloon a single call.
ENTITY_JUDGE_BATCH_MAX_RECORDS: Final[int] = 80
ENTITY_JUDGE_BATCH_MAX_CHARS: Final[int] = 40_000

# Convergence bound: new entities created in one pass attach as fresh "?"
# candidates on the next graph rebuild and need one more judging pass.
# Two passes settle the common case; the third catches entities minted
# during pass two. Anything left after that waits for the next run.
ENTITY_JUDGE_MAX_PASSES: Final[int] = 3

# Re-asks after a schema-invalid LLM response (validation error appended).
ENTITY_JUDGE_MAX_REASKS: Final[int] = 2


# ──────────────────────── Trigger-driven injection ────────────────────────

# Relevance floor and max preview count for memories auto-injected into the
# event stream on message arrival / task creation.
INJECT_MIN_RELEVANCE: Final[float] = 0.5
INJECT_TOP_K: Final[int] = 5


# ──────────────────────── Processing and pruning ────────────────────────

# Unprocessed-event count that fires processing immediately (threshold-
# driven) and gates the daily scheduled run; 0 disables the gate. MAX is
# the upper bound the settings slider allows.
PROCESSING_THRESHOLD_DEFAULT: Final[int] = 25
PROCESSING_THRESHOLD_MAX: Final[int] = 100

# MEMORY.md size management: item cap that triggers pruning, the count
# pruning shrinks down to, and the per-item word limit.
MEMORY_MAX_ITEMS_DEFAULT: Final[int] = 200
MEMORY_PRUNE_TARGET_DEFAULT: Final[int] = 135
MEMORY_ITEM_WORD_LIMIT_DEFAULT: Final[int] = 150

# Default daily auto-processing time (24h clock).
SCHEDULE_HOUR_DEFAULT: Final[int] = 3
SCHEDULE_MINUTE_DEFAULT: Final[int] = 0


# ──────────────────────── Indexed-file candidate scan ────────────────────────

# Bounds of the workspace scan that offers files in the index picker —
# keeps the picker responsive on large workspaces.
CANDIDATE_MAX_DEPTH: Final[int] = 10
CANDIDATE_MAX_RESULTS: Final[int] = 500
