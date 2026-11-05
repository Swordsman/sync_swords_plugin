// Suggested links between maps, computed from the maps themselves: terms they share in goal, need and solution text,
// weighted so common words count for little. Pure functions: no DOM, no db.
const STOP = new Set(("that this with from have been into than then them they their there what when which while will would " +
  "should could about after before because between each every only other over same such some very also both does done make made " +
  "more most must need needs needed using used uses user users want wants joe skill plugin page code file files map maps " +
  "build built design goal solution solutions test tests part parts like just it's one two its are for and the not but any all can " +
  "own per via out how why who through kind never system once later shows exists").split(/\s+/));

const stem = (word) => word.replace(/ies$/, "y").replace(/(ing|ed|ly)$/, "").replace(/([^s])s$/, "$1").replace(/e$/, "");

export function termsOf(map) {   // stem -> {word (first spelling seen), tf}
  const body = (map.data?.nodes ?? []).filter((n) => n.kind !== "test").map((n) => n.text);
  const text = [map.title, map.title, map.goal, ...body].join(" ");   // title and goal count double
  const found = new Map();
  for (const word of text.toLowerCase().match(/[a-z][a-z0-9]{3,}/g) ?? []) {
    if (STOP.has(word)) continue;
    const entry = found.get(stem(word)) ?? found.set(stem(word), { word, tf: 0 }).get(stem(word));
    entry.tf++;
  }
  return found;
}

// -> [{a, b, score, terms: [spelling...]}] strongest first. Score is the cosine of the two maps' tf-idf vectors, so a long
// map doesn't match everything by size. Terms most maps share weigh little (idf). Pairs already joined
// by a ref are left out, and each map keeps its `perMap` best links so the overview stays readable.
export function suggest(maps, { minScore = 0.1, minShared = 3, perMap = 2 } = {}) {
  const sets = maps.map(termsOf), df = new Map();
  for (const set of sets) for (const term of set.keys()) df.set(term, (df.get(term) ?? 0) + 1);
  const usable = (term) => df.get(term) > 1;   // a term only one map uses links nothing; one mention is chance, so a map's own vector keeps terms it says twice
  const vector = (set) => new Map([...set].filter(([t, e]) => usable(t) && e.tf > 1).map(([t, e]) => [t, (1 + Math.log(e.tf)) * Math.log((maps.length + 1) / df.get(t))]));
  const vectors = sets.map(vector), norm = vectors.map((v) => Math.sqrt([...v.values()].reduce((s, x) => s + x * x, 0)) || 1);
  const joined = new Set(maps.flatMap((m) => (m.refs ?? []).flatMap((r) => [`${m.slug}|${r.slug}`, `${r.slug}|${m.slug}`])));
  const pairs = [];
  for (let i = 0; i < maps.length; i++) for (let j = i + 1; j < maps.length; j++) {
    if (joined.has(`${maps[i].slug}|${maps[j].slug}`)) continue;
    const shared = [...vectors[i].keys()].filter((t) => vectors[j].has(t));
    const dot = shared.reduce((s, t) => s + vectors[i].get(t) * vectors[j].get(t), 0), score = dot / (norm[i] * norm[j]);
    if (shared.length >= minShared && score >= minScore) {
      shared.sort((p, q) => vectors[j].get(q) * vectors[i].get(q) - vectors[j].get(p) * vectors[i].get(p) || p.localeCompare(q));
      pairs.push({ a: maps[i].slug, b: maps[j].slug, score, terms: shared.slice(0, 3).map((t) => sets[i].get(t).word) });
    }
  }
  pairs.sort((p, q) => q.score - p.score);
  const used = new Map(), keep = [];
  for (const pair of pairs) {   // a link survives if it is within the top few of either end
    const room = (slug) => (used.get(slug) ?? 0) < perMap;
    if (room(pair.a) || room(pair.b)) { keep.push(pair); for (const s of [pair.a, pair.b]) used.set(s, (used.get(s) ?? 0) + 1); }
  }
  return keep;
}
