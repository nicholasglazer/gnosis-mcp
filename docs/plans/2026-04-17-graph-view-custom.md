# Custom WebGL Graph View for gnosis-mcp (beats Obsidian)

**Target release:** v0.11.0 (minor bump — headline feature)

**Decision:** Custom implementation, not Sigma.js. Rationale below.

**Goal:** A document-graph visualisation that is (a) visibly 60 fps at 1k–5k nodes on a 2020 laptop, (b) animated with 2026-professional feel (spring physics, easing, ambient motion, bloom), (c) feature-richer than Obsidian's graph view by at least 15 novel capabilities.

## Why custom, not Sigma.js

Sigma.js would ship in 4–8 hours and look like *Sigma.js*. Our brand promise with gnosis-mcp is "the serious, polished RAG option" — the graph view is the screenshot that gets shared. We want *our* visual language, not a library's defaults. We pay 6× the effort (~46 hrs vs ~8 hrs) for complete control over motion, shading, and feature depth. The 15 novel features in § Feature list are not possible inside Sigma without forking internals.

The one concession: physics is solved. We don't reinvent force simulation — we use Rust → WASM compile of a stock Barnes-Hut implementation, running in a Web Worker. That's battle-tested math, not UX.

## Architecture

```
┌────────────────────────────────────────────────────────┐
│  Svelte 5 component — Graph.svelte                     │
│    owns reactivity, emits events, reads gnosis-mcp API │
└──────────────┬─────────────────────────────────────────┘
               │
┌──────────────▼─────────────────────────────────────────┐
│  Renderer (main thread)                                │
│    WebGPU device, command encoders                     │
│    Render pipelines: nodes, edges, SDF labels, bloom   │
│    Compute pipelines: force accumulation + integration │
│    Camera (spring-damped second-order filter)          │
│    Animation scheduler (rAF dirty-flag)                │
│    Hover / click / drag via spatial-hash on CPU        │
└──────────────┬─────────────────────────────────────────┘
               │ WASM imports (topology queries only)
┌──────────────▼─────────────────────────────────────────┐
│  Zig → WASM topology module                            │
│    BFS shortest-path                                   │
│    Louvain community detection                         │
│    Spatial hash build (quadtree lives on GPU)          │
└────────────────────────────────────────────────────────┘
```

Physics moved *onto the GPU*. Every frame the compute pipeline consumes node positions, accumulates forces (O(N log N) via Barnes-Hut tree uploaded as a storage buffer), integrates, writes back. The render pipeline reads the same buffer — zero CPU→GPU copy for positions. Main thread is responsible only for: user input, camera spring, animation scheduler, and launching the compute/render command encoder per frame.

### Layer responsibilities

- **Svelte 5 component**: props in, events out. No drawing code; no physics code. Handles filter/search wiring, deep-link URL state, keyboard handlers.
- **Renderer**: pure WebGL. Reads `SharedArrayBuffer` of node positions written by the worker. One instanced draw call for all nodes, one for all edges, one for all labels. Runs at display refresh via `requestAnimationFrame`, but only *renders* when any of (camera moving, physics not settled, hover state changed, transition in progress) is true. Idle state is zero-draw.
- **Physics worker**: holds graph topology. Runs Barnes-Hut force simulation in a tight WASM loop. Writes new node positions into `SharedArrayBuffer` so main thread sees them without message-passing overhead. Handles Louvain clustering + BFS shortest-path on demand.

### Data flow

1. Svelte component calls `GET /api/graph/stats` → `{nodes, edges}`.
2. Main thread transfers the graph to the worker via `postMessage({type: "init", nodes, edges})`.
3. Worker allocates typed arrays (Float32 positions, velocities; Uint32 edge sources/targets) inside `SharedArrayBuffer`. Returns buffer handle.
4. Renderer receives the handle, binds it as WebGL VBOs (zero-copy on GPU).
5. Worker ticks physics at 60 Hz, mutates the shared buffer in place.
6. Renderer draws at display refresh reading the latest positions from the same memory.
7. Every user interaction (hover/click/drag/filter) fires a message to the worker. Worker responds with either (a) a new buffer region to highlight, or (b) a new simulation command.

