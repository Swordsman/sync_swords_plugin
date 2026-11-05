#!/usr/bin/env python3
"""Question-library audit. Static: schema, vocabularies, nothing lost since v1.
Jev: coverage of every atomic source prompt, duplicate baseline questions, situation-specific leakage."""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

from paths import DATA, output, use_jev  # noqa: E402

use_jev()
from jevbatch import batch_ask  # noqa: E402
from scout import meter_summary, noul  # noqa: E402

LIBRARY, PREVIOUS = DATA / "questions.json", DATA / "questions.v1.json"
SOURCE_FILES = (DATA / "human_sources.md", DATA / "joe_questions.md")

ACTIONS = {"recap", "goal", "inventory", "clarify", "reframe", "plan", "analogize", "alternatives", "expand", "decompose",
           "estimate", "perspective", "assumptions", "provenance", "verify", "trace", "isolate", "discriminate", "calibrate",
           "stress-test", "purpose", "completeness", "consequences", "evaluate", "generalize", "simplify", "causes",
           "retrospect", "disclose", "gap", "probe", "abstract"}
STANCES = {"neutral", "doubting", "expansive", "adversarial"}
STAGES = {"understand", "plan", "execute", "review", "debrief", "any"}
SOURCES = {"joe", "debrief", "polya", "heuer", "klein", "paul-elder", "king", "padesky", "aar", "five-whys", "grow-icf",
           "six-hats", "bloom", "feynman", "debugging", "red-team", "kipling", "fermi", "munger", "chesterton", "kahneman",
           "rubber-duck"}
FIELDS = {"id", "question", "phrasings", "followups", "action", "stance", "stage", "presumes_error", "sources",
          "flip_rate", "fix_rate"}
OPTIONAL = {"note", "triggers"}
# one-call membership scores run lower than per-pair scores (near-verbatim matches land near 0.6), so the cutoffs differ
COVERED, STRONG, DUPLICATE, LEAK = 0.35, 0.5, 0.5, 0.5
GUIDANCE_LABELS = {"Guidance", "Practice rules"}
CONTINUATIONS = {"Anything at all?", "Avoid that.", "Which one is it?"}  # tails that only make sense attached to the sentence before
PARKED = {  # substring of a source prompt -> why it has no library entry (explicit decisions override scores)
    "How committed are you": "human motivation; no model analogue yet",
    "follow silence with patience": "asker guidance (README asker rules)",
    "Ask open questions that evoke discovery": "asker guidance (README asker rules)",
    "avoid leading or closed ones": "asker guidance (README asker rules)",
    "Who does which follow-up": "team logistics",
    "share lessons without blame": "team logistics",
}
ACCEPTED = {  # substring of a source prompt -> why a sub-0.7 match was reviewed and accepted as covered
    "What are the key facts or terms": "fragment from Bloom's remember level; key facts covered by `inventory` follow-up",
    "What could be designed or composed": "paraphrase of the `best-move` follow-up; Jev false negative",
    "What is the base rate, and why would mine differ": "paraphrase of the `base-rate` question; Jev false negative",
    "What is the full set of reasonable explanations": "paraphrase of an `unconsidered` phrasing; Jev false negative",
    "rather than a person": "adapted for models: `why-chain` asks 'rather than a one-off slip'",
    "How good is it by named criteria": "covered jointly by the `tradeoffs` phrasing and its criteria follow-up",
    "What would they call this plan": "paraphrase of a `perspective` follow-up; Jev false negative",
    "Which gaps should be sent out to be filled": "covered by the `info-need` follow-up on getting missing information",
}
RETIRED = {  # v1 text -> why it was removed rather than kept
    "What are you taking for granted, including anything unstated? Which of those, if false, would change your conclusion?":
        "split: the first sentence is the new `assumptions` baseline; the second duplicated `sensitivity`",
}


def load(path: Path = LIBRARY) -> list[dict]:
    return json.loads(path.read_text())


def flatten(entries: list[dict]) -> list[dict]:
    rows = []
    for entry in entries:
        for kind, texts in (("question", [entry["question"]]), ("phrasing", entry["phrasings"]), ("followup", entry["followups"])):
            for text in texts:
                rows.append({"tid": f"T{len(rows):03d}", "entry": entry["id"], "kind": kind, "text": text})
    assert len({row["tid"] for row in rows}) == len(rows), "text ids must be unique"
    return rows


