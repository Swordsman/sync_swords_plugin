#!/usr/bin/env python3
"""Two CPU NLI checks.
support(premise, claim): HHEM-2.1-open, P(claim is supported by premise); premise may be several sentences joined.
relation(premise, hypothesis): ModernBERT-base-nli, entailment / neutral / contradiction with probabilities.
Revisions are pinned. HHEM's custom code also loads google/flan-t5-base (config + tokenizer) by name; pinned here too.
"""
from __future__ import annotations

import os
import pathlib
import time

HERE = pathlib.Path(__file__).resolve().parent
os.environ.setdefault("HF_HOME", str(HERE / "hf-cache"))

import torch  # noqa: E402
from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: E402

SUPPORT_REPO, SUPPORT_REV = "vectara/hallucination_evaluation_model", "de9a5e6ba9ba"
FOUNDATION_REPO, FOUNDATION_REV = "google/flan-t5-base", "7bcac572ce56"
RELATION_REPO, RELATION_REV = "tasksource/ModernBERT-base-nli", "de4ab7e77845"
MINICHECK_REPO, MINICHECK_REV = "lytang/MiniCheck-Flan-T5-Large", "96eafd01cee2"
MINICHECK_NO, MINICHECK_YES = 3, 209   # token ids the model emits for unsupported / supported (its inference.py)


def full_sha(repo: str, short: str) -> str:
    from huggingface_hub import HfApi
    sha = HfApi().model_info(repo).sha
    if not sha.startswith(short):
        raise RuntimeError(f"{repo} head moved: {sha[:12]} != pinned {short}; review the change, then re-pin")
    return sha


HHEM_PROMPT = ("<pad> Determine if the hypothesis is true given the premise?\n\nPremise: {text1}\n\n"
               "Hypothesis: {text2}")   # from the repo's configuration_hhem_v2.py


class Support:
    """HHEM-2.1-open. remote_code=True runs the repo's own modeling code; False rebuilds the same model from plain
    T5ForTokenClassification plus the repo's weights (no trust_remote_code). Both reproduce the model card's scores."""

    def __init__(self, remote_code: bool = False):
        foundation = full_sha(FOUNDATION_REPO, FOUNDATION_REV)
        self.tokenizer = AutoTokenizer.from_pretrained(FOUNDATION_REPO, revision=foundation)
        revision = full_sha(SUPPORT_REPO, SUPPORT_REV)
        if remote_code:
            self.model = AutoModelForSequenceClassification.from_pretrained(SUPPORT_REPO, revision=revision,
                                                                            trust_remote_code=True).eval()
            self.model.tokenzier = self.tokenizer   # its code loads the tokenizer by bare name: use the pinned one
            return
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file
        from transformers import AutoConfig, T5ForTokenClassification
        config = AutoConfig.from_pretrained(FOUNDATION_REPO, revision=foundation)
        config.num_labels = 2
        self.model = T5ForTokenClassification(config)
        state = load_file(hf_hub_download(SUPPORT_REPO, "model.safetensors", revision=revision))
        missing, unexpected = self.model.load_state_dict({k.removeprefix("t5."): v for k, v in state.items()},
                                                         strict=False)
        if unexpected or set(missing) - {"transformer.encoder.embed_tokens.weight"}:   # that one is tied to shared
            raise RuntimeError(f"HHEM weights don't fit T5ForTokenClassification: {missing} {unexpected}")
        self.model.eval()

    def __call__(self, premise: str, claim: str) -> float:
        with torch.inference_mode():
            if hasattr(self.model, "predict"):
                return float(self.model.predict([(premise, claim)])[0])
            inputs = self.tokenizer([HHEM_PROMPT.format(text1=premise, text2=claim)], return_tensors="pt")
            return float(torch.softmax(self.model(**inputs).logits[:, 0, :], dim=-1)[0, 1])


class MiniCheck:
    """Support check, MiniCheck's own scoring: 'predict: ' + doc + eos + claim, P(support) from the first decoder
    step's logits at the yes/no token ids. One chunk: docs here are short (its code splits docs at ~500 words)."""

    def __init__(self):
        from transformers import AutoModelForSeq2SeqLM
        revision = full_sha(MINICHECK_REPO, MINICHECK_REV)
        self.tokenizer = AutoTokenizer.from_pretrained(MINICHECK_REPO, revision=revision)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(MINICHECK_REPO, revision=revision).eval()

    def __call__(self, premise: str, claim: str) -> float:
        inputs = self.tokenizer("predict: " + self.tokenizer.eos_token.join([premise, claim]), return_tensors="pt",
                                truncation=True, max_length=2048)
        start = torch.zeros((1, 1), dtype=torch.long)
        with torch.inference_mode():
            logits = self.model(**inputs, decoder_input_ids=start).logits[0, 0, [MINICHECK_NO, MINICHECK_YES]]
        return float(torch.softmax(logits, dim=-1)[1])


class Relation:
    def __init__(self):
        revision = full_sha(RELATION_REPO, RELATION_REV)
        self.tokenizer = AutoTokenizer.from_pretrained(RELATION_REPO, revision=revision)
        self.model = AutoModelForSequenceClassification.from_pretrained(RELATION_REPO, revision=revision).eval()
        self.labels = [self.model.config.id2label[index] for index in range(self.model.config.num_labels)]

    def __call__(self, premise: str, hypothesis: str) -> tuple[str, dict[str, float]]:
        inputs = self.tokenizer(premise, hypothesis, return_tensors="pt", truncation=True)
        with torch.inference_mode():
            probabilities = torch.softmax(self.model(**inputs).logits[0], dim=-1).tolist()
        scores = dict(zip(self.labels, (round(p, 3) for p in probabilities)))
        return max(scores, key=scores.get), scores


PAIRS = [  # (expected, premise, hypothesis)
    ("supports", "Alice is taller than Bob. Bob is taller than Carol.", "Alice is taller than Carol."),
    ("supports", "The cache key is the model plus the thinking setting. A prefix is cached only after two requests "
                 "share it.", "A prefix sent by only one request is not cached yet."),
    ("contradicts", "Thinking mode is on by default in DeepSeek V4.", "DeepSeek V4 has thinking turned off by default."),
    ("contradicts", "The meeting moved from Tuesday to Thursday.", "The meeting is on Tuesday."),
    ("unrelated", "The cat slept on the windowsill all afternoon.", "The server listens on port 8080."),
    ("unrelated", "Joe lives in Bothell.", "Joe owns a red bicycle."),
]


def main() -> None:
    torch.set_num_threads(os.cpu_count() or 1)
    checks = {}
    for name, build in (("hhem", lambda: Support(remote_code=False)), ("hhem-remote", lambda: Support(remote_code=True)),
                        ("minicheck", MiniCheck), ("modernbert", Relation)):
        started = time.perf_counter()
        checks[name] = build()
        print(f"load {name}: {time.perf_counter() - started:.1f}s")
        checks[name](*PAIRS[0][1:])   # warm-up, not timed
    print()
    for expected, premise, hypothesis in PAIRS:
        cells = []
        for name, check in checks.items():
            started = time.perf_counter()
            result = check(premise, hypothesis)
            seconds = time.perf_counter() - started
            shown = f"{result[0]} {result[1][result[0]]:.3f}" if isinstance(result, tuple) else f"{result:.3f}"
            cells.append(f"{name}={shown} ({seconds:.3f}s)")
        print(f"{expected:<12} " + "  ".join(cells))


if __name__ == "__main__":
    main()