### Why `SharedArrayBuffer` and not `postMessage` of position arrays

`postMessage` clones a 4 KB position array 60 times per second = 240 KB/s + JS object allocation pressure. `SharedArrayBuffer` is zero-copy: the worker writes, the main thread reads, both see the same memory. Requires COOP/COEP headers — we set those in the Cloudflare Pages `_headers`.

## Rendering details — the "2026 feel" locked down

### Spring-physics camera

All camera moves (pan, zoom, focus-on-node) are driven by a **second-order low-pass filter** (a.k.a. damped spring), not linear tweens:

```js
// Per frame, target-driven settling
const omega = 2 * Math.PI * frequency;      // natural frequency (Hz)
const zeta = damping;                        // 0..1 (underdamped..critically)
const dt = 1 / 60;

ax = omega * omega * (targetX - posX) - 2 * zeta * omega * velX;
velX += ax * dt;
posX += velX * dt;
```

Defaults: `frequency = 3 Hz`, `zeta = 0.85`. Feels iOS-native — slight overshoot, settles quickly. Applied to zoom (exponential), pan, and focus moves uniformly.

Reference: [Game Programming Gems 4, Ch. 1.10 — second-order low-pass](https://www.gamedeveloper.com/programming/game-programming-gems-4-second-order-dynamics).

### Node breathing (idle ambient motion)

Every node has a per-node phase offset. At idle (simulation alpha < 0.001 for > 1s):

```glsl
// vertex shader fragment
float phase = time * 0.25 + a_phase;       // 4-second period
float breath = 0.015 * sin(phase * 6.283); // ±1.5% scale
gl_PointSize = a_size * (1.0 + breath);
```

Costs ~0.08ms/frame. Makes the graph feel alive, not frozen.

### Edge flow

Each edge draws a subtle gradient travelling from source to target:

```glsl
// fragment shader
float t = mod(v_edge_uv + time * 0.15, 1.0);
float pulse = smoothstep(0.5, 0.6, t) - smoothstep(0.6, 0.7, t);
color.a *= 0.3 + 0.5 * pulse;
```

Conveys directionality (source → target) without arrowheads. Can be toggled off for dense graphs.

### Hover state

- Node scales 1.12× over 80 ms via cubic-bezier(0.2, 0.9, 0.3, 1).
- Connected edges brighten opacity from 0.4 → 1.0.
- All other nodes fade to 15% opacity, unaffected by physics.
- 1-pixel bloom ring on the hovered node (fragment shader radial gradient).
- Preview card HTML panel appears 250 ms later with title + content excerpt + top-3 related. Panel uses `backdrop-filter: blur(12px)`.

### Click-to-focus

- Camera springs to node position + 1.2× zoom.
- Local-graph mode activates: nodes beyond depth 2 fade to 8% opacity.
- Edges within subgraph brighten, edges outside dim.
- URL updates to `?focus=<path>&depth=2`.
- Back/forward browser navigation re-focuses previous nodes smoothly.

### Drag

- Node follows cursor with 40 ms spring lag.
- Physics alpha pumps back up to 0.3 (re-settles).
- Neighbouring nodes trail with reducing amplitude (2nd-order spring cascade).
- Release pins the node unless `Shift` held.

### Reduced motion

When `prefers-reduced-motion: reduce`:
- All spring curves become instant.
- Idle breathing disabled.
- Edge flow disabled.
- Transitions compress to 80 ms linear fades.

## Feature list (vs Obsidian parity)

### Parity with Obsidian (must-have)

1. Force-directed physics with tunable gravity / repel / link / distance sliders.
2. Pan with drag, zoom with wheel/pinch.
3. Hover shows label; click selects + highlights 1-hop neighbourhood.
4. Drag with pinning.
5. Colour by category (palette from design tokens).
6. Label size scales with degree; label rendered above threshold zoom.
7. Local-graph mode (filter to N hops).
8. Folder/category/tag filters.
9. Dark/light theme aware.
10. Screenshot export (PNG).

### Beyond Obsidian (the 15 novel features)

11. **Shortest-path mode** — pick 2 nodes, BFS highlights the path (worker side).
12. **Community clustering** — Louvain on demand, colour-by-cluster toggle.
13. **Semantic heatmap overlay** — type a query, embed it, glow nodes by cosine similarity.
14. **Timeline scrub** — slider shows graph at any git commit (needs new `/api/graph/snapshots`).
15. **Real-time updates** — SSE from `gnosis-mcp serve --watch`; new nodes animate in.
16. **Mini-map** — corner overview, click to teleport, highlight current viewport.
17. **Keyboard navigation** — `j`/`k` across neighbours, `Enter` to focus, `/` to search, `?` help.
18. **Hover preview card** — title + excerpt + top-3 related, no click needed.
19. **Edge "why?"** — click an edge, side panel shows the shared text span that created the link.
20. **Deep-link state** — URL encodes filter, focal, camera position; shareable.
21. **Lasso multi-select** — hold `Shift`, drag to box-select; bulk tag / export / pin.
22. **Presentation mode** — fullscreen, Perlin-noise auto-camera drift, keyboard-driven.
23. **Export** — PNG, SVG, JSON, shareable URL.
24. **Idle ambient motion** — breathing + edge flow (can disable via reduced-motion).
25. **Degree-distribution sparkline** — small chart in corner showing graph statistics.

## Physics — WebGPU compute pipeline

### Why on the GPU

At 5 k nodes, Barnes-Hut on the CPU costs ~4 ms per tick — fine, but competing with render for main-thread frame budget. Moving it to a compute shader with one thread per node parallelises the inner loop perfectly. Measured elsewhere (cosmos.gl) at 100 k nodes / 1 ms per tick. Our 1–5 k target becomes trivial.

### Pipeline layout

Per frame:

1. **CPU (main thread, ~200 µs):** rebuild Barnes-Hut quadtree from current positions. Upload as a compact `array<TreeNode>` storage buffer.
2. **GPU compute dispatch A — forces:** one workgroup per 64 nodes. Each thread walks the tree for its node, accumulates repulsion. Links iterated linearly. Writes velocity deltas.
3. **GPU compute dispatch B — integrate:** one thread per node. Reads velocity, applies damping + center gravity, updates position buffer in place.
4. **GPU render dispatch — nodes + edges + labels + bloom:** single command encoder, all pipelines share the position buffer.

### WGSL sketch

```wgsl
// nodes_force.wgsl
@group(0) @binding(0) var<storage, read> positions : array<vec2f>;
@group(0) @binding(1) var<storage, read_write> velocities : array<vec2f>;
@group(0) @binding(2) var<storage, read> tree : array<TreeNode>;
@group(0) @binding(3) var<storage, read> edges : array<Edge>;
@group(0) @binding(4) var<uniform> params : SimParams;

@compute @workgroup_size(64)
fn cs_forces(@builtin(global_invocation_id) gid : vec3u) {
  let i = gid.x;
  if (i >= arrayLength(&positions)) { return; }
  let p = positions[i];
  var force = vec2f(0.0);

  // Barnes-Hut tree traversal
  var idx = 0u;
  loop {
    let node = tree[idx];
    if (node.size == 0u) { break; }
    let d = node.com - p;
    let r2 = dot(d, d);
    if (node.half * node.half < params.theta2 * r2 || node.size == 1u) {
      force += d * node.mass / (r2 * sqrt(r2) + params.softening);
      idx = node.next;
    } else {
      idx = node.first_child;
    }
    if (idx == 0xffffffffu) { break; }
  }

  // Center gravity
  force -= p * params.center_strength;

  velocities[i] = (velocities[i] + force * params.dt) * params.damping;
}
```

### Topology WASM (Zig)

```zig
// topology.zig — compiled with `zig build-exe -target wasm32-freestanding -O ReleaseFast`
const std = @import("std");

export fn shortest_path(
    src: u32,
    dst: u32,
    adj_offsets: [*]const u32,
    adj_edges: [*]const u32,
    out_path: [*]u32,
    max_len: u32,
) u32 {
    // BFS with parent array, reconstruct path backward
    // ... ~80 LOC
}

export fn louvain_step(
    n_nodes: u32,
    adj_offsets: [*]const u32,
    adj_edges: [*]const u32,
    weights: [*]const f32,
    community: [*]u32, // in/out
) bool {
    // Single Louvain pass; returns true if modularity improved
    // ... ~150 LOC
}
```

Build: `zig build-lib topology.zig -target wasm32-freestanding -O ReleaseSmall -dynamic -rdynamic`. Output: `topology.wasm`, ~12 KB.

Rust alternative: same surface via `wasm-bindgen`; slightly larger binary (~30 KB), ecosystem advantage if you later want `petgraph`. Pick either — the JS caller is identical.

## Backend additions

Existing `/api/graph/stats` covers the current needs. To unlock timeline + real-time:

1. `GET /api/graph/snapshots?file_path=...&limit=50` — returns graph state at each git commit that touched the file. New route, ~40 LOC. Uses existing git history index.
2. `GET /api/graph/events` (SSE) — pushes `{type: "added"|"updated"|"removed", path, category}` events from the file watcher. Streams while `--watch` is active. ~60 LOC.

## File layout (gnosismcp.com repo)

```
src/lib/graph/
  Graph.svelte                  # public component
  GraphControls.svelte          # sidebar with filters + sliders
  GraphMinimap.svelte           # corner overview
  GraphHoverCard.svelte         # floating panel on hover
  GraphLegend.svelte            # category palette
  GraphUnsupported.svelte       # shown when WebGPU unavailable
  renderer/
    Renderer.ts                 # owns WebGPU device + pipelines
    Camera.ts                   # spring physics (second-order filter)
    PipelineNodes.ts            # render pipeline for nodes
    PipelineEdges.ts            # render pipeline for edges
    PipelineLabels.ts           # SDF text pipeline
    PipelineForces.ts           # compute pipeline (force accumulation)
    PipelineIntegrate.ts        # compute pipeline (integration)
    PipelineBloom.ts            # post-processing
    BarnesHut.ts                # CPU quadtree build; uploads to GPU
    shaders/                    # .wgsl files
      nodes_render.wgsl
      edges_render.wgsl
      labels_render.wgsl
      forces.compute.wgsl
      integrate.compute.wgsl
      bloom.frag.wgsl
  topology/
    topology.zig                # Zig source (or topology.rs if Rust picked)
    topology.wasm               # pre-built artefact (committed)
    bindings.ts                 # JS wrapper
  data/
    transformGraph.ts           # /api/graph/stats -> internal format
    useGraph.svelte.ts          # $state wrapper
static/
  fonts/
    inter-msdf.png              # font atlas
    inter-msdf.json             # glyph metrics
```

Total deliverable code ~2 500 LOC TypeScript + ~400 LOC Zig (or Rust) + ~600 LOC WGSL.

## Effort by phase

| Phase | Scope | Hours |
|---|---|---|
| **v0.11.0-alpha.1** | WebGPU renderer, compute physics, Zig WASM topology, pan/zoom/hover/click/drag, color-by-category, SDF labels | **18** |
| **v0.11.0-beta.1** | Shortest-path, Louvain clustering, mini-map, keyboard nav, hover preview, deep-link, reduced-motion | 14 |
| **v0.11.0 GA** | Spring camera + idle ambient + bloom pass + filter transitions + presentation mode + export + polish | 10 |
| **v0.11.1** | Semantic heatmap, timeline scrub, real-time SSE, edge "why?" explanations | 12 |

**Total to ship "beats Obsidian": 42 hrs.** WebGPU-first buys us back 4 hrs over the WebGL + Worker path — compute and render share the same API, one less layer to marshal.

## Risks and mitigations

1. **WebGPU browser support.** April 2026 status is stable on Chrome/Edge/Safari 18+/Firefox. Users on Safari 17 and earlier, Chrome < 113, or corporate Edge with GPU disabled get the unsupported card. We accept the ~2–5% bounce rate.
2. **Zig toolchain for contributors.** Ship pre-built `.wasm` in the repo; `zig` only needed for contributors who edit `topology.zig`. Everyone else never installs it. Same policy applies if the Rust path is chosen.
3. **iOS Safari touch gestures.** Budget 4 hrs for dedicated mobile testing. Custom pinch-zoom + drag disambiguation via [Pointer Events + touch-action CSS](https://developer.mozilla.org/en-US/docs/Web/API/Pointer_events/Pinch_zoom_gestures).
4. **"2026-professional" is subjective.** Pin reference targets now:
   - **Motion feel:** [Linear.app](https://linear.app) transitions, [tldraw](https://tldraw.com) canvas pan, [Figma](https://figma.com) arrow select.
   - **Colour depth:** [Stripe.com](https://stripe.com) gradients — deliberately quiet, never neon.
   - **Typography in UI chrome:** Inter for UI, JetBrains Mono for labels and metrics.
5. **Asset size budget.** Gzipped: WGSL shaders ~4 KB, Zig WASM topology ~8 KB, SDF font atlas ~60 KB, component JS ~40 KB. **Total ~112 KB** — smaller than the original WebGL plan.
6. **GPU driver bugs.** WebGPU is young. Test matrix: latest Chrome on macOS Apple Silicon, Chrome on Windows Intel+Nvidia, Safari 18+ on iPhone 15, Firefox on Linux. Budget 2 hrs for driver-specific workarounds.

## Admin's `DependencyGraph.svelte` (sidenote)

Separate 1–2 hr patch, not coupled to this work:
- Add `d3-zoom` on the SVG root for pan/zoom.
- Replace full-DOM-remount with enter/update/exit pattern (proper d3 idiom).
- Add hover tooltip with service span count + error rate.

At 20–200 service nodes, SVG is fine. Don't cross-pollinate the graph package back to admin until the package has a real 1 k+ customer deployment exercising it — admin's scale doesn't validate the hot paths.

## Reference bar — pin these three moments

When the component ships, these three interactions must feel better than Obsidian's equivalents. If they don't, the phase GA is not done.

1. **Click on a hub node** — camera springs over the hub, local-graph mode fades in, connected edges pulse once, hover card slides in.
2. **Drag a node through a dense cluster** — node lags cursor by ~40 ms, neighbours trail with decreasing amplitude, whole cluster flexes like jelly then resettles.
3. **Toggle "dark mode" mid-animation** — colours morph over 300 ms, no flash, physics continues uninterrupted.

If any of those feel jerky or cheap, we're not done.

## Success criteria

- 60 fps sustained on 2020 MacBook Air M1 with 5 000 nodes + 15 000 edges.
- 60 fps on iPad Air 4th gen (touch).
- Total asset size < 150 KB gzip.
- Lighthouse performance score ≥ 95 on gnosismcp.com `/graph`.
- 20 users tested before GA; Obsidian comparison blind A/B preferring ours ≥ 70%.

## Reference links

- [Game Programming Gems 4 — second-order low-pass camera](https://www.gamedeveloper.com/programming/game-programming-gems-4-second-order-dynamics)
- [dimforge/salva — Rust N-body](https://github.com/dimforge/salva)
- [Barnes-Hut Wikipedia](https://en.wikipedia.org/wiki/Barnes%E2%80%93Hut_simulation)
- [Louvain community detection](https://en.wikipedia.org/wiki/Louvain_method)
- [MSDF text rendering explainer](https://github.com/Chlumsky/msdfgen)
- [`SharedArrayBuffer` + COOP/COEP](https://developer.mozilla.org/en-US/docs/Web/API/SharedArrayBuffer)
- [WebGPU compute shader tutorial — graphics.stanford.edu](https://graphics.stanford.edu/courses/cs248a-22-fall/Lectures/Lecture-WebGPU.pdf)
- [Obsidian graph physics discussion](https://forum.obsidian.md/t/graph-view-physics-and-force-directed-graphs/72586)
- [Cosmograph / cosmos.gl WebGPU force impl](https://github.com/cosmosgl/graph)
