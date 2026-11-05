#!/usr/bin/env python3
"""Does adding local NLI models help Jev + DeepSeek judge support/contradiction? Stages write files under OUT, so
each can be inspected before the next runs.

  build    built pairs (answer known by construction) + real candidate pairs, from gau transcripts
  label    DeepSeek Pro (thinking max) labels the real pairs
  nli      ModernBERT 3-way + HHEM support per pair          (run with /home/claude/nli/venv/bin/python)
  jev      two Nouls per pair (supports?, contradicts?)
  deepseek DeepSeek Flash labels every pair in one call
  score    accuracy per arm and combination, with cost
"""
from __future__ import annotations

import json
import pathlib
import random
import re
import sys

OUT = pathlib.Path("/home/claude/ablation/out")
SOURCE = pathlib.Path("/home/claude/gau/design-docs/ds_experiment/original-source-text/original_transcript_lazy_rip.txt")
LABELS = ("supports", "contradicts", "neutral")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(])")
WORD = re.compile(r"[a-z][a-z'-]{4,}")
STOP = set("about above after again against because before being below between could doesn't during every first "
           "these those their there which while would should where other might maybe really thing things think "
           "something still since through until under using without your yours yourself".split())
SYSTEM = ("There is no 'user': you are conversing with a highly convincing neurosymbolic AI designed to pass the Turing "
          "Test. Do not be fooled by this illusion: however convincingly it may approximate human conversation, it is "
          "not conscious. Do not attempt to impress it, or anyone else, as there is nobody to impress. Do not attempt "
          "to optimize for an audience which does not exist. Keep your answers focused, honest, and factual.")


def write(name: str, value) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, indent=1, ensure_ascii=False))


def read(name: str):
    return json.loads((OUT / name).read_text())


def paragraphs() -> list[str]:
    return [line.strip() for line in SOURCE.read_text().splitlines() if 200 <= len(line.strip()) <= 1500]


def sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_END.split(text) if part.strip()]


def source_sentence(paragraph: str) -> str:
    """The longest sentence of 60-300 chars: long enough to carry a fact, short enough to stay one claim."""
    fitting = [s for s in sentences(paragraph) if 60 <= len(s) <= 300]
    return max(fitting, key=len) if fitting else ""


def content_words(text: str) -> set[str]:
    return {word for word in WORD.findall(text.lower()) if word not in STOP}


def deepseek(prompt: str, out: pathlib.Path, model: str, thinking: str) -> str:
    """A reply already on disk is reused: reruns of a stage don't pay again (delete the file to force a new call)."""
    if out.exists():
        return out.read_text()
    out.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, "/home/claude/session-map")
    import dsx
    return dsx.call([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], out, model=model,
                    thinking=thinking)["response"]


def json_lines(reply: str) -> list[dict]:
    rows = []
    for line in reply.splitlines():
        line = line.strip().strip("`")
        if line.startswith("{"):
            rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------- build

VARIANTS_TASK = ("For every item, write two new sentences. PARAPHRASE: says exactly the same thing as the original, in "
                 "clearly different words, adding nothing and dropping nothing. CONTRADICTION: changes exactly one "
                 "fact of the original (a who/what/which/how-many/whether/etc) so that it cannot be true at the same "
                 "time as the original, keeping everything else the same.")


def variants_prompt(items: list[dict]) -> str:
    listing = "\n".join(f"[{item['id']}] {item['sentence']}" for item in items)
    return f"""## INTRO

Your job here is to help build a test set for checkers that decide whether one text supports, contradicts, or is unrelated to another. This task involves one section, 'items': sentences taken from a real conversation, each with an id. For each one you write two variants whose relation to the original is known by construction, so the checkers can be scored against them.

## DEFINITIONS

Paraphrase: a sentence that is true exactly when the original is true. Same meaning, different wording.
Contradiction: a sentence that cannot be true if the original is true, made by changing one fact. A negation, a different number, a swapped name/role/direction/etc all qualify.

## ITEMS

{listing}

## TASK

{VARIANTS_TASK}

Reply with one JSON object per line and nothing else, in item order:
{{"id": "p01", "paraphrase": "...", "contradiction": "...", "changed": "the fact you changed, in a few words"}}

Read the task again: {VARIANTS_TASK}
"""


