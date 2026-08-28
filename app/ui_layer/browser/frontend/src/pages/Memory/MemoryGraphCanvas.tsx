import { useEffect, useRef } from 'react'
import type { MemoryGraph, MemoryGraphNode } from '../../store/slices/memorySettingsSlice'

// Community palette — full-spectrum, ordered for MAX adjacent contrast, and
// tuned to the brand's intensity. Colour groups are numbered 0,1,2,… so the
// colours that must differ are CONSECUTIVE entries; stepping ~137.5° (the
// golden angle) around the hue wheel puts every next colour on the far side
// of the wheel, so no two consecutive groups look alike. Every colour is
// pushed to roughly the saturation/lightness of the brand orange #FF4F18
// (~S100 / L55), so they read as equal-energy siblings of the logo rather
// than a mix of vivid and washed-out. Reads on both #191919 and #FFFFFF.
const COMMUNITY_COLORS = [
  '#FF3B3B', // red
  '#16D65C', // green
  '#A64BFF', // violet
  '#FFC21A', // gold
  '#12C9E0', // cyan
  '#FF3D9E', // magenta-pink
  '#93E01A', // lime
  '#3D6BFF', // indigo-blue
  '#FF7A1A', // orange
  '#0DCBB6', // teal
  '#B84DFF', // purple
  '#FFDE1A', // yellow
]

// ── Physics tuning ──────────────────────────────────────────────────────
// d3-style cooling: alpha decays toward ZERO and the simulation performs a
// hard stop (velocities zeroed) once it crosses ALPHA_MIN. There is no
// simmering floor — a floor keeps injecting force every frame and the
// layout jitters forever at the spring/repulsion equilibrium.
const FRICTION = 0.8
const REPULSION = 2400
const REPULSION_CUTOFF = 320
// A node's repulsion scales with how connected it is: a well-connected hub
// pushes other nodes away harder, so its dense cloud of memories spreads out
// instead of piling on top of neighbouring hubs. Sub-linear (log of degree)
// so a 60-link hub is strongly repulsive without detonating the layout;
// degree-1 leaves keep the base repulsion (multiplier 1).
const HUB_REPULSION = 2.0
// Extra clearance every pair of nodes keeps beyond their radii.
const NODE_CLEARANCE = 22
// Hard no-overlap guarantee: pairs closer than radii + this gap are
// separated by direct position correction (not forces), so overlap cannot
// survive — not even in the frozen settled state.
const COLLIDE_GAP = 3
const SPRING = 0.04
const CENTER_GRAVITY = 0.01
const CLUSTER_GRAVITY = 0.015
const MAX_SPEED = 14
const ALPHA_DECAY = 0.96
const ALPHA_MIN = 0.004
// Early stop: once cool-ish and essentially still, freeze immediately —
// waiting out the full decay leaves seconds of visible micro-drift.
const REST_ALPHA = 0.08
const REST_SPEED = 0.06
const ENTRANCE_MS = 550
const BREATHE_RAMP_MS = 1500
const FOLLOW_LERP = 0.08

// ── Radial fan-out for file chunks ──────────────────────────────────────
// A file's chunks fan out around it in ALL directions as a radial tree
// (reference: a center with branches radiating outward). Branch structure
// comes from the section hierarchy ("# A > ## B > ### C"): top-level
// sections sit on the inner ring, subsections chain outward, leaves reach
// the rim. Each branch owns its angular wedge, allocated by leaf count so
// branches never cross. Nothing is pinned: every chunk is simulated and
// pulled toward its radial slot by spring forces — fully elastic. Lines
// are straight parent→child segments along each branch.
const RADIAL_INNER = 72       // first ring's distance from the file
const RADIAL_RING_GAP = 58    // distance between depth rings
const RADIAL_PULL = 0.09      // spring strength toward the radial slot
// Minimum arc distance between neighbouring leaves on a fan's rim. Trees
// with more leaves than their natural rim can hold scale their rings up
// so slots never force chunks into each other.
const MIN_LEAF_SPACING = 13

interface SimNode {
  data: MemoryGraphNode
  x: number
  y: number
  vx: number
  vy: number
  radius: number
  color: string
  // Repulsion multiplier from this node's edge degree — hubs shove harder.
  repel: number
  // Celestial rendering: precomputed "r,g,b" strings so the per-frame
  // rgba() concatenation stays allocation-cheap.
  starHalo: string // desaturated community tint for the outer glow
  starCore: string // near-white core with a hint of the tint (dark theme)
  starInk: string  // near-black core variant for light theme (ink chart)
  birth: number
  phase: number // idle-breathing + twinkle phase (render-only)
}

interface TreeMember {
  node: SimNode
  // Radial slot as a fixed offset from the file's position.
  ox: number
  oy: number
}

interface TreeLink {
  a: SimNode // parent (file or another chunk)
  b: SimNode // child chunk
}

interface RadialTree {
  center: SimNode
  members: TreeMember[]
  links: TreeLink[]
}

interface SimEdge {
  a: SimNode
  b: SimNode
  rest: number
  // Flat file ↔ own-chunk edges: superseded by the radial-tree forces and
  // the branch links, so both the spring pass and the edge renderer skip
  // them.
  rib: boolean
}

interface MemoryGraphCanvasProps {
  graph: MemoryGraph | null
  selectedId: string | null
  onSelect: (node: MemoryGraphNode | null) => void
  /** Increment to trigger a zoom-to-fit. */
  fitNonce?: number
  /** Increment to force a re-layout (reheat + camera follow), even when
   * the refetched graph is topologically identical. */
  refreshNonce?: number
  /** Render-only link visibility. Memory↔entity lines and memory↔file
   * (radial branch) lines toggle independently; positions are unaffected. */
  showEntityLinks?: boolean
  showFileLinks?: boolean
}

function nodeRadius(node: MemoryGraphNode): number {
  if (node.kind === 'entity') {
    // Slightly bigger than a memory dot, growing slowly (log-scaled) with
    // connections: 1 mention ≈ 5.4, 10 ≈ 7.7, 100 ≈ 10 (hard cap).
    return 5.4 + Math.min(4.6, Math.log2((node.size || 1) + 1) * 1.4)
  }
  if (node.kind === 'file') return 7.5
  return 4.6
}

