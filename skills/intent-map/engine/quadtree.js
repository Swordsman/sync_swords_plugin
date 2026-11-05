// Barnes-Hut repulsion: a quadtree holds each cell's node count, strength sum and centre of mass, so a far-away cluster pushes
// like one heavy node. Cost per tick is about n log n instead of n squared. `theta` is how coarse a far cell may be (cell
// width over distance below theta counts as far); 0 is exact. A pair pushes with the mean of its two strengths, as in the
// pairwise version: a cell pushes with count * (own strength + the cell's mean strength) / 2.
const MAX_DEPTH = 24;

class Cell {
  constructor(x, y, h) { Object.assign(this, {x, y, h, n: 0, mx: 0, my: 0, ms: 0, kids: null, items: []}); }
  add(i, P, depth) {   // P: {x, y, st} arrays by node index
    this.n++; this.mx += P.x[i]; this.my += P.y[i]; this.ms += P.st[i];
    if (!this.kids) {
      if (this.n === 1 || depth >= MAX_DEPTH) { this.items.push(i); return; }
      const half = this.h / 2;
      this.kids = [0, 1, 2, 3].map(q => new Cell(this.x + (q & 1 ? half : -half), this.y + (q & 2 ? half : -half), half));
      const old = this.items; this.items = [];
      for (const o of old) this.kids[this.quadrant(P.x[o], P.y[o])].add(o, P, depth + 1);
    }
    this.kids[this.quadrant(P.x[i], P.y[i])].add(i, P, depth + 1);
  }
  quadrant(px, py) { return (px >= this.x ? 1 : 0) + (py >= this.y ? 2 : 0); }
  contains(px, py) { return Math.abs(px - this.x) <= this.h && Math.abs(py - this.y) <= this.h; }
}

export function buildTree(P, count) {
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (let i = 0; i < count; i++) { x0 = Math.min(x0, P.x[i]); x1 = Math.max(x1, P.x[i]); y0 = Math.min(y0, P.y[i]); y1 = Math.max(y1, P.y[i]); }
  const root = new Cell((x0 + x1) / 2, (y0 + y1) / 2, Math.max(x1 - x0, y1 - y0) / 2 + 1);
  for (let i = 0; i < count; i++) root.add(i, P, 0);
  return root;
}

export function repelBarnesHut(nodes, strengths, theta) {
  const P = {x: Float64Array.from(nodes, n => n.x), y: Float64Array.from(nodes, n => n.y), st: Float64Array.from(strengths)};
  const tree = buildTree(P, nodes.length), stack = [];
  nodes.forEach((p, i) => {
    let vx = 0, vy = 0;
    const push = (qx, qy, count, strength) => {   // the velocity change on p from `count` nodes of mean `strength` at (qx, qy)
      const dx = p.x - qx, dy = p.y - qy, d2 = dx * dx + dy * dy + 0.01, f = count * (strengths[i] + strength) / 2 / d2 / Math.sqrt(d2);
      vx += f * dx; vy += f * dy; };
    stack.push(tree);
    while (stack.length) {
      const c = stack.pop(); if (!c.n) continue;
      if (!c.kids) { for (const o of c.items) if (o !== i) push(P.x[o], P.y[o], 1, P.st[o]); continue; }
      const qx = c.mx / c.n, qy = c.my / c.n;
      if (!c.contains(p.x, p.y) && 2 * c.h < theta * Math.hypot(p.x - qx, p.y - qy)) push(qx, qy, c.n, c.ms / c.n);
      else for (const k of c.kids) stack.push(k);
    }
    p.vx += vx; p.vy += vy;
  });
}