def schema_problems(entries: list[dict]) -> list[str]:
    ids = [entry.get("id") for entry in entries]
    problems = [f"duplicate id: {name}" for name in sorted({name for name in ids if ids.count(name) > 1})]
    owner: dict[str, str] = {}
    for row in flatten(entries):
        key = row["text"].casefold()
        if key in owner:
            problems.append(f"text in both {owner[key]} and {row['entry']}: {row['text']}")
        owner[key] = row["entry"]
    for entry in entries:
        name = entry.get("id", "?")
        if missing := FIELDS - entry.keys():
            problems.append(f"{name}: missing {sorted(missing)}")
        if extra := entry.keys() - FIELDS - OPTIONAL:
            problems.append(f"{name}: unknown fields {sorted(extra)}")
        for field, vocabulary in (("action", ACTIONS), ("stance", STANCES), ("stage", STAGES)):
            if entry.get(field) not in vocabulary:
                problems.append(f"{name}: {field} {entry.get(field)!r}")
        if unknown := set(entry.get("sources", [])) - SOURCES:
            problems.append(f"{name}: sources {sorted(unknown)}")
    return problems


def regression_missing(entries: list[dict]) -> list[str]:
    if not PREVIOUS.exists():  # v1 is not shipped in the skill; the check proved the v2 migration and is done
        return []
    old = {text for entry in load(PREVIOUS) for text in (entry["question"], *entry["variants"])}
    return sorted(old - {row["text"] for row in flatten(entries)} - RETIRED.keys())


TAGS = ("action", "stance", "stage", "presumes_error", "sources", "flip_rate", "fix_rate")


def dump(entries: list[dict], path: Path = LIBRARY) -> None:
    """Write the library in its hand-readable layout: one entry per block, tags on one line."""
    encode = lambda value: json.dumps(value, ensure_ascii=False)  # noqa: E731
    blocks = []
    for entry in entries:
        lines = [f' {{"id": {encode(entry["id"])}, "question": {encode(entry["question"])}',  # separators come from the join
                 f'  "phrasings": {encode(entry["phrasings"])}',
                 f'  "followups": {encode(entry["followups"])}',
                 "  " + ", ".join(f"{encode(tag)}: {encode(entry[tag])}" for tag in TAGS)]
        lines += [f"  {encode(key)}: {encode(entry[key])}" for key in ("triggers", "note") if key in entry]
        blocks.append(",\n".join(lines) + "}")
    text = "[\n" + ",\n".join(blocks) + "\n]\n"
    if json.loads(text) != entries:  # postcondition: the file round-trips to exactly what was passed in
        raise ValueError("dump would not round-trip; nothing written")
    path.write_text(text)


SECTION, SUBSECTION = re.compile(r"^## \d+\. (.+?)\s*$"), re.compile(r"^### (.+?)\s*$")
LABEL = re.compile(r"^([A-Z][\w/()' -]{0,30}):\s+")
SENTENCE = re.compile(r"(?<=\?)\s+|(?<=\.)\s+(?=[A-Z(])")


def split_prompt(text: str) -> list[str]:
    segments: list[str] = []
    for sentence in SENTENCE.split(text):
        parts: list[str] = []
        for part in sentence.split("; "):
            if parts and len(part.split()) < 4:  # "...; is that right?" stays attached
                parts[-1] = f"{parts[-1]}; {part}"
            else:
                parts.append(part)
        for part in (part.strip() for part in parts):
            if segments and part in CONTINUATIONS:
                segments[-1] = f"{segments[-1]} {part}"
            elif len(part.split()) >= 2:
                segments.append(part)
    return segments


def atomic_prompts() -> list[dict]:
    prompts = []
    for path in SOURCE_FILES:
        tradition = part = ""
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if match := SECTION.match(line):
                tradition, part = match[1], ""
            elif match := SUBSECTION.match(line):
                part = match[1]
            elif line.startswith("- "):
                text, label = line[2:].strip(), ""
                if (match := LABEL.match(text)) and "," not in match[1]:
                    label, text = match[1], text[match.end():]
                for segment in split_prompt(text):
                    prompts.append({"pid": f"P{len(prompts):03d}", "file": path.name, "line": number,
                                    "tradition": tradition, "part": part or label, "text": segment,
                                    "guidance": label in GUIDANCE_LABELS})
    assert len({prompt["pid"] for prompt in prompts}) == len(prompts), "prompt ids must be unique"
    return prompts


# Jev cost rule: one state per request, every question answerable from it in that request. All checks below go through a
# single batch_ask, which sends the library once per request and splits only at the context limit.

