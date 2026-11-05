// Rulesets as data. "cards": four columns of cards with curved edges. "nodes": a force graph whose groups are held together
// by meta-nodes. Callers may pass their own presets to mountMap (the Intent Maps overview does).
import {COLS, R} from "./util.js";

export const PRESETS = {
  cards: {live: false, settle: 40, top: 28, fit: "width", sweep: {key: "kind", order: COLS}, rules: [
    {id: "look", on: {}, do: [["shape", {as: "card"}]]},
    {id: "columns", on: {}, do: [["column", {key: "kind"}], ["relax", {axis: "y", rate: 0.5}],
                                 ["stack", {axis: "y", gap: 12, per: "kind", start: 28}]]},
  ]},
  nodes: {live: true, fit: "all", rules: [
    {id: "look", on: {}, do: [["shape", {as: "dot"}]]},
    {id: "goal-size", on: {kind: "goal"}, do: [["size", {r: R + 5}]]},
    {id: "physics", on: {}, do: [["repel", {strength: 3800}], ["spring", {length: 150, k: 0.004}], ["gravity", {k: 0.0015}]]},
    {id: "groups", on: {}, do: [["attract", {by: "kind", hold: "row"}]]},
  ]},
};