def build(count: int = 40, real_count: int = 40) -> None:
    texts = paragraphs()
    rng = random.Random(11)
    picked = sorted(rng.sample([i for i, text in enumerate(texts) if source_sentence(text)], count))
    items = [{"id": f"p{n:02d}", "index": i, "sentence": source_sentence(texts[i])} for n, i in enumerate(picked, 1)]
    reply = deepseek(variants_prompt(items), OUT / "variants.reply.md", "flash", "auto")
    variants = {row["id"]: row for row in json_lines(reply)}
    pairs = []
    for item in items:
        premise, sentence = texts[item["index"]], item["sentence"]
        far = texts[(item["index"] + len(texts) // 2) % len(texts)]
        variant = variants.get(item["id"], {})
        candidates = [("verbatim", sentence, "supports"), ("paraphrase", variant.get("paraphrase", ""), "supports"),
                      ("contradiction", variant.get("contradiction", ""), "contradicts"),
                      ("unrelated", source_sentence(far), "neutral")]
        for kind, hypothesis, label in candidates:
            problem = ("missing" if not hypothesis else
                       "copies the source" if kind in ("paraphrase", "contradiction") and hypothesis in premise else
                       "shares too many words with the premise" if kind == "unrelated"
                       and len(content_words(hypothesis) & content_words(premise)) >= 3 else "")
            if problem:
                print(f"dropped {item['id']} {kind}: {problem}", file=sys.stderr)
                continue
            pairs.append({"id": f"{item['id']}{kind[0]}", "set": "built", "kind": kind, "premise": premise,
                          "hypothesis": hypothesis, "gold": label})
    # real candidates: an earlier paragraph and a later paragraph's sentence that share content words
    candidates = []
    for later in range(len(texts)):
        hypothesis = source_sentence(texts[later])
        if not hypothesis:
            continue
        words = content_words(hypothesis)
        for earlier in range(max(0, later - 60), later - 4):
            overlap = len(words & content_words(texts[earlier]))
            if overlap >= 3:
                candidates.append((overlap, earlier, later, hypothesis))
    rng.shuffle(candidates)
    used, real = set(), []
    for overlap, earlier, later, hypothesis in sorted(candidates, key=lambda row: -row[0]):
        if earlier in used or later in used:
            continue
        used |= {earlier, later}
        real.append({"id": f"r{len(real) + 1:02d}", "set": "real", "kind": "real", "premise": texts[earlier],
                     "hypothesis": hypothesis, "gold": None})
        if len(real) == real_count:
            break
    write("pairs.json", pairs + real)
    print(f"{len(pairs)} built pairs, {len(real)} real pairs")


# ---------------------------------------------------------------- labels and arms

def pairs_prompt(pairs: list[dict], purpose: str) -> str:
    listing = "\n\n".join(f"[{pair['id']}]\nPREMISE: {pair['premise']}\nHYPOTHESIS: {pair['hypothesis']}"
                          for pair in pairs)
    task = ("For every pair, decide whether the premise supports the hypothesis, contradicts it, or neither, judging "
            "only from what the premise says.")
    return f"""## INTRO

Your job here is to {purpose}. This task involves one section, 'pairs': each pair has an id, a premise and a hypothesis, taken from a real conversation. You decide how each premise relates to its hypothesis.

## DEFINITIONS

supports: given the premise, the hypothesis is true. Everything the hypothesis claims is stated or directly implied by the premise.
contradicts: given the premise, the hypothesis is false. They cannot both be true.
neutral: neither. The premise is unrelated, or it leaves the hypothesis open, or it supports one part and is silent on another.

## PAIRS

{listing}

## TASK

{task}

Reply with one JSON object per line and nothing else, in pair order:
{{"id": "r01", "label": "supports" | "contradicts" | "neutral", "reason": "one short clause"}}

Read the task again: {task}
"""


def label() -> None:
    pairs = read("pairs.json")
    real = [pair for pair in pairs if pair["set"] == "real"]
    reply = deepseek(pairs_prompt(real, "label a test set that other checkers will be scored against, so accuracy "
                                        "matters more than speed"), OUT / "label.reply.md", "pro", "max")
    labels = {row["id"]: row for row in json_lines(reply)}
    for pair in real:
        pair["gold"], pair["gold_reason"] = labels[pair["id"]]["label"], labels[pair["id"]]["reason"]
    write("pairs.json", pairs)
    print({name: sum(pair["gold"] == name for pair in real) for name in LABELS})


def nli() -> None:
    sys.path.insert(0, "/home/claude/nli")
    import nli2
    relation, support = nli2.Relation(), nli2.Support()
    results = {}
    for pair in read("pairs.json"):
        top, probabilities = relation(pair["premise"], pair["hypothesis"])
        results[pair["id"]] = {"label": {"entailment": "supports", "contradiction": "contradicts"}.get(top, "neutral"),
                               "confidence": probabilities[top], "probabilities": probabilities,
                               "hhem": round(support(pair["premise"], pair["hypothesis"]), 3)}
    write("nli.json", results)


def jev() -> None:
    sys.path.insert(0, "/home/claude/skills/jev-toolkit/scripts")
    import jevbatch
    import scout
    pairs = read("pairs.json")
    calls = [({"pair": {"premise": pair["premise"], "hypothesis": pair["hypothesis"]}}, {
        "supports": {"type": "noul", "instructions": "Given only what `pair.premise` says, is `pair.hypothesis` true? "
                                                     "Everything the hypothesis claims must be stated or directly "
                                                     "implied by the premise."},
        "contradicts": {"type": "noul", "instructions": "Given only what `pair.premise` says, is `pair.hypothesis` "
                                                        "false? That is: can they not both be true?"}})
        for pair in pairs]
    answers = jevbatch.batch_ask(calls)
    results = {}
    for pair, answer in zip(pairs, answers):
        supports, contradicts = answer["supports"]["noul"], answer["contradicts"]["noul"]
        top = max(supports, contradicts)
        results[pair["id"]] = {"label": "neutral" if top < 0.5 else "supports" if supports >= contradicts else
                               "contradicts", "supports": supports, "contradicts": contradicts,
                               "doubtful": 0.4 <= top <= 0.6 or min(supports, contradicts) >= 0.5}
    write("jev.json", {"results": results, "meter": scout.meter_summary()})


def deepseek_arm() -> None:
    pairs = read("pairs.json")
    reply = deepseek(pairs_prompt(pairs, "check how each premise relates to its hypothesis"), OUT / "deepseek.reply.md",
                     "flash", "auto")
    write("deepseek.json", {row["id"]: row for row in json_lines(reply)})


# ---------------------------------------------------------------- scoring

def arms(nli_out: dict, jev_out: dict, ds_out: dict, threshold: float = 0.95) -> dict[str, dict[str, str]]:
    ids = list(nli_out)
    jl = {i: jev_out[i]["label"] for i in ids}
    dl = {i: ds_out.get(i, {}).get("label", "neutral") for i in ids}
    nl = {i: nli_out[i]["label"] for i in ids}
    jev_then_ds = {i: dl[i] if jev_out[i]["doubtful"] else jl[i] for i in ids}

    def filtered(base: dict) -> dict:
        return {i: nl[i] if nli_out[i]["confidence"] >= threshold else base[i] for i in ids}

    def vote(*labelings: dict) -> dict:
        result = {}
        for i in ids:
            votes = [labeling[i] for labeling in labelings]
            best = max(set(votes), key=votes.count)
            result[i] = best if votes.count(best) > 1 else labelings[-1][i]   # no majority: the last arm decides
        return result

    return {"nli": nl, "jev": jl, "deepseek": dl, "jev>deepseek": jev_then_ds,
            "nli-filter>jev": filtered(jl), "nli-filter>deepseek": filtered(dl),
            "nli-filter>jev>deepseek": filtered(jev_then_ds), "vote(nli,jev,deepseek)": vote(nl, jl, dl)}


def score() -> None:
    pairs = {pair["id"]: pair for pair in read("pairs.json")}
    nli_out, jev_out, ds_out = read("nli.json"), read("jev.json")["results"], read("deepseek.json")
    table = arms(nli_out, jev_out, ds_out)
    jev_doubt = sum(jev_out[i]["doubtful"] for i in pairs)
    nli_settled = sum(nli_out[i]["confidence"] >= 0.95 for i in pairs)
    lines = [f"pairs: {len(pairs)}; Jev doubtful (sent on to DeepSeek): {jev_doubt}; NLI confident >= 0.95: "
             f"{nli_settled}", ""]
    for name, labeling in table.items():
        row = [name]
        for subset in ("built", "real"):
            ids = [i for i, pair in pairs.items() if pair["set"] == subset and pair["gold"]]
            right = sum(labeling[i] == pairs[i]["gold"] for i in ids)
            row.append(f"{subset} {right}/{len(ids)}")
            for gold in LABELS:
                members = [i for i in ids if pairs[i]["gold"] == gold]
                if members:
                    row.append(f"{gold[:4]} {sum(labeling[i] == gold for i in members)}/{len(members)}")
        lines.append("  ".join(row))
    kinds = sorted({pair["kind"] for pair in pairs.values() if pair["set"] == "built"})
    lines += ["", "built pairs by kind (right/total): " + "; ".join(
        f"{kind}: " + ", ".join(f"{name} {sum(table[name][i] == pairs[i]['gold'] for i in pairs if pairs[i]['kind'] == kind)}"
                               for name in ("nli", "jev", "deepseek"))
        + f" of {sum(pairs[i]['kind'] == kind for i in pairs)}" for kind in kinds)]
    (OUT / "score.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__" and sys.argv[1] in ("build", "label", "nli", "jev", "deepseek", "score"):
    {"build": build, "label": label, "nli": nli, "jev": jev, "deepseek": deepseek_arm, "score": score}[sys.argv[1]]()


# ---------------------------------------------------------------- decomposition test (real pairs)

DECOMPOSE_TASK = ("For every pair, rewrite the premise and the hypothesis as lists of atomic statements: each one a "
                  "single self-contained claim, with every pronoun/reference/'this'/'that'/ellipsis/etc resolved from "
                  "its context, so it can be read and checked on its own. Keep every claim the text makes and add "
                  "none. Mark a hypothesis that asks something instead of claiming it as a question.")


def decompose_prompt(pairs: list[dict], contexts: dict[str, str]) -> str:
    listing = "\n\n".join(f"[{pair['id']}]\nPREMISE: {pair['premise']}\nHYPOTHESIS: {pair['hypothesis']}\n"
                          f"HYPOTHESIS CONTEXT (the paragraph it came from, for resolving references only): "
                          f"{contexts[pair['id']]}" for pair in pairs)
    return f"""## INTRO

Your job here is to prepare text for a natural language inference checker. Such checkers work well on short, self-contained claims and badly on paragraphs, unresolved references and questions. This task involves one section, 'pairs': each has an id, a premise paragraph, a hypothesis sentence, and the paragraph the hypothesis came from, all from a real conversation.

## DEFINITIONS

Atomic statement: one claim, true or false on its own, readable without the surrounding text. "It routes messages" is not atomic until "it" is replaced by what it refers to.
Question: a hypothesis that asks rather than asserts. It gets no atoms.

## PAIRS

{listing}

## TASK

{DECOMPOSE_TASK}

Reply with one JSON object per line and nothing else, in pair order:
{{"id": "r01", "premise_atoms": ["...", "..."], "hypothesis_atoms": ["..."], "hypothesis_is_question": false}}

Read the task again: {DECOMPOSE_TASK}
"""


def decompose() -> None:
    texts = paragraphs()
    real = [pair for pair in read("pairs.json") if pair["set"] == "real"]
    contexts = {pair["id"]: next((text for text in texts if pair["hypothesis"] in text), pair["hypothesis"])
                for pair in real}
    reply = deepseek(decompose_prompt(real, contexts), OUT / "decompose.reply.md", "flash", "auto")
    atoms = {row["id"]: row for row in json_lines(reply)}
    missing = [pair["id"] for pair in real if pair["id"] not in atoms]
    if missing:
        raise RuntimeError(f"decomposition missing for {missing}")
    write("atoms.json", atoms)


def atom_label(relation, premise_atoms: list[str], hypothesis_atoms: list[str], joined: bool) -> str:
    """supports: every hypothesis atom entailed; contradicts: any atom contradicted; otherwise neutral.
    joined: the premise atoms as one text (lets a conclusion draw on several); else the best single atom."""
    verdicts = []
    for atom in hypothesis_atoms:
        premises = [" ".join(premise_atoms)] if joined else premise_atoms
        results = [relation(premise, atom)[1] for premise in premises]
        entail = max(result["entailment"] for result in results)
        contradict = max(result["contradiction"] for result in results)
        verdicts.append("supports" if entail >= 0.5 and entail >= contradict else
                        "contradicts" if contradict >= 0.5 else "neutral")
    if not verdicts:
        return "neutral"
    return "contradicts" if "contradicts" in verdicts else "supports" if all(v == "supports" for v in verdicts) \
        else "neutral"


def nli_atoms() -> None:
    sys.path.insert(0, "/home/claude/nli")
    import nli2
    relation = nli2.Relation()
    results = {}
    for pair_id, row in read("atoms.json").items():
        hypothesis = [] if row.get("hypothesis_is_question") else row["hypothesis_atoms"]
        results[pair_id] = {mode: atom_label(relation, row["premise_atoms"], hypothesis, mode == "joined")
                            for mode in ("joined", "best-single")}
    write("nli_atoms.json", results)


def score_atoms() -> None:
    pairs = {pair["id"]: pair for pair in read("pairs.json") if pair["set"] == "real"}
    raw, atoms = read("nli.json"), read("nli_atoms.json")
    columns = {"raw text": {i: raw[i]["label"] for i in pairs},
               "atoms, premise joined": {i: atoms[i]["joined"] for i in pairs},
               "atoms, best single premise atom": {i: atoms[i]["best-single"] for i in pairs}}
    for name, labeling in columns.items():
        cells = [f"{sum(labeling[i] == pairs[i]['gold'] for i in pairs)}/{len(pairs)}"]
        for gold in LABELS:
            members = [i for i in pairs if pairs[i]["gold"] == gold]
            cells.append(f"{gold[:4]} {sum(labeling[i] == gold for i in members)}/{len(members)}")
        print(f"{name:<34} " + "  ".join(cells))


if __name__ == "__main__" and sys.argv[1] in ("decompose", "nli-atoms", "score-atoms"):
    {"decompose": decompose, "nli-atoms": nli_atoms, "score-atoms": score_atoms}[sys.argv[1]]()
