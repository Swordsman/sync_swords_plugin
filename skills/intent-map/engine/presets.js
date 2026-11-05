// Rulesets as data. "cards": four columns of cards with curved edges. "nodes": a force graph whose groups are held together
// by meta-nodes, whose edges get shorter with the priority of their more important end (150 at priority 0, 80 at 5) and whose
// nodes keep their edges at even angles. Callers may pass their own presets to mountMap (the Intent Maps overview does).
import {COLS, R} from "./util.js";

export const PRESETS = {
  cards: {live: false, settle: 40, top: 28, fit: "width", sweep: {key: "kind", order: COLS}, rules: [
    {id: "look", on: {}, do: [["shape", {as: "card"}]]},
    {id: "columns", on: {}, do: [["column", {key: "kind"}], ["relax", {axis: "y", rate: 0.5}],
                                 ["stack", {axis: "y", gap: 12, per: "kind", start: 28}]]},
  ]},
  nodes: {live: true, fit: "all", settle: 150, rules: [
    {id: "look", on: {}, do: [["shape", {as: "dot"}]]},
    {id: "goal-size", on: {kind: "goal"}, do: [["size", {r: R + 5}]]},
    {id: "physics", on: {}, do: [["repel", {strength: 3800}], ["spring", {length: {scale: "priority", from: [0, 5], to: [150, 80]}, k: 0.004}],
                                   ["gravity", {k: 0.0015}]]},
    {id: "fan", on: {}, do: [["spread", {k: 0.1}]]},
    {id: "groups", on: {}, do: [["attract", {by: "kind", hold: "row"}]]},
  ]},
};
