// Barnes-Hut repulsion: a quadtree holds each cell's node count, strength sum and centre of mass, so a far-away cluster pushes
// like one heavy node. Cost per tick is about n log n instead of n squared. `theta` is how coarse a far cell may be (cell
// width over distance below theta counts as far); 0 is exact. A pair pushes with the mean of its two strengths, as in the
// pairwise version: a cell pushes with count * (own strength + the cell's mean strength) / 2.
// The tree lives in flat typed arrays (cell c has children KID[4c..4c+3], 0 meaning none: the root is cell 0 and never a
// child), reused between ticks, so a tick allocates nothing.
const MAX_DEPTH = 24;
let cap = 0, X, Y, H, N, SX, SY, SS, KID, ITEM, NEXT, STACK;

function reserve(cells, nodes) {
  if (cells <= cap) return;
  cap = cells;
  [X, Y, H, SX, SY, SS] = Array.from({length: 6}, () => new Float64Array(cap));
  N = new Int32Array(cap); ITEM = new Int32Array(cap); KID = new Int32Array(4 * cap); STACK = new Int32Array(4 * MAX_DEPTH + 8);
  NEXT = new Int32Array(nodes);
}

let used = 0;
const quadrant = (c, px, py) => (px >= X[c] ? 1 : 0) + (py >= Y[c] ? 2 : 0);

function cell(x, y, h) {
  const c = used++;
  X[c] = x; Y[c] = y; H[c] = h; N[c] = 0; SX[c] = SY[c] = SS[c] = 0; ITEM[c] = -1; KID.fill(0, 4 * c, 4 * c + 4);
  return c;
}

function add(c, i, px, py, st) {   // puts node i in the leaf it belongs to, splitting leaves that already hold one
  for (let depth = 0; ; depth++) {
    N[c]++; SX[c] += px[i]; SY[c] += py[i]; SS[c] += st[i];
    if (KID[4 * c] === 0) {
      if (N[c] === 1) { ITEM[c] = i; NEXT[i] = -1; return; }
      if (depth >= MAX_DEPTH || used + 4 > cap) { NEXT[i] = ITEM[c]; ITEM[c] = i; return; }   // coincident nodes share a leaf
      const old = ITEM[c], half = H[c] / 2; ITEM[c] = -1;
      for (let q = 0; q < 4; q++) KID[4 * c + q] = cell(X[c] + (q & 1 ? half : -half), Y[c] + (q & 2 ? half : -half), half);
      const k = KID[4 * c + quadrant(c, px[old], py[old])];
      N[k] = 1; SX[k] = px[old]; SY[k] = py[old]; SS[k] = st[old]; ITEM[k] = old; NEXT[old] = -1;
    }
    c = KID[4 * c + quadrant(c, px[i], py[i])];
  }
}

export function repelBarnesHut(nodes, strengths, theta) {
  const n = nodes.length, px = Float64Array.from(nodes, p => p.x), py = Float64Array.from(nodes, p => p.y);
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (let i = 0; i < n; i++) { x0 = Math.min(x0, px[i]); x1 = Math.max(x1, px[i]); y0 = Math.min(y0, py[i]); y1 = Math.max(y1, py[i]); }
  reserve(8 * n + 64, n);
  used = 0;
  cell((x0 + x1) / 2, (y0 + y1) / 2, Math.max(x1 - x0, y1 - y0) / 2 + 1);
  for (let i = 0; i < n; i++) add(0, i, px, py, strengths);
  for (let i = 0; i < n; i++) {
    const p = nodes[i], own = strengths[i]; let vx = 0, vy = 0, top = 0;
    STACK[top++] = 0;
    while (top) {
      const c = STACK[--top], count = N[c]; if (!count) continue;
      let qx, qy, q;
      if (KID[4 * c] === 0) {   // a leaf: every node in it pushes on its own
        for (let o = ITEM[c]; o >= 0; o = NEXT[o]) if (o !== i) {
          const dx = p.x - px[o], dy = p.y - py[o], d2 = dx * dx + dy * dy + 0.01, f = (own + strengths[o]) / 2 / d2 / Math.sqrt(d2);
          vx += f * dx; vy += f * dy; }
        continue; }
      qx = SX[c] / count; qy = SY[c] / count;
      const outside = Math.abs(p.x - X[c]) > H[c] || Math.abs(p.y - Y[c]) > H[c];   // a cell holding the node itself is always opened
      if (outside && 2 * H[c] < theta * Math.hypot(p.x - qx, p.y - qy)) {
        const dx = p.x - qx, dy = p.y - qy, d2 = dx * dx + dy * dy + 0.01, f = count * (own + SS[c] / count) / 2 / d2 / Math.sqrt(d2);
        vx += f * dx; vy += f * dy;
      } else for (q = 0; q < 4; q++) STACK[top++] = KID[4 * c + q];
    }
    p.vx += vx; p.vy += vy;
  }
}
