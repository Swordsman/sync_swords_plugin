"""Identity axes for content-free questions. A question is one value per axis; render() turns coordinates into prose.
Contract: two different questions must never share coordinates (else an axis is missing), and one question must never
need two (else it is several questions). Stage, purpose and triggers are applicability metadata, not identity."""
from __future__ import annotations

import itertools

# axis -> value -> (definition for Jev, phrase used when rendering)
TARGET = {
    "goal": ("what is being asked for and what would count as success", "the goal and what would count as success"),
    "terms": ("the meaning of the words or concepts in the task", "the key terms and what they mean"),
    "scope": ("the boundary or count of the thing: what is included, whole or part, one thing or several",
              "the scope: what's included, and whether it's one thing or several"),
    "constraints": ("conditions or requirements the answer must meet", "the constraints"),
    "premises": ("what is being taken as given or assumed true", "the premises you're taking as given"),
    "evidence": ("observations, data, or facts gathered so far", "the evidence"),
    "explanations": ("candidate explanations, hypotheses, or conclusions under consideration",
                     "the candidate explanations or conclusions"),
    "approach": ("the overall plan, method, or frame being used", "your approach"),
    "step": ("one specific step, action, or change, current or next", "the current or next step"),
    "instrument": ("the tool, source, or place being used to look", "the tool, source, or place you're looking"),
    "result": ("the output, answer, or fix produced", "the result"),
    "outcome": ("what actually happened, looked at after the fact", "what actually happened"),
    "prior-work": ("known problems, solutions, tools, or results that already exist",
                   "existing work, solutions, or problems like this one"),
    "self": ("the answerer's own state, reactions, doubts, or unspoken thoughts", "your own reactions and unspoken thoughts"),
    "inquiry": ("the questions being asked, or the ones not being asked", "the questions being asked, and the ones nobody is asking"),
}

MOVE = {
    "articulate": ("state or restate it explicitly", "State {t} explicitly, in your own words."),
    "enumerate": ("list every member or possibility", "Enumerate {t}: list every member or possibility."),
    "justify": ("give the reason for it or show how it is known", "How do you know {t} is right? Show it rather than assert it."),
    "predict": ("work out what follows from it or what should be observed if it holds",
                "If {t} holds, what else follows, or should be observable?"),
    "check": ("test it independently, by a different route or against reality",
              "Check {t} independently, by a different route. Does it hold?"),
    "compare": ("set it against something else: expected versus actual, or one candidate against another",
                "Compare {t} against what was expected, or against the alternatives. Where do they differ?"),
    "rank": ("decide which part matters most or which option is best", "Which part of {t} matters most, and why?"),
    "decompose": ("split it into parts or separate things", "Break {t} into its separate parts. Is it one thing or several?"),
    "combine": ("merge pieces into something new", "What could you build by combining parts of {t}?"),
    "remove": ("take something away or relax it and see what changes",
               "Take away or relax part of {t}. What changes, and what was it actually doing?"),
    "perturb": ("change one thing (late, wrong, hostile) and see what breaks",
                "Change one thing about {t}: make it late, wrong, or hostile. What breaks?"),
    "invert": ("consider the opposite, or what would guarantee the reverse",
               "Consider the opposite of {t}. What would guarantee the reverse, and is any of it present?"),
    "suppose-outcome": ("assume an outcome has already happened and work back to how",
                        "Assume this has already failed (or succeeded). Working back through {t}, what is the most plausible reason?"),
    "relate": ("connect it to a similar case or something already known",
               "What similar case or known pattern does {t} resemble, and what does that tell you?"),
    "generalize": ("extract a rule or lesson that applies beyond this case", "What rule or lesson about {t} applies beyond this case?"),
    "find-gaps": ("look for what is missing, overlooked, or unsaid", "What is missing from {t}, or overlooked in it?"),
    "locate": ("say where something is, or whether the search is in the right place",
               "Where exactly in {t} is the thing that matters, and are you looking in the right place?"),
}

STANCE = {
    "neutral": ("makes no presumption about whether the work is right", ""),
    "doubting": ("suggests the work might be wrong and asks for a check", "Something may be wrong here. "),
    "adversarial": ("assumes the work is wrong or fails, or argues the opposite", "Assume this is wrong. "),
    "expansive": ("assumes something more or better is possible", "Assume something better is possible. "),
}

PERSPECTIVE = {
    "own": ("from the answerer's own viewpoint", ""),
    "opposing": ("from the viewpoint of someone who holds a contrary view", "Answer as someone who holds the opposite view would. "),
    "outsider": ("from an uninvolved or expert observer's viewpoint", "Answer as an uninvolved expert would. "),
    "stakeholder": ("from the viewpoint of the person the work is for or affected by", "Answer as the person this work is for would. "),
    "several": ("from several competing viewpoints in turn", "Answer from each competing viewpoint in turn. "),
}

AXES = {"target": TARGET, "move": MOVE, "stance": STANCE, "perspective": PERSPECTIVE}


def render(target: str | None = None, move: str | None = None, stance: str | None = None, perspective: str | None = None) -> str:
    """An axis left as None renders generically, so a pair of axes can be read on its own."""
    template = MOVE[move][1] if move else "Think about {t}."
    framing = (PERSPECTIVE[perspective][1] if perspective else "") + (STANCE[stance][1] if stance else "")
    return framing + template.format(t=TARGET[target][1] if target else "this")


def grid():
    """Every combination of axis values, in axis order."""
    names = list(AXES)
    for values in itertools.product(*(AXES[name] for name in names)):
        yield dict(zip(names, values))
