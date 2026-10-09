"""Ask strands-decider the questions in questions.json about a pull request.

Reads the PR from the environment the workflow sets, prints a Markdown report,
and writes it to the path given as the first argument.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from strands_decider.infer import load_engine
from strands_decider.schema import SystemOneRequest

HERE = Path(__file__).parent
MAX_DIFF_CHARS = 60_000
CONFIDENT = 0.9


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def pr_state(base: str, head: str) -> str:
    rng = f"{base}...{head}"
    diff = git("diff", rng)
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n[diff truncated]\n"
    return "\n\n".join(
        [
            f"Title: {os.environ.get('PR_TITLE', '')}",
            f"Description:\n{os.environ.get('PR_BODY') or '(none)'}",
            f"Files changed:\n{git('diff', '--stat', rng)}",
            f"Diff:\n{diff}",
        ]
    )


def flag(confidence: float) -> str:
    return "" if confidence >= CONFIDENT else " ⚠️ low confidence"


def report(questions: dict, answers: dict, model: str) -> str:
    lines = ["<!-- strands-decider -->", "## Strands Decider", "", "| Question | Answer |", "| --- | --- |"]
    for name, ans in answers.items():
        question = questions[name]["instructions"]
        if ans.type == "noul":
            verdict = "yes" if ans.noul >= 0.5 else "no"
            text = f"**{verdict}** ({ans.noul:.2f}){flag(max(ans.noul, 1 - ans.noul))}"
        elif ans.type == "choice":
            text = f"**{ans.choice}** ({ans.confidence:.2f}){flag(ans.confidence)}"
        else:
            level = max(ans.probabilities, key=ans.probabilities.get)
            text = f"**{level}** (score {ans.score:.2f}, {ans.confidence:.2f}){flag(ans.confidence)}"
        lines.append(f"| {question} | {text} |")
    lines += ["", f"<sub>Model: `{model}`. Answers below {CONFIDENT} confidence need a human look.</sub>"]
    return "\n".join(lines) + "\n"


def main() -> None:
    model = os.environ["DECIDER_MODEL"]
    questions = json.loads((HERE / "questions.json").read_text())
    request = SystemOneRequest.model_validate(
        {"state": pr_state(os.environ["BASE_SHA"], os.environ["HEAD_SHA"]), "questions": questions}
    )
    engine = load_engine(model, device=os.environ.get("DECIDER_DEVICE", "cpu"))
    response = engine.evaluate(request)
    markdown = report(questions, response.answers, model)
    print(markdown)
    Path(sys.argv[1]).write_text(markdown)


if __name__ == "__main__":
    main()