ACTION_MEANINGS = {
    "recap": "summarize the situation or the reasoning so far", "goal": "state what is wanted and what counts as success",
    "inventory": "list what is known, unknown, or available", "clarify": "pin down meaning or check the task is well formed",
    "reframe": "question whether the question itself is right", "plan": "decide what to do next or how to proceed",
    "analogize": "draw on similar problems, cases, or base rates", "alternatives": "generate other options or explanations",
    "expand": "push for a better or more creative solution", "decompose": "split into parts or simpler versions",
    "estimate": "give rough magnitudes or bounds", "perspective": "take another viewpoint",
    "assumptions": "surface and examine premises", "provenance": "say where a claim came from and what supports it",
    "verify": "check that something is correct or possible", "trace": "walk through it step by step",
    "isolate": "reproduce and narrow down a problem", "discriminate": "tell competing explanations apart with evidence",
    "calibrate": "state confidence and its basis", "stress-test": "try to break it or find how it fails",
    "purpose": "explain why something exists before changing it", "completeness": "find what was missed",
    "consequences": "work out what follows", "evaluate": "judge options by criteria or value",
    "generalize": "apply the result or lesson elsewhere", "simplify": "explain it plainly",
    "abstract": "find the underlying structure", "causes": "trace why something happened",
    "retrospect": "compare plan with outcome and learn", "disclose": "say what is unsaid or what feels off",
    "gap": "name missing information", "probe": "produce a question to ask",
}
STANCE_MEANINGS = {"neutral": "asks for information", "doubting": "questions the current answer or process",
                   "expansive": "asks for more options or a better result", "adversarial": "tries to break it"}
STAGE_MEANINGS = {"understand": "before work starts, making sense of the task", "plan": "choosing an approach",
                  "execute": "while doing the work", "review": "checking the result before it is final",
                  "debrief": "after the outcome or the correct answer is known", "any": "useful at any point"}
assert set(ACTION_MEANINGS) == ACTIONS and set(STANCE_MEANINGS) == STANCES and set(STAGE_MEANINGS) == STAGES


def choice(instructions: str, options: dict, seed: str) -> dict:
    """Options in a per-question shuffled order: Jev leans toward a Choice's first option, so no option is always first."""
    order = sorted(options)
    random.Random(seed).shuffle(order)
    return {"type": "choice", "instructions": instructions, "criteria": {option: options[option] for option in order}}


def library_state(entries: list[dict]) -> dict:
    return {entry["id"]: {"question": entry["question"], "phrasings": entry["phrasings"], "followups": entry["followups"]}
            for entry in entries}


def text_paths(entry: dict) -> list[tuple[str, str, str]]:
    """(path, kind, text) for every text of an entry, as `library.<id>...` paths."""
    paths = [(f"library.{entry['id']}.question", "question", entry["question"])]
    paths += [(f"library.{entry['id']}.{field}[{index}]", field[:-1], text)
              for field in ("phrasings", "followups") for index, text in enumerate(entry[field])]
    return paths


def run_checks(prompts: list[dict], entries: list[dict]) -> dict:
    library = library_state(entries)
    ids = {entry_id: None for entry_id in library}
    asked = [prompt for prompt in prompts if not prompt["guidance"]]
    calls = [({"source": {"text": prompt["text"], "tradition": prompt["tradition"], "technique": prompt["part"]}, "library": library},
              {"in": noul("Does any entry in `library` ask what `source.text` asks, in its question, phrasings, or follow-ups, "
                          "outright or as one of its stated parts, in any wording? Entries that are only broader, related, or on "
                          "the same topic do not count."),
               "which": choice("Which entry in `library` asks what `source.text` asks, in its question, phrasings, or follow-ups? "
                               "Pick the closest.", ids, prompt["pid"])})
             for prompt in asked]
    for entry in entries:  # library-only questions: same state, so batch_ask packs them with everything else
        entry_id = entry["id"]
        others = {other: None for other in ids if other != entry_id}
        questions = {
            "dup": noul(f"Does any other entry in `library` ask the same thing as `library.{entry_id}.question`, so that asking "
                        "both would be redundant? Entries that are related or on the same topic but ask for different things do "
                        "not count."),
            "dup_with": choice(f"Which other entry in `library` comes closest to asking the same thing as "
                               f"`library.{entry_id}.question`?", others, entry_id),
            "action": choice(f"Which operation does `library.{entry_id}.question` ask the model to perform?", ACTION_MEANINGS, entry_id),
            "stance": choice(f"What posture does `library.{entry_id}.question` take toward the model's current work?",
                             STANCE_MEANINGS, entry_id),
            "stage": choice(f"At which point in a task does `library.{entry_id}.question` fit best?", STAGE_MEANINGS, entry_id),
        }
        for index, (text_path, _, _) in enumerate(text_paths(entry)):
            questions[f"leak{index}"] = noul(f"Does `{text_path}` mention a detail of one particular situation, such as a named "
                                             "person, product, tool, file, number, or place, so that it could not be asked unchanged "
                                             "in a different situation? Generic words like 'the task', 'the result', 'the tool', or "
                                             "'the person' do not count.")
        calls.append(({"library": library}, questions))
    answers = batch_ask(calls)
    return {"coverage": list(zip(asked, answers[:len(asked)])), "entries": list(zip(entries, answers[len(asked):]))}


