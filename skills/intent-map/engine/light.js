// Highlight: hovering or pinning a node lights its upstream and downstream (or just its neighbours) and dims the rest.

function reach(start, edges, pick) {
  const seen = new Set([start]), stack = [start], hot = new Set();
  while (stack.length) { for (const l of edges.get(stack.pop())) { hot.add(l); const m = pick(l);
    if (!seen.has(m)) { seen.add(m); stack.push(m); } } }
  return [seen, hot];
}

function lit(cx, n) {   // [nodes lit, links lit]; "adjacent" is for graphs whose edges carry no direction
  if (cx.opts.reach === "adjacent") {
    return [new Set([n, ...cx.neighbors.get(n)]), new Set(cx.links.filter(l => l.s === n || l.t === n))];
  }
  const [down, hotDown] = reach(n, cx.out, l => l.t), [up, hotUp] = reach(n, cx.inn, l => l.s);
  return [new Set([...down, ...up]), new Set([...hotDown, ...hotUp])];
}

export function light(cx, n) {
  const [nodes, hotLinks] = n ? lit(cx, n) : [null, null];
  for (const m of cx.nodes) { const off = nodes ? !nodes.has(m) : false; m.card.classList.toggle("dim", off); m.dot.classList.toggle("dim", off); }
  for (const l of cx.links) {
    const hot = hotLinks ? hotLinks.has(l) : false;
    for (const p of [l.wire, l.path, l.text]) if (p) { p.classList.toggle("hot", hot && p !== l.text); p.classList.toggle("dim", !!n && !hot); }
    if (l.directed) l.wire.setAttribute("marker-end", `url(#${hot ? cx.arrowHot : cx.arrow})`);
  }
}
