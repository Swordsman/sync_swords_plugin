#!/usr/bin/env python3
"""Set-membership audit: dedupe the sources in one request, then check each survivor against the whole library in one request."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit  # noqa: E402

FOUND = 0.5
# run-1 audit against v1 (pairwise design): source prompts with no clear match
V1_UNCOVERED = {"P038", "P092", "P136", "P155", "P181", "P185", "P186", "P187", "P210"}
V1_WEAK = {"P024", "P045", "P048", "P049", "P051", "P063", "P083", "P086", "P098", "P121", "P125", "P149", "P151", "P159",
           "P163", "P172", "P173", "P183", "P225"}


def dedupe(prompts: list[dict]) -> tuple[list[dict], dict[str, float]]:
    items = {prompt["pid"]: prompt["text"] for prompt in prompts}
    questions = {f"dup_{pid}": audit.noul(f"Does any item listed before `items.{pid}` in `items` ask the same thing as `items.{pid}`, "
                                          "in any wording? Items that are related but ask for different things do not count.")
                 for pid in items}
    answers = audit.ask_jev({"items": items}, questions)["answers"]
    scores = {pid: answers[f"dup_{pid}"]["noul"] for pid in items}
    return [prompt for prompt in prompts if scores[prompt["pid"]] < FOUND], scores


def membership(prompts: list[dict], library_texts: list[str]) -> dict[str, float]:
    source = {prompt["pid"]: prompt["text"] for prompt in prompts}
    library = {f"L{index:03d}": text for index, text in enumerate(library_texts)}
    questions = {f"in_{pid}": audit.noul(f"Does any text in `library` ask what `source.{pid}` asks, outright or as one of its stated "
                                         "parts, in any wording? Texts that are only broader, related, or on the same topic do not count.")
                 for pid in source}
    answers = audit.ask_jev({"source": source, "library": library}, questions)["answers"]
    return {pid: answers[f"in_{pid}"]["noul"] for pid in source}


def main() -> None:
    prompts = [prompt for prompt in audit.atomic_prompts() if not prompt["guidance"]]
    survivors, dup_scores = dedupe(prompts)
    dropped = [prompt for prompt in prompts if dup_scores[prompt["pid"]] >= FOUND]
    v1_texts = [text for entry in audit.load(audit.PREVIOUS) for text in (entry["question"], *entry["variants"])]
    v2_texts = [row["text"] for row in audit.flatten(audit.load())]
    report = {"prompts": len(prompts), "after_dedupe": len(survivors),
              "dropped_as_duplicates": [f"{dup_scores[p['pid']]:.2f} {p['pid']} {p['text']}" for p in dropped]}
    for name, texts in (("v1", v1_texts), ("v2", v2_texts)):
        scores = membership(survivors, texts)
        missing = {pid for pid, score in scores.items() if score < FOUND}
        report[name] = {"library_texts": len(texts), "missing": len(missing),
                        "missing_texts": sorted(f"{scores[p['pid']]:.2f} {p['pid']} {p['text']}" for p in survivors if p["pid"] in missing)}
        if name == "v1":
            survivor_ids = {prompt["pid"] for prompt in survivors}
            known = (V1_UNCOVERED | V1_WEAK) & survivor_ids
            report[name]["vs_pairwise"] = {"known_gaps_surviving_dedupe": len(known),
                                           "found_uncovered": sorted(V1_UNCOVERED & missing),
                                           "missed_uncovered": sorted((V1_UNCOVERED & survivor_ids) - missing),
                                           "found_weak": len(V1_WEAK & missing), "of_weak": len(V1_WEAK & survivor_ids),
                                           "new_flags": len(missing - V1_UNCOVERED - V1_WEAK)}
    report["jev"] = audit.meter_summary()
    audit.output("membership.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
