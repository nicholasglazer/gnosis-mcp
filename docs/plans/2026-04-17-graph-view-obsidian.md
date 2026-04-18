# Obsidian-style Graph View for gnosis-mcp

**Target release:** v0.11.0 (first minor bump — graph view is a user-facing feature, not a fix)

**Goal:** Ship an interactive, WebGL-rendered document graph that lets users pan/zoom/click around their docs and see how they relate — matching the quality bar of Obsidian's graph view.

**Non-goal:** matching Obsidian's exact behavior pixel-for-pixel. We want the *feel*, not the reimplementation.

## Context — why this matters

Every doc-search tool looks the same at the surface (a text box and a list of results). The graph view is the part that makes people *share screenshots on HN*. It's also load-bearing for navigation: "click the central hub doc, see its neighborhood" is a real exploration pattern that our users do manually today via `get_related`.

## Stack decision — Sigma.js v3 + Graphology (primary), cosmos.gl (fallback)

- **Rendering:** Sigma.js v3 — WebGL (MIT, 94% TS, framework-agnostic). Handles our target (1k nodes / 3k edges) with headroom and degrades to ~10k before chugging.
- **Graph data model:** [Graphology](https://graphology.github.io/) — the canonical "graph" data structure in JS. Handles BFS/centrality for free (local-graph mode, hub detection). Sigma consumes it natively.
- **Force layout:** ForceAtlas2 plugin (`graphology-layout-forceatlas2`) — the same layout Gephi uses. Tunable via sliders like Obsidian's.
- **Fallback to cosmos.gl** only if users complain about > 5k node corpora. cosmos.gl does GPU-side force compute via WebGL transform feedback; measured at 100k+ nodes smooth. API surface is smaller → more glue code. MIT.

Obsidian itself uses PIXI.js + hand-rolled physics (closed-source, devs said the API is "a pain"). Juggl ([HEmile/juggl](https://github.com/HEmile/juggl)) is the closest open clone, built on Cytoscape.js — useful as reference for UX patterns, not as a dep.

## What we're NOT picking and why

| Rejected | Reason |
|---|---|
| d3-force + SVG | Dies above ~2k nodes. Admin's `DependencyGraph.svelte` suffers from this exactly. |
| d3-force + Canvas 2D hand-rolled | Works but 2–3 days of glue for what Sigma gives in 30 lines. |
| Cytoscape.js | Canvas-only, DOM-bound event model; drops frames at 1k with continuous physics. |
| PIXI.js + d3-force (Obsidian's recipe) | 4–5 days, max control, but pays for features Sigma already ships. |
| vis-network | Deprecated. |
| Svelte Flow / @xyflow/svelte | Node-editor, not force graph — wrong fit. |
| three.js / 3d-force-graph | 3D is a distraction; 2D + good physics is what users want for docs. |

## Backend — minimal additions, existing tool covers it

The `get_graph_stats` MCP tool and `GET /api/graph/stats` REST endpoint already return:

```json
{
  "nodes": [{"path": "guides/foo.md", "category": "guides", "degree": 5, "title": "Foo"}],
  "edges": [{"source": "guides/foo.md", "target": "architecture/bar.md", "relation_type": "related"}],
  "stats": {"total_nodes": 142, "total_edges": 310, "hubs": [...], "orphans": [...]}
}
```

**Additions needed:**

1. **New REST endpoint `GET /api/graph`** returning the same shape but with `limit` and `category` filters, and optional `focal_path` + `depth` params for local-graph mode. Reuses existing backend queries — ~50 lines in `rest.py`.
2. Optional: streaming variant for huge graphs via SSE — deferred to v0.12+.

## Frontend — new package in the gnosismcp.com site or a standalone component?

Two options:

**A. Ship the graph embedded in gnosismcp.com.** Marketing angle — the landing page has a live graph of its own docs. Feeds the component via a public endpoint of a public demo instance. Pros: marketing value, zero install friction. Cons: needs a public instance, or bundle a static dataset.

**B. Ship a separate `@gnosis-mcp/graph` npm package.** Pros: users can embed in their own dashboards, `admin.selify.ai` can swap it in for `DependencyGraph.svelte`. Cons: extra release motion.

**Recommendation: do both.** Start with (A) on gnosismcp.com with a static snapshot of the gnosis-mcp repo graph as the demo payload. Extract to a package once the component stabilises.

## File layout (gnosismcp.com repo)

```
src/lib/components/graph/
  Graph.svelte              # top-level component, owns sigma instance + lifecycle
  GraphControls.svelte      # sidebar: physics sliders, category toggles, search
  useGraph.svelte.ts        # $state reactive wrapper around graphology
  transformGraph.ts         # get_graph_stats JSON -> graphology.Graph
  forceAtlas2.worker.ts     # layout in a web worker (keeps main thread @ 60fps)
static/graph-demo.json      # baked snapshot for marketing hero
src/routes/graph/+page.svelte  # standalone page: /graph
```

## UX checklist (minimum viable "Obsidian-quality")

- [ ] Pan with drag, zoom with wheel/pinch (Sigma built-in).
- [ ] Hover: label appears, node pulses gently.
- [ ] Click: node + 1-hop neighborhood highlighted, rest dimmed to ~15% opacity.
- [ ] Drag: pin node under cursor, physics continues for the rest.
- [ ] Color-by-category (palette from our existing base16 tokens).
- [ ] Node size = `1 + log2(degree + 1) * 3` px — visible hubs without giants.
- [ ] Label visibility scales with zoom (`labelRenderedSizeThreshold`).
- [ ] Force-strength slider: repel, link, gravity (defaults matching Obsidian's feel).
- [ ] "Local mode" toggle: filter to N hops from the clicked focal node, smooth transition.
- [ ] Category multi-select filter.
- [ ] Dark/light theme — reads CSS custom properties (we already have these).
- [ ] Empty state + loading skeleton.

## Performance budget

- **Target:** 1 000 nodes + 3 000 edges, steady 60 fps on a 2020 laptop, < 100 ms to first paint after data arrival.
- **Cooling:** run layout aggressively for ~3 s, then drop `alpha` to 0 — idle frame cost becomes pure render.
- **Web worker:** run ForceAtlas2 off the main thread (Graphology supports this out of the box). The main thread only does hit-testing + render.
- **Batched render:** Sigma handles this; we do nothing special.

## Risks

1. **Physics feel** — Obsidian's layout has a very specific "springy" quality. ForceAtlas2 defaults feel different. Tuning takes iteration; budget 2–3 hrs for this alone.
2. **Label collision avoidance** — Sigma skips overlapping labels by default, which looks "empty" at zoom-out. May need a custom reducer.
3. **Theme reactivity** — CSS custom properties don't invalidate Sigma's cached node styles; we re-seed the renderer on theme change.
4. **Mobile touch** — pinch-zoom works out of the box; drag-vs-pan gesture needs testing.

## Effort

- **Backend REST endpoint:** 1 hr
- **Data transform + basic mount:** 2 hrs
- **ForceAtlas2 + hover + click highlight:** 3 hrs
- **Controls panel (sliders + filters):** 2 hrs
- **Local-graph mode:** 1 hr
- **Theme wiring + polish:** 2 hrs
- **Baked demo snapshot + landing integration:** 2 hrs
- **Extract to `@gnosis-mcp/graph` package (deferred phase):** 4 hrs

**Total: ~13 hrs to a polished v0.11 demo on gnosismcp.com. ~17 hrs if we also extract to a standalone package.**

## Release plan

- **v0.11.0-alpha.1:** backend endpoint + standalone `/graph` route on gnosismcp.com with the baked demo. Internal testing.
- **v0.11.0:** + controls panel + local-graph mode + published package. Blog post on the rebuild.
- **v0.11.1+:** iterate on physics feel; add tag filters; maybe add an MCP tool `render_graph` that returns a static PNG for agents that can't do WebGL.

## Reference links

- [Understanding Obsidian's graph core (forum)](https://forum.obsidian.md/t/understanding-the-graph-view-core/41020)
- [Obsidian graph physics discussion](https://forum.obsidian.md/t/graph-view-physics-and-force-directed-graphs/72586)
- [Sigma.js v3 docs](https://www.sigmajs.org/docs/)
- [Graphology docs](https://graphology.github.io/)
- [graphology-layout-forceatlas2](https://graphology.github.io/standard-library/layout-forceatlas2.html)
- [cosmos.gl (MIT engine behind Cosmograph)](https://github.com/cosmosgl/graph)
- [Juggl — open Cytoscape-based Obsidian clone](https://github.com/HEmile/juggl)
- [Nightingale: visualizing million-node graphs](https://nightingaledvs.com/how-to-visualize-a-graph-with-a-million-nodes/)
- [Cylynx: JS graph library comparison](https://www.cylynx.io/blog/a-comparison-of-javascript-graph-network-visualisation-libraries/)