function nodeColor(node: MemoryGraphNode): string {
  return COMMUNITY_COLORS[(node.community ?? 0) % COMMUNITY_COLORS.length]
}

/** Mix a hex colour toward a target channel value by t∈[0,1] → "r,g,b". */
function mixChannels(hex: string, target: number, t: number): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  const mix = (c: number) => Math.round(c + (target - c) * t)
  return `${mix(r)},${mix(g)},${mix(b)}`
}

/** Star colour set for a community colour: subtle tint, not flat paint. */
function starColors(hex: string): { halo: string; core: string; ink: string } {
  return {
    halo: mixChannels(hex, 255, 0.35), // gently desaturated glow
    core: mixChannels(hex, 255, 0.82), // near-white, a whisper of hue
    ink: mixChannels(hex, 24, 0.6),    // near-black for light theme
  }
}

interface SkySpeck {
  x: number
  y: number
  r: number
  a: number
  phase: number
}

/** Resolve a CSS variable on the canvas element (theme-aware colors). */
function cssVar(el: HTMLElement, name: string, fallback: string): string {
  const value = getComputedStyle(el).getPropertyValue(name).trim()
  return value || fallback
}

/** Cheap topology signature — reheating is skipped when it is unchanged. */
function graphSignature(graph: MemoryGraph | null): string {
  if (!graph) return ''
  let sig = `${graph.nodes.length}:${graph.edges.length}`
  for (const n of graph.nodes) sig += `|${n.id}`
  return sig
}

/**
 * Force-directed memory graph on a raw canvas.
 *
 * All simulation state lives in refs and one rAF loop — React renders the
 * element once. When `graph` changes, existing nodes keep their positions;
 * new nodes spawn next to an already-placed neighbour (or on their
 * community's ring) and ease in. A refetch with identical topology does
 * NOT reheat the layout, so panel actions don't shake the graph. While the
 * initial layout settles, the camera smoothly follows a zoom-to-fit frame
 * until the user takes over (pan/zoom/drag). After settling the physics
 * pass stops dead — only a gentle render-side breathing remains.
 */