def coverage_results(prompts: list[dict], pairs: list) -> list[dict]:
    by_pid = {prompt["pid"]: answer for prompt, answer in pairs}

    def status(prompt: dict) -> dict:
        if prompt["guidance"]:
            return {**prompt, "status": "guidance", "score": None, "entry": None}
        answer = by_pid[prompt["pid"]]
        score = round(answer["in"]["noul"], 2)
        lookup = lambda table: next((reason for key, reason in table.items() if key.casefold() in prompt["text"].casefold()), None)  # noqa: E731
        parked, accepted = lookup(PARKED), lookup(ACCEPTED)
        label = (f"parked: {parked}" if parked else "covered" if score >= STRONG else f"accepted: {accepted}" if accepted
                 else "weak" if score >= COVERED else "uncovered")
        entry = answer["which"]["choice"] if score >= COVERED else None  # read the Choice only when the Noul says it exists
        return {**prompt, "status": label, "score": score, "entry": entry,
                "entry_confidence": round(answer["which"]["confidence"], 2) if entry else None}

    return [status(prompt) for prompt in prompts]


def main() -> None:
    entries = load()
    rows = flatten(entries)
    prompts = atomic_prompts()
    summary = {"entries": len(entries), "texts": len(rows), "schema_problems": schema_problems(entries),
               "lost_since_v1": regression_missing(entries)}
    checks = run_checks(prompts, entries)

    results = coverage_results(prompts, checks["coverage"])
    output("coverage.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    counts: dict[str, int] = {}
    for result in results:
        counts[result["status"].split(":")[0]] = counts.get(result["status"].split(":")[0], 0) + 1
    summary["coverage"] = {"prompts": len(results), **counts,
                           "to_review": [{"pid": r["pid"], "text": r["text"], "status": r["status"], "score": r["score"]}
                                         for r in results if r["status"] in ("weak", "uncovered")]}

    duplicates, tag_disagreements, leaks = [], [], []
    for entry, answer in checks["entries"]:
        if answer["dup"]["noul"] >= DUPLICATE:
            duplicates.append({"id": entry["id"], "score": round(answer["dup"]["noul"], 2), "closest": answer["dup_with"]["choice"]})
        for tag in ("action", "stance", "stage"):
            if answer[tag]["choice"] != entry[tag]:
                tag_disagreements.append({"id": entry["id"], "tag": tag, "mine": entry[tag], "jev": answer[tag]["choice"],
                                          "jev_confidence": round(answer[tag]["confidence"], 2), "question": entry["question"]})
        for index, (text_path, kind, text) in enumerate(text_paths(entry)):
            if answer[f"leak{index}"]["noul"] >= LEAK:
                leaks.append({"id": entry["id"], "kind": kind, "score": round(answer[f"leak{index}"]["noul"], 2), "text": text})
    duplicates.sort(key=lambda item: item["score"], reverse=True)
    for name, data in (("dedup", duplicates), ("tags", tag_disagreements), ("leakage", leaks)):
        output(f"{name}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False))
    summary["duplicates_flagged"] = [f"{item['score']} {item['id']} ~ {item['closest']}" for item in duplicates]
    summary["tag_disagreements"] = {tag: sum(item["tag"] == tag for item in tag_disagreements) for tag in ("action", "stance", "stage")}
    summary["leaks"] = [f"{leak['score']} {leak['id']}/{leak['kind']}: {leak['text']}" for leak in leaks]
    summary["jev"] = meter_summary()
    output("summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
