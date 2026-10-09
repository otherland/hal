"""Ask strands-decider the questions in questions.json about a pull request.

Reads the PR from the environment the workflow sets, prints a Markdown report,
and writes it to the path given as the first argument.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from strands_decider.infer import load_engine
from strands_decider.schema import SystemOneRequest

HERE = Path(__file__).parent
MAX_DIFF_CHARS = 60_000
CONFIDENT = 0.9

# Machine-written files: their diffs are long, cost the most to read, and say
# little about the change. They still appear in the file list.
SKIP_DIFF = [
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "poetry.lock", "uv.lock", "Pipfile.lock", "Cargo.lock", "go.sum", "Gemfile.lock",
    "composer.lock", "*.min.js", "*.min.css", "*.map", "*.snap", "*.svg",
]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def pr_state(base: str, head: str) -> str:
    rng = f"{base}...{head}"
    excludes = [f":(exclude,glob)**/{pattern}" for pattern in SKIP_DIFF]
    diff = git("diff", rng, "--", ".", *excludes)
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


def log(message: str) -> None:
    print(f"decider: {message}", file=sys.stderr, flush=True)


def timed(fn, *args):
    start = time.perf_counter()
    result = fn(*args)
    return result, (time.perf_counter() - start) * 1000


def report(questions: dict, answers: dict, model: str, timing: str) -> str:
    lines = ["<!-- strands-decider -->", "## Strands Decider", "", "| Question | Answer |", "| --- | --- |"]
    for name, ans in answers.items():
        question = questions[name]["instructions"]
        if ans.type == "noul":
            verdict = "yes" if ans.noul >= 0.5 else "no"
            text = f"**{verdict}** ({ans.noul:.2f}){flag(max(ans.noul, 1 - ans.noul))}"
        elif ans.type == "choice":
            text = f"**{ans.choice}** ({ans.confidence:.2f}){flag(ans.confidence)}"
        else:
            # probabilities are keyed by level index; legend maps index -> label
            level = ans.legend[max(ans.probabilities, key=ans.probabilities.get)]
            text = f"**{level}** (score {ans.score:.2f}, {ans.confidence:.2f}){flag(ans.confidence)}"
        lines.append(f"| {question} | {text} |")
    lines += [
        "",
        f"<sub>Model: `{model}`. {timing}. "
        f"Answers below {CONFIDENT} confidence need a human look.</sub>",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    model = os.environ["DECIDER_MODEL"]
    questions = json.loads((HERE / "questions.json").read_text())
    request = SystemOneRequest.model_validate(
        {"state": pr_state(os.environ["BASE_SHA"], os.environ["HEAD_SHA"]), "questions": questions}
    )
    log(f"state is {len(request.state):,} chars; asking {len(questions)} questions")

    device = os.environ.get("DECIDER_DEVICE", "cpu")
    engine, load_ms = timed(lambda: load_engine(model, device=device))
    log(f"model loaded in {load_ms:,.0f} ms")

    response, ask_ms = timed(engine.evaluate, request)
    tokens = response.usage.input_tokens
    log(f"all questions answered in {ask_ms:,.0f} ms ({tokens:,} input tokens, "
        f"{ask_ms / len(questions):,.0f} ms per question on average)")
    log("raw answers: " + response.model_dump_json())

    # Each question again on its own, with the state already cached, to show
    # what one more question costs.
    if os.environ.get("DECIDER_TIME_EACH") == "1":
        for name, question in request.questions.items():
            single = SystemOneRequest(state=request.state, questions={name: question})
            _, ms = timed(engine.evaluate, single)
            log(f"  {name}: {ms:,.0f} ms on its own")

    timing = f"{len(questions)} questions in {ask_ms / 1000:.1f} s on {device} ({tokens:,} tokens)"
    markdown = report(questions, response.answers, model, timing)
    print(markdown)
    Path(sys.argv[1]).write_text(markdown)


if __name__ == "__main__":
    main()