export function MemoryGraphCanvas({ graph, selectedId, onSelect, fitNonce = 0, refreshNonce = 0, showEntityLinks = true, showFileLinks = true }: MemoryGraphCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const nodesRef = useRef<Map<string, SimNode>>(new Map())
  const treesRef = useRef<RadialTree[]>([])
  const specksRef = useRef<SkySpeck[]>([])
  const edgesRef = useRef<SimEdge[]>([])
  const alphaRef = useRef(1)
  const settledAtRef = useRef<number | null>(null)
  const signatureRef = useRef('')
  const transformRef = useRef({ x: 0, y: 0, k: 1 })
  const followRef = useRef(false)
  const fitRequestRef = useRef(false)
  const lastFitNonce = useRef(fitNonce)
  const hoverRef = useRef<SimNode | null>(null)
  const selectedRef = useRef<string | null>(null)
  const dragRef = useRef<{ node: SimNode | null; panning: boolean; lastX: number; lastY: number; moved: boolean }>({
    node: null, panning: false, lastX: 0, lastY: 0, moved: false,
  })
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect

  // Link-visibility flags read inside the rAF loop (which closes over refs,
  // not props), so live toggles take effect without restarting the loop.
  const showEntityLinksRef = useRef(showEntityLinks)
  showEntityLinksRef.current = showEntityLinks
  const showFileLinksRef = useRef(showFileLinks)
  showFileLinksRef.current = showFileLinks

  selectedRef.current = selectedId

  if (fitNonce !== lastFitNonce.current) {
    lastFitNonce.current = fitNonce
    fitRequestRef.current = true
  }

  // Manual refresh: the user explicitly asked for a re-layout, so bypass
  // the identical-topology guard — reheat and let the camera follow.
  const lastRefreshNonce = useRef(refreshNonce)
  if (refreshNonce !== lastRefreshNonce.current) {
    lastRefreshNonce.current = refreshNonce
    alphaRef.current = 1
    settledAtRef.current = null
    followRef.current = true
  }

  // ── Graph → simulation sync ────────────────────────────────────────────
  useEffect(() => {
    const nodes = nodesRef.current
    const now = performance.now()
    const incoming = new Set<string>()

    const canvas = canvasRef.current
    const width = canvas?.clientWidth || 800
    const height = canvas?.clientHeight || 600
    const cx = width / 2
    const cy = height / 2

    // Degree = how connected each node is; drives the hub-repulsion boost.
    const degreeOf = new Map<string, number>()
    for (const e of graph?.edges || []) {
      degreeOf.set(e.source, (degreeOf.get(e.source) || 0) + 1)
      degreeOf.set(e.target, (degreeOf.get(e.target) || 0) + 1)
    }
    const repelOf = (id: string) =>
      1 + HUB_REPULSION * Math.log2(Math.max(1, degreeOf.get(id) || 1))

    const fresh: MemoryGraphNode[] = []
    for (const data of graph?.nodes || []) {
      incoming.add(data.id)
      const existing = nodes.get(data.id)
      if (existing) {
        existing.data = data
        existing.radius = nodeRadius(data)
        existing.repel = repelOf(data.id)
        existing.color = nodeColor(data)
        const star = starColors(existing.color)
        existing.starHalo = star.halo
        existing.starCore = star.core
        existing.starInk = star.ink
      } else {
        fresh.push(data)
      }
    }
    for (const id of Array.from(nodes.keys())) {
      if (!incoming.has(id)) nodes.delete(id)
    }

    // Adjacency of the incoming graph, used to seed new nodes next to an
    // already-placed neighbour so clusters assemble instead of untangling.
    const adjacency = new Map<string, string[]>()
    for (const e of graph?.edges || []) {
      let a = adjacency.get(e.source)
      if (!a) adjacency.set(e.source, a = [])
      a.push(e.target)
      let b = adjacency.get(e.target)
      if (!b) adjacency.set(e.target, b = [])
      b.push(e.source)
    }

    // Entities first (items/files then attach next to them). Each community
    // gets its own angular sector on a ring, so clusters start separated.
    fresh.sort((a, b) => (a.kind === 'entity' ? 0 : 1) - (b.kind === 'entity' ? 0 : 1))
    const ringRadius = Math.min(width, height) * 0.28
    for (const data of fresh) {
      let x: number | undefined
      let y: number | undefined
      for (const nb of adjacency.get(data.id) || []) {
        const placed = nodes.get(nb)
        if (placed) {
          x = placed.x + (Math.random() - 0.5) * 26
          y = placed.y + (Math.random() - 0.5) * 26
          break
        }
      }
      if (x === undefined || y === undefined) {
        const angle = ((data.community ?? 0) * 2.399963) + (Math.random() - 0.5) * 0.8
        const dist = ringRadius * (0.55 + Math.random() * 0.65)
        x = cx + Math.cos(angle) * dist
        y = cy + Math.sin(angle) * dist
      }
      const color = nodeColor(data)
      const star = starColors(color)
      nodes.set(data.id, {
        data,
        x, y,
        vx: 0, vy: 0,
        radius: nodeRadius(data),
        repel: repelOf(data.id),
        color,
        starHalo: star.halo,
        starCore: star.core,
        starInk: star.ink,
        birth: now,
        phase: Math.random() * Math.PI * 2,
      })
    }

    // ── Build radial trees: each file's chunks fan out around it ──
    // Branch structure from the section hierarchy; angular wedges are
    // allocated by leaf count (classic radial tidy-tree), so every branch
    // owns a slice and branches never cross.
    const trees: RadialTree[] = []
    const memberIds = new Set<string>()
    // Any item that names its file joins that file's fan — file chunks AND
    // conversation memories (MEMORY.md behaves like every other file).
    const chunksByFile = new Map<string, SimNode[]>()
    for (const data of graph?.nodes || []) {
      if (data.kind === 'item' && data.file) {
        const sim = nodes.get(data.id)
        if (!sim) continue
        let list = chunksByFile.get(data.file)
        if (!list) chunksByFile.set(data.file, list = [])
        list.push(sim)
      }
    }

    const stripPart = (s: string) => s.replace(/ \(part \d+\)$/, '')
    const partNum = (s: string) => {
      const m = s.match(/ \(part (\d+)\)$/)
      return m ? parseInt(m[1], 10) : 1
    }

    for (const data of graph?.nodes || []) {
      if (data.kind !== 'file') continue
      const center = nodes.get(data.id)
      if (!center) continue
      const chunkList = chunksByFile.get(data.label) || []
      if (chunkList.length === 0) continue

      // Group split sections ("(part n)") under one base path; parts chain
      // outward so long sections become a branch, not siblings. Items
      // without a section (conversation memories) get a unique base so
      // they become independent leaves off the file, never a chain.
      const bySection = new Map<string, SimNode[]>()
      for (const chunk of chunkList) {
        const base = stripPart(chunk.data.section || '') || `#${chunk.data.id}`
        let list = bySection.get(base)
        if (!list) bySection.set(base, list = [])
        list.push(chunk)
      }
      for (const list of bySection.values()) {
        list.sort((a, b) => partNum(a.data.section || '') - partNum(b.data.section || ''))
      }

      // Parent resolution: part n hangs off part n-1; a section's first
      // part hangs off its nearest ancestor section that has a chunk, or
      // the file itself.
      const parentOf = new Map<SimNode, SimNode | null>()
      for (const [base, parts] of bySection) {
        for (let i = 1; i < parts.length; i++) parentOf.set(parts[i], parts[i - 1])
        const segs = base.split(' > ')
        let parent: SimNode | null = null
        for (let cut = segs.length - 1; cut >= 1; cut--) {
          const ancestor = bySection.get(segs.slice(0, cut).join(' > '))
          if (ancestor && ancestor.length > 0) { parent = ancestor[0]; break }
        }
        parentOf.set(parts[0], parent)
      }

      // Children lists (null key = the file root), stable order.
      const children = new Map<SimNode | null, SimNode[]>()
      for (const chunk of chunkList) {
        const parent = parentOf.get(chunk) ?? null
        let list = children.get(parent)
        if (!list) children.set(parent, list = [])
        list.push(chunk)
      }
      for (const list of children.values()) {
        list.sort((a, b) => (a.data.section || '').localeCompare(b.data.section || ''))
      }

      // Radial tidy-tree: DFS assigns each leaf a sequential angular slot;
      // an inner node sits at the mean angle of its subtree. Depth maps to
      // ring radius.
      let leafTotal = 0
      const countLeaves = (parent: SimNode | null): number => {
        const kids = children.get(parent) || []
        if (kids.length === 0) return 1
        let sum = 0
        for (const k of kids) sum += countLeaves(k)
        return sum
      }
      for (const k of children.get(null) || []) leafTotal += countLeaves(k)
      if (leafTotal === 0) continue

      const members: TreeMember[] = []
      const links: TreeLink[] = []
      let slot = 0
      let maxDepth = 1
      const layout = (chunk: SimNode, parent: SimNode | null, depth: number): number => {
        if (depth > maxDepth) maxDepth = depth
        const kids = children.get(chunk) || []
        let angle: number
        if (kids.length === 0) {
          angle = ((slot + 0.5) / leafTotal) * Math.PI * 2
          slot += 1
        } else {
          let sum = 0
          for (const k of kids) sum += layout(k, chunk, depth + 1)
          angle = sum / kids.length
        }
        const r = RADIAL_INNER + (depth - 1) * RADIAL_RING_GAP
        members.push({ node: chunk, ox: Math.cos(angle) * r, oy: Math.sin(angle) * r })
        links.push({ a: parent ?? center, b: chunk })
        memberIds.add(chunk.data.id)
        return angle
      }
      for (const k of children.get(null) || []) layout(k, null, 1)

      // Leafy trees widen: if the rim can't give every leaf its minimum
      // arc spacing, scale all rings up proportionally so slots never
      // force chunks into each other.
      const naturalRim = RADIAL_INNER + (maxDepth - 1) * RADIAL_RING_GAP
      const requiredRim = (leafTotal * MIN_LEAF_SPACING) / (Math.PI * 2)
      const scale = Math.max(1, requiredRim / naturalRim)
      if (scale > 1) {
        for (const m of members) {
          m.ox *= scale
          m.oy *= scale
        }
      }

      trees.push({ center, members, links })
    }
    treesRef.current = trees

    edgesRef.current = (graph?.edges || [])
      .map(e => {
        const a = nodes.get(e.source)
        const b = nodes.get(e.target)
        if (!a || !b) return null
        const rib =
          (a.data.kind === 'file' && memberIds.has(b.data.id) && b.data.file === a.data.label) ||
          (b.data.kind === 'file' && memberIds.has(a.data.id) && a.data.file === b.data.label)
        const rest = a.data.kind === 'file' || b.data.kind === 'file' ? 115 : 70
        return { a, b, rest, rib }
      })
      .filter((e): e is SimEdge => e !== null)

    // Reheat ONLY when the topology actually changed. Refetches after panel
    // actions (edit, process, refresh) usually return the identical graph —
    // shaking the layout for those reads as instability.
    const signature = graphSignature(graph)
    if (signature !== signatureRef.current) {
      signatureRef.current = signature
      alphaRef.current = 1
      settledAtRef.current = null
      if ((graph?.nodes?.length ?? 0) > 0) followRef.current = true

      // Background starfield: tiny static specks scattered across (and a
      // little beyond) the content area, so panning feels like drifting
      // through space. Regenerated only on topology change.
      const all = Array.from(nodes.values())
      if (all.length > 0) {
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
        for (const n of all) {
          minX = Math.min(minX, n.x); maxX = Math.max(maxX, n.x)
          minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y)
        }
        const padX = (maxX - minX) * 0.5 + 300
        const padY = (maxY - minY) * 0.5 + 300
        const specks: SkySpeck[] = []
        for (let i = 0; i < 220; i++) {
          specks.push({
            x: minX - padX + Math.random() * (maxX - minX + padX * 2),
            y: minY - padY + Math.random() * (maxY - minY + padY * 2),
            r: 0.4 + Math.random() * 0.8,
            a: 0.06 + Math.random() * 0.22,
            phase: Math.random() * Math.PI * 2,
          })
        }
        specksRef.current = specks
      } else {
        specksRef.current = []
      }
    }
  }, [graph])

  // ── Simulation + render loop ───────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let raf = 0
    let disposed = false

    const resize = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1)
      const { clientWidth, clientHeight } = canvas
      if (canvas.width !== clientWidth * dpr || canvas.height !== clientHeight * dpr) {
        canvas.width = clientWidth * dpr
        canvas.height = clientHeight * dpr
      }
    }
    const ro = new ResizeObserver(resize)
    ro.observe(canvas)
    resize()

    // Transform that frames all nodes with padding, or null when empty.
    const fitTransform = (): { x: number; y: number; k: number } | null => {
      const nodes = Array.from(nodesRef.current.values())
      if (nodes.length === 0) return null
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
      for (const n of nodes) {
        minX = Math.min(minX, n.x - n.radius)
        minY = Math.min(minY, n.y - n.radius)
        maxX = Math.max(maxX, n.x + n.radius)
        maxY = Math.max(maxY, n.y + n.radius)
      }
      const width = canvas.clientWidth
      const height = canvas.clientHeight
      const pad = 56
      const spanX = Math.max(60, maxX - minX)
      const spanY = Math.max(60, maxY - minY)
      const k = Math.min(1.5, Math.max(0.3,
        Math.min((width - pad * 2) / spanX, (height - pad * 2) / spanY)))
      return {
        k,
        x: width / 2 - ((minX + maxX) / 2) * k,
        y: height / 2 - ((minY + maxY) / 2) * k,
      }
    }

    // Spatial-hash repulsion: nodes only interact within their 3×3 cell
    // neighbourhood (cell size = cutoff), keeping the pass near-linear.
    // The close-range boost is a CONTINUOUS ramp — a stepped multiplier
    // makes nodes at the threshold flip between force regimes every frame
    // and oscillate visibly.
    const applyRepulsion = (nodes: SimNode[], alpha: number) => {
      const cell = REPULSION_CUTOFF
      const grid = new Map<number, SimNode[]>()
      const hash = (gx: number, gy: number) => (gx * 73856093) ^ (gy * 19349663)
      for (const n of nodes) {
        const key = hash(Math.floor(n.x / cell), Math.floor(n.y / cell))
        let bucket = grid.get(key)
        if (!bucket) grid.set(key, bucket = [])
        bucket.push(n)
      }
      const cutoff2 = REPULSION_CUTOFF * REPULSION_CUTOFF
      for (const n1 of nodes) {
        const gx0 = Math.floor(n1.x / cell)
        const gy0 = Math.floor(n1.y / cell)
        for (let gx = gx0 - 1; gx <= gx0 + 1; gx++) {
          for (let gy = gy0 - 1; gy <= gy0 + 1; gy++) {
            const bucket = grid.get(hash(gx, gy))
            if (!bucket) continue
            for (const n2 of bucket) {
              if (n2 === n1) continue
              let dx = n1.x - n2.x
              let dy = n1.y - n2.y
              let d2 = dx * dx + dy * dy
              if (d2 > cutoff2) continue
              if (d2 < 1) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 1 }
              const d = Math.sqrt(d2)
              const sizeBoost = 1 + (n1.radius + n2.radius) * 0.04
              const minDist = n1.radius + n2.radius + NODE_CLEARANCE
              const overlapRamp = d < minDist ? 1 + 2 * (minDist - d) / minDist : 1
              // n2 repels n1; scale by n2's connectedness so hubs shove hardest.
              const force = (REPULSION * sizeBoost * overlapRamp * n2.repel / d2) * alpha
              n1.vx += (dx / d) * force
              n1.vy += (dy / d) * force
            }
          }
        }
      }
    }

    // Position-based collision resolution (the game way): overlapping
    // pairs are separated directly, half the overlap each, iterated a few
    // times over a spatial grid. Because it edits positions rather than
    // applying forces, it keeps working when the simulation is nearly
    // cold — overlap physically cannot survive into the settled state.
    const collidePass = (nodes: SimNode[], iterations: number) => {
      const cell = 80
      const hash = (gx: number, gy: number) => (gx * 73856093) ^ (gy * 19349663)
      const dragged = () => dragRef.current.node
      for (let it = 0; it < iterations; it++) {
        const grid = new Map<number, SimNode[]>()
        for (const n of nodes) {
          const key = hash(Math.floor(n.x / cell), Math.floor(n.y / cell))
          let bucket = grid.get(key)
          if (!bucket) grid.set(key, bucket = [])
          bucket.push(n)
        }
        for (const n1 of nodes) {
          const gx0 = Math.floor(n1.x / cell)
          const gy0 = Math.floor(n1.y / cell)
          for (let gx = gx0 - 1; gx <= gx0 + 1; gx++) {
            for (let gy = gy0 - 1; gy <= gy0 + 1; gy++) {
              const bucket = grid.get(hash(gx, gy))
              if (!bucket) continue
              for (const n2 of bucket) {
                if (n1.data.id >= n2.data.id) continue // each pair once
                let dx = n2.x - n1.x
                let dy = n2.y - n1.y
                let d2 = dx * dx + dy * dy
                const minDist = n1.radius + n2.radius + COLLIDE_GAP
                if (d2 >= minDist * minDist) continue
                if (d2 < 0.01) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = dx * dx + dy * dy }
                const d = Math.sqrt(d2)
                // Soft positional push (full-strength corrections fight the
                // springs and read as jitter)...
                const push = (minDist - d) * 0.3
                const nx = dx / d
                const ny = dy / d
                const drag = dragged()
                if (n1 !== drag) { n1.x -= nx * push; n1.y -= ny * push }
                if (n2 !== drag) { n2.x += nx * push; n2.y += ny * push }
                // ...plus an INELASTIC contact: cancel the pair's
                // approaching momentum and apply contact friction. Without
                // this, preserved velocity makes touching nodes slide
                // tangentially and orbit each other forever.
                const rvx = n2.vx - n1.vx
                const rvy = n2.vy - n1.vy
                const vn = rvx * nx + rvy * ny
                if (vn < 0) {
                  const half = vn / 2
                  n1.vx += nx * half; n1.vy += ny * half
                  n2.vx -= nx * half; n2.vy -= ny * half
                }
                n1.vx *= 0.7; n1.vy *= 0.7
                n2.vx *= 0.7; n2.vy *= 0.7
              }
            }
          }
        }
      }
    }

    const tickPhysics = (nodes: SimNode[], width: number, height: number, time: number) => {
      const alpha = alphaRef.current
      applyRepulsion(nodes, alpha)

      for (const e of edgesRef.current) {
        // Rib edges (file ↔ its own chunk) are handled by the org-grid
        // forces below.
        if (e.rib) continue
        const dx = e.b.x - e.a.x
        const dy = e.b.y - e.a.y
        const d = Math.sqrt(dx * dx + dy * dy) || 1
        const force = (d - e.rest) * SPRING * alpha
        const fx = (dx / d) * force
        const fy = (dy / d) * force
        e.a.vx += fx; e.a.vy += fy
        e.b.vx -= fx; e.b.vy -= fy
      }

      // Radial-tree forces: every chunk is pulled toward its slot on its
      // depth ring around the file — a spring to a moving target, not a
      // pin, so the whole fan stays elastic (drag a chunk and it snaps
      // back; drag the file and its fan follows with a springy lag).
      for (const tree of treesRef.current) {
        const fx0 = tree.center.x
        const fy0 = tree.center.y
        for (const m of tree.members) {
          const targetX = fx0 + m.ox
          const targetY = fy0 + m.oy
          m.node.vx += (targetX - m.node.x) * RADIAL_PULL * alpha
          m.node.vy += (targetY - m.node.y) * RADIAL_PULL * alpha
          // Equal and opposite reaction on the file keeps the pair honest
          // (dragging a chunk tugs its file a little — elastic, organic).
          tree.center.vx -= (targetX - m.node.x) * RADIAL_PULL * alpha * 0.04
          tree.center.vy -= (targetY - m.node.y) * RADIAL_PULL * alpha * 0.04
        }
      }

      // Community centroids pull members together; the global centre pull
      // keeps disconnected clusters from drifting apart forever.
      const centroids = new Map<number, { x: number; y: number; n: number }>()
      for (const n of nodes) {
        const c = n.data.community ?? 0
        const acc = centroids.get(c)
        if (acc) { acc.x += n.x; acc.y += n.y; acc.n += 1 }
        else centroids.set(c, { x: n.x, y: n.y, n: 1 })
      }
      const cx = width / 2
      const cy = height / 2
      let maxSpeed = 0
      for (const n of nodes) {
        const acc = centroids.get(n.data.community ?? 0)
        if (acc && acc.n > 1) {
          n.vx += (acc.x / acc.n - n.x) * CLUSTER_GRAVITY * alpha
          n.vy += (acc.y / acc.n - n.y) * CLUSTER_GRAVITY * alpha
        }
        n.vx += (cx - n.x) * CENTER_GRAVITY * alpha
        n.vy += (cy - n.y) * CENTER_GRAVITY * alpha

        if (dragRef.current.node === n) { n.vx = 0; n.vy = 0; continue }
        n.vx *= FRICTION
        n.vy *= FRICTION
        const speed = Math.sqrt(n.vx * n.vx + n.vy * n.vy)
        if (speed > MAX_SPEED) {
          n.vx = (n.vx / speed) * MAX_SPEED
          n.vy = (n.vy / speed) * MAX_SPEED
        }
        n.x += n.vx
        n.y += n.vy
        if (speed > maxSpeed) maxSpeed = speed
      }

      // Hard separation every tick — springs can overpower repulsion for
      // heavily shared neighbours, so soft forces alone let big hubs sink
      // into each other.
      collidePass(nodes, 2)

      // Cool toward zero — and freeze EARLY once the layout is basically
      // still; letting the decay run its full tail leaves seconds of
      // visible micro-drift. A final heavier collide pass guarantees the
      // frozen layout is clean; velocities are zeroed so no momentum
      // leaks into the next wake-up.
      alphaRef.current = alpha * ALPHA_DECAY
      const atRest = alphaRef.current < ALPHA_MIN ||
        (alphaRef.current < REST_ALPHA && maxSpeed < REST_SPEED)
      if (atRest) {
        alphaRef.current = 0
        settledAtRef.current = time
        collidePass(nodes, 5)
        for (const n of nodes) { n.vx = 0; n.vy = 0 }
      }
    }

    const step = (time: number) => {
      if (disposed) return
      const nodes = Array.from(nodesRef.current.values())
      const width = canvas.clientWidth
      const height = canvas.clientHeight

      const settling = alphaRef.current > 0
      if (nodes.length > 0 && settling) {
        tickPhysics(nodes, width, height, time)
      }

      // Camera: explicit fit request snaps; during the initial settle the
      // camera glides after the fit frame until the user takes over.
      if (fitRequestRef.current) {
        fitRequestRef.current = false
        followRef.current = false
        const fit = fitTransform()
        if (fit) transformRef.current = fit
      } else if (followRef.current) {
        const fit = fitTransform()
        if (fit) {
          const t = transformRef.current
          t.x += (fit.x - t.x) * FOLLOW_LERP
          t.y += (fit.y - t.y) * FOLLOW_LERP
          t.k += (fit.k - t.k) * FOLLOW_LERP
        }
        if (!settling) followRef.current = false
      }

      // ── render ──
      const dpr = Math.min(2, window.devicePixelRatio || 1)
      const t = transformRef.current
      const hovered = hoverRef.current
      const selected = selectedRef.current

      const bg = cssVar(canvas, '--bg-primary', '#191919')
      const textColor = cssVar(canvas, '--text-secondary', '#9a9a9a')
      const isDark = parseInt(bg.slice(1, 3) || 'ff', 16) < 128

      const focusId = hovered?.data.id ?? selected
      let neighbours: Set<string> | null = null
      if (focusId) {
        neighbours = new Set([focusId])
        for (const e of edgesRef.current) {
          if (e.a.data.id === focusId) neighbours.add(e.b.data.id)
          if (e.b.data.id === focusId) neighbours.add(e.a.data.id)
        }
      }

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.fillStyle = bg
      ctx.fillRect(0, 0, width, height)
      ctx.translate(t.x, t.y)
      ctx.scale(t.k, t.k)

      // Visible world-rect for culling (with slack for labels).
      const viewMinX = (-t.x) / t.k - 80
      const viewMinY = (-t.y) / t.k - 80
      const viewMaxX = (width - t.x) / t.k + 80
      const viewMaxY = (height - t.y) / t.k + 80
      const inView = (x: number, y: number) =>
        x >= viewMinX && x <= viewMaxX && y >= viewMinY && y <= viewMaxY

      // Idle breathing (render-only; the physics positions stay frozen).
      // Amplitude ramps in after settling so the freeze→drift transition
      // is seamless instead of popping.
      const settledAt = settledAtRef.current
      const amp = settledAt !== null
        ? Math.min(1, (time - settledAt) / BREATHE_RAMP_MS) * 1.2
        : 0
      const breathe = (n: SimNode) => ({
        x: n.x + Math.sin(time / 1600 + n.phase) * amp,
        y: n.y + Math.cos(time / 1900 + n.phase) * amp,
      })

      // ── Background starfield: distant static specks, faint slow twinkle ──
      if (isDark) {
        for (const s of specksRef.current) {
          if (!inView(s.x, s.y)) continue
          const tw = 0.7 + 0.3 * Math.sin(time / 1400 + s.phase)
          ctx.fillStyle = `rgba(240,224,205,${s.a * tw})`
          ctx.beginPath()
          ctx.arc(s.x, s.y, s.r / Math.max(0.7, t.k), 0, Math.PI * 2)
          ctx.fill()
        }
      }

      // ── Branch lines: straight parent→child segments along each branch ──
      // Replaces the flat file→chunk ribs. Each chunk connects to its
      // parent in the section hierarchy (top-level sections connect to the
      // file), so the tree fans outward without a starburst core.
      ctx.lineWidth = 1 / t.k
      if (showFileLinksRef.current) for (const tree of treesRef.current) {
        const focusInTree =
          focusId !== null && focusId !== undefined &&
          (tree.center.data.id === focusId ||
            tree.members.some(m => m.node.data.id === focusId))
        const dimmedTree = neighbours !== null && !focusInTree
        const alpha = dimmedTree ? 0.04 : 0.12
        // Constellation lines: cool silver, barely there.
        ctx.strokeStyle = isDark
          ? `rgba(236,220,205,${alpha})`
          : `rgba(74,58,48,${alpha})`
        for (const link of tree.links) {
          if (!inView(link.a.x, link.a.y) && !inView(link.b.x, link.b.y)) continue
          const pa = breathe(link.a)
          const pb = breathe(link.b)
          ctx.beginPath()
          ctx.moveTo(pa.x, pa.y)
          ctx.lineTo(pb.x, pb.y)
          ctx.stroke()
        }
      }

      // Edges (entity links; ribs are drawn as org connectors above).
      if (showEntityLinksRef.current) for (const e of edgesRef.current) {
        if (e.rib) continue
        if (!inView(e.a.x, e.a.y) && !inView(e.b.x, e.b.y)) continue
        const pa = breathe(e.a)
        const pb = breathe(e.b)
        const inFocus = !neighbours ||
          (neighbours.has(e.a.data.id) && neighbours.has(e.b.data.id) &&
            (e.a.data.id === focusId || e.b.data.id === focusId))
        ctx.strokeStyle = isDark
          ? `rgba(236,220,205,${inFocus ? 0.28 : 0.05})`
          : `rgba(74,58,48,${inFocus ? 0.22 : 0.04})`
        ctx.beginPath()
        ctx.moveTo(pa.x, pa.y)
        ctx.lineTo(pb.x, pb.y)
        ctx.stroke()
      }

      // ── Nodes: solid, workspace-friendly ──
      //   entity — solid core + thin detached ring, sized by mention count
      //   memory — smaller solid dot
      //   file   — short filled document glyph (FileText icon)
      // No gradients: flat colour reads cleanly on dark AND light themes.
      for (const n of nodes) {
        if (!inView(n.x, n.y)) continue
        const p = breathe(n)
        const age = Math.min(1, (time - n.birth) / ENTRANCE_MS)
        const entrance = 1 - Math.pow(1 - age, 3)
        const dimmed = neighbours ? !neighbours.has(n.data.id) : false
        const faded = n.data.superseded === true
        const isSelected = n.data.id === selected

        let vis = entrance * (dimmed ? 0.12 : faded ? 0.35 : 1)
        if (vis <= 0.01) continue

        const kind = n.data.kind
        const r = n.radius * entrance

        // Selected: radar-ping like the sidebar session dot (1.4s loop).
        // Rings are born at the core and ONLY travel outward, fading as
        // they go; the node's opacity dips smoothly in sync.
        if (isSelected) {
          const phase = ((time % 1400) / 1400)          // 0→1, then reset
          const eased = 1 - Math.pow(1 - phase, 2)      // ease-out travel
          vis *= 1 - 0.35 * Math.sin(phase * Math.PI)   // smooth dip
          const ringR = r * 0.4 + eased * (r + 14)
          ctx.strokeStyle = n.color
          ctx.globalAlpha = 0.55 * (1 - eased)
          ctx.lineWidth = 1.6 / t.k
          ctx.beginPath()
          ctx.arc(p.x, p.y, ringR, 0, Math.PI * 2)
          ctx.stroke()
          ctx.globalAlpha = 1
          ctx.lineWidth = 1 / t.k
        }

        ctx.globalAlpha = vis
        if (kind === 'file') {
          // Files render as a FILLED document glyph so they read as files,
          // not as another coloured node. Portrait page with rounded corners
          // and a folded top-right corner; text lines carved in the
          // background colour. Geometry uses the full radius (not the
          // entrance-scaled r) in a 24×24 local space.
          const sc = (n.radius * 3.0) / 24
          const L = 6.5, R = 17.5, T = 4, B = 20   // page bounds (portrait)
          const RAD = 1.8                          // corner radius
          const FOLD = 4.5                          // dog-ear size
          const FX = R - FOLD, FY = T + FOLD        // fold start / diagonal end
          ctx.save()
          ctx.translate(p.x, p.y)
          ctx.scale(sc, sc)
          ctx.translate(-12, -12)
          ctx.lineJoin = 'round'
          ctx.lineCap = 'round'
          // Page body: top edge → fold diagonal → rounded right/bottom/left.
          ctx.fillStyle = n.color
          ctx.beginPath()
          ctx.moveTo(L + RAD, T)
          ctx.lineTo(FX, T)
          ctx.lineTo(R, FY)
          ctx.arcTo(R, B, R - RAD, B, RAD)
          ctx.arcTo(L, B, L, B - RAD, RAD)
          ctx.arcTo(L, T, L + RAD, T, RAD)
          ctx.closePath()
          ctx.fill()
          // Folded corner: a darker flap so it reads as turned-down paper.
          ctx.fillStyle = 'rgba(0,0,0,0.22)'
          ctx.beginPath()
          ctx.moveTo(FX, T)
          ctx.lineTo(FX, FY)
          ctx.lineTo(R, FY)
          ctx.closePath()
          ctx.fill()
          // Two text lines carved in the background colour.
          ctx.strokeStyle = bg
          ctx.lineWidth = 1.1 / (t.k * sc)
          ctx.beginPath()
          ctx.moveTo(9, 13); ctx.lineTo(15, 13)
          ctx.moveTo(9, 16); ctx.lineTo(15, 16)
          ctx.stroke()
          ctx.restore()
          ctx.lineWidth = 1 / t.k
        } else if (kind === 'entity') {
          // Entities: solid core + thin detached ring (the old file design).
          ctx.fillStyle = n.color
          ctx.beginPath()
          ctx.arc(p.x, p.y, r * 0.62, 0, Math.PI * 2)
          ctx.fill()
          ctx.strokeStyle = n.color
          ctx.lineWidth = 1.2 / t.k
          ctx.beginPath()
          ctx.arc(p.x, p.y, r, 0, Math.PI * 2)
          ctx.stroke()
          ctx.lineWidth = 1 / t.k
        } else {
          // Memories: plain filled dot.
          ctx.fillStyle = n.color
          ctx.beginPath()
          ctx.arc(p.x, p.y, r, 0, Math.PI * 2)
          ctx.fill()
        }
        ctx.globalAlpha = 1
      }

      // ── Labels: greedy declutter in screen space ──
      const fontPx = 11
      ctx.font = `${fontPx / t.k}px ui-sans-serif, system-ui, sans-serif`
      ctx.textAlign = 'center'
      const drawn: Array<{ x: number; y: number; w: number; h: number }> = []
      const overlaps = (x: number, y: number, w: number, h: number) =>
        drawn.some(rct =>
          Math.abs(x - rct.x) < (w + rct.w) / 2 + 4 && Math.abs(y - rct.y) < (h + rct.h) / 2 + 2)

      // Entities and files are ALWAYS label candidates — the greedy
      // declutter below decides what actually fits at the current zoom
      // (larger nodes win). Items are full sentences, so they only reveal
      // on hover/selection or when zoomed in close.
      const candidates: SimNode[] = []
      for (const n of nodes) {
        if (!inView(n.x, n.y)) continue
        const isFocus = n.data.id === focusId || n.data.id === selected
        if (isFocus) { candidates.push(n); continue }
        if (neighbours && !neighbours.has(n.data.id)) continue
        if (n.data.kind === 'entity' || n.data.kind === 'file') candidates.push(n)
        else if (t.k >= 1.6) candidates.push(n)
      }
      candidates.sort((a, b) => {
        const fa = a.data.id === focusId || a.data.id === selected ? 1 : 0
        const fb = b.data.id === focusId || b.data.id === selected ? 1 : 0
        if (fa !== fb) return fb - fa
        return b.radius - a.radius
      })

      const haloColor = isDark ? 'rgba(15,15,15,0.75)' : 'rgba(255,255,255,0.8)'
      for (const n of candidates) {
        const isFocus = n.data.id === focusId || n.data.id === selected
        const p = breathe(n)
        let label = n.data.label
        if (n.data.kind === 'item') {
          label = label.length > 48 ? `${label.slice(0, 48)}…` : label
        } else if (label.length > 28 && !isFocus) {
          label = `${label.slice(0, 28)}…`
        }
        const w = ctx.measureText(label).width
        const sx = p.x * t.k + t.x
        const sy = (p.y - n.radius - 5 / t.k) * t.k + t.y
        if (!isFocus && overlaps(sx, sy, w * t.k, fontPx + 2)) continue
        drawn.push({ x: sx, y: sy, w: w * t.k, h: fontPx + 2 })

        ctx.globalAlpha = isFocus ? 1 : 0.85
        // Text halo so labels stay legible over edges and nodes.
        ctx.lineWidth = 3 / t.k
        ctx.strokeStyle = haloColor
        ctx.lineJoin = 'round'
        ctx.strokeText(label, p.x, p.y - n.radius - 5 / t.k)
        ctx.fillStyle = isFocus
          ? cssVar(canvas, '--text-primary', '#eaeaea')
          : textColor
        ctx.fillText(label, p.x, p.y - n.radius - 5 / t.k)
        ctx.globalAlpha = 1
      }
      ctx.lineWidth = 1 / t.k

      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)

    return () => {
      disposed = true
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [])

  // ── Interaction ────────────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const toWorld = (clientX: number, clientY: number) => {
      const rect = canvas.getBoundingClientRect()
      const t = transformRef.current
      return {
        x: (clientX - rect.left - t.x) / t.k,
        y: (clientY - rect.top - t.y) / t.k,
      }
    }

    const hitTest = (wx: number, wy: number): SimNode | null => {
      let best: SimNode | null = null
      let bestD = Infinity
      for (const n of nodesRef.current.values()) {
        const dx = n.x - wx
        const dy = n.y - wy
        const d = Math.sqrt(dx * dx + dy * dy)
        const hitR = Math.max(n.radius + 4, 8)
        if (d < hitR && d < bestD) { best = n; bestD = d }
      }
      return best
    }

    const wake = (heat: number) => {
      alphaRef.current = Math.max(alphaRef.current, heat)
      settledAtRef.current = null
    }

    const onPointerDown = (e: PointerEvent) => {
      canvas.setPointerCapture(e.pointerId)
      followRef.current = false // user takes the camera
      const w = toWorld(e.clientX, e.clientY)
      const node = hitTest(w.x, w.y)
      dragRef.current = {
        node,
        panning: !node,
        lastX: e.clientX,
        lastY: e.clientY,
        moved: false,
      }
    }

    const onPointerMove = (e: PointerEvent) => {
      const drag = dragRef.current
      const w = toWorld(e.clientX, e.clientY)

      if (drag.node) {
        drag.node.x = w.x
        drag.node.y = w.y
        drag.node.vx = 0
        drag.node.vy = 0
        wake(0.3)
        drag.moved = true
        return
      }
      if (drag.panning) {
        const t = transformRef.current
        t.x += e.clientX - drag.lastX
        t.y += e.clientY - drag.lastY
        drag.lastX = e.clientX
        drag.lastY = e.clientY
        if (Math.abs(e.movementX) + Math.abs(e.movementY) > 1) drag.moved = true
        return
      }
      const hovered = hitTest(w.x, w.y)
      hoverRef.current = hovered
      canvas.style.cursor = hovered ? 'pointer' : 'grab'
    }

    const onPointerUp = (e: PointerEvent) => {
      const drag = dragRef.current
      if (!drag.moved) {
        const w = toWorld(e.clientX, e.clientY)
        const node = hitTest(w.x, w.y)
        onSelectRef.current(node ? node.data : null)
      }
      dragRef.current = { node: null, panning: false, lastX: 0, lastY: 0, moved: false }
    }

    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      followRef.current = false // user takes the camera
      const rect = canvas.getBoundingClientRect()
      const t = transformRef.current
      const factor = Math.exp(-e.deltaY * 0.0012)
      const k = Math.min(4, Math.max(0.2, t.k * factor))
      const px = e.clientX - rect.left
      const py = e.clientY - rect.top
      // Zoom towards the cursor.
      t.x = px - ((px - t.x) / t.k) * k
      t.y = py - ((py - t.y) / t.k) * k
      t.k = k
    }

    const onLeave = () => {
      hoverRef.current = null
    }

    canvas.addEventListener('pointerdown', onPointerDown)
    canvas.addEventListener('pointermove', onPointerMove)
    canvas.addEventListener('pointerup', onPointerUp)
    canvas.addEventListener('wheel', onWheel, { passive: false })
    canvas.addEventListener('pointerleave', onLeave)
    return () => {
      canvas.removeEventListener('pointerdown', onPointerDown)
      canvas.removeEventListener('pointermove', onPointerMove)
      canvas.removeEventListener('pointerup', onPointerUp)
      canvas.removeEventListener('wheel', onWheel)
      canvas.removeEventListener('pointerleave', onLeave)
    }
  }, [])

  return <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block', touchAction: 'none' }} />
}
