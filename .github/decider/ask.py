"""Ask strands-decider the questions in questions.json about a pull request.

Reads the PR from the environment the workflow sets, prints a Markdown report,
and writes it to the path given as the first argument.

Set DECIDER_CHUNK_CHARS to split a large diff into pieces that are asked
separately and combined. Off by default: on a GitHub CPU runner each piece
repeats the header and questions, and the time per token is about the same
past ~2,000 tokens, so splitting measured slower (100 s vs 75 s on a 12k diff).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import psutil
from strands_decider.infer import SystemOneEngine, load_engine
from strands_decider.schema import ChoiceAnswer, NoulAnswer, SystemOneRequest

HERE = Path(__file__).parent
CONFIDENT = 0.9
# Characters per piece, header included, and the most pieces read per PR.
# The default reads one piece of up to 60k characters.
CHUNK_CHARS = int(os.environ.get("DECIDER_CHUNK_CHARS", "60000"))
MAX_CHUNKS = int(os.environ.get("DECIDER_MAX_CHUNKS", "1" if CHUNK_CHARS >= 60000 else "8"))
# Unchanged lines shown around each change; fewer lines, fewer tokens.
CONTEXT = int(os.environ.get("DECIDER_CONTEXT", "1"))

# Machine-written files: their diffs are long, cost the most to read, and say
# little about the change. They still appear in the file list.
SKIP_DIFF = [
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "poetry.lock", "uv.lock", "Pipfile.lock", "Cargo.lock", "go.sum", "Gemfile.lock",
    "composer.lock", "*.min.js", "*.min.css", "*.map", "*.snap", "*.svg",
]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def log(message: str) -> None:
    print(f"decider: {message}", file=sys.stderr, flush=True)


def gib(n: float) -> str:
    return f"{n / 2**30:.1f} GiB"


def log_machine(stage: str) -> None:
    mem, swap = psutil.virtual_memory(), psutil.swap_memory()
    log(f"[{stage}] RAM {gib(mem.available)} free of {gib(mem.total)}, swap used {gib(swap.used)}")


def split_pieces(diff: str, size: int) -> list[str]:
    """Pack whole files into pieces of about `size` characters; split big files by hunk."""
    parts: list[str] = []
    for file_diff in re.split(r"(?m)^(?=diff --git )", diff):
        if not file_diff:
            continue
        if len(file_diff) <= size:
            parts.append(file_diff)
            continue
        header, *hunks = re.split(r"(?m)^(?=@@ )", file_diff)
        for hunk in hunks or [""]:
            text = header + hunk
            parts += [text[i:i + size] for i in range(0, len(text), size)]

    pieces: list[str] = []
    for part in parts:
        if pieces and len(pieces[-1]) + len(part) <= size:
            pieces[-1] += part
        else:
            pieces.append(part)
    return pieces


def pr_states(base: str, head: str) -> tuple[list[str], int]:
    """One state per piece of the diff, and how many pieces were left unread."""
    rng = f"{base}...{head}"
    excludes = [f":(exclude,glob)**/{pattern}" for pattern in SKIP_DIFF]
    diff = git("diff", f"-U{CONTEXT}", rng, "--", ".", *excludes)
    # Every piece repeats this header, so keep it short.
    header = "\n\n".join([
        f"Title: {os.environ.get('PR_TITLE', '')}",
        f"Description:\n{(os.environ.get('PR_BODY') or '(none)')[:800]}",
        f"Files changed:\n{git('diff', '--stat=80', rng)[:1200]}",
    ])
    pieces = split_pieces(diff, max(1500, CHUNK_CHARS - len(header))) or ["(no textual changes)"]
    unread = max(0, len(pieces) - MAX_CHUNKS)
    pieces = pieces[:MAX_CHUNKS]
    states = [
        f"{header}\n\nDiff{f' (part {i} of {len(pieces)})' if len(pieces) > 1 else ''}:\n{piece}"
        for i, piece in enumerate(pieces, 1)
    ]
    return states, unread


def combine(answers: list, weights: list[int]):
    """One answer from the answers to each piece of the diff."""
    first = answers[0]
    if len(answers) == 1:
        return first
    if first.type == "noul":
        # "Does this PR ...?" is yes if any piece of it does.
        return NoulAnswer(noul=max(a.noul for a in answers))
    if first.type == "choice":
        total = sum(weights)
        probs = {k: sum(a.probabilities[k] * w for a, w in zip(answers, weights)) / total
                 for k in first.probabilities}
        choice = max(probs, key=probs.get)
        return ChoiceAnswer(choice=choice, probabilities=probs, confidence=probs[choice])
    # Score: the riskiest piece decides.
    return max(answers, key=lambda a: a.score)


def flag(confidence: float) -> str:
    return "" if confidence >= CONFIDENT else " ⚠️ low confidence"


def report(questions: dict, answers: dict, model: str, footer: str) -> str:
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
        f"<sub>Model: `{model}`. {footer}. "
        f"Answers below {CONFIDENT} confidence need a human look.</sub>",
    ]
    return "\n".join(lines) + "\n"


def choose_dtype() -> str:
    dtype = os.environ.get("DECIDER_DTYPE", "fp32")
    if dtype == "bf16":
        # The engine upcasts the torso to fp32 on CPU (~7 GiB). Keeping bf16 halves
        # that, but measured 6.7x slower on a GitHub runner's AMD EPYC (no native
        # bf16), so only use it if fp32 would not fit in memory at all.
        SystemOneEngine._upcast_torso_for_cpu = lambda self: None
    return dtype


def main() -> None:
    import torch

    model = os.environ["DECIDER_MODEL"]
    questions = json.loads((HERE / "questions.json").read_text())
    states, unread = pr_states(os.environ["BASE_SHA"], os.environ["HEAD_SHA"])
    device = os.environ.get("DECIDER_DEVICE", "cpu")
    dtype = choose_dtype() if device == "cpu" else "model default"

    log(f"{psutil.cpu_count(logical=False)} cores ({psutil.cpu_count()} logical), "
        f"torch threads {torch.get_num_threads()}, dtype {dtype}")
    log(f"diff in {len(states)} piece(s) of up to ~{CHUNK_CHARS:,} chars"
        + (f"; {unread} more piece(s) not read" if unread else ""))
    log_machine("start")

    start = time.perf_counter()
    engine = load_engine(model, device=device)
    log(f"model loaded in {time.perf_counter() - start:,.1f} s")
    log_machine("loaded")

    per_piece: list[dict] = []
    tokens = 0
    start = time.perf_counter()
    for i, state in enumerate(states, 1):
        t = time.perf_counter()
        response = engine.evaluate(SystemOneRequest.model_validate({"state": state, "questions": questions}))
        tokens += response.usage.input_tokens
        per_piece.append(response.answers)
        log(f"piece {i}/{len(states)}: {len(state):,} chars, {response.usage.input_tokens:,} tokens, "
            f"{time.perf_counter() - t:,.1f} s")
        log(f"  raw answers: {response.model_dump_json(include={'answers'})}")
    ask_s = time.perf_counter() - start
    log(f"all answered in {ask_s:,.1f} s")
    log_machine("answered")

    weights = [len(s) for s in states]
    answers = {name: combine([p[name] for p in per_piece], weights) for name in questions}
    footer = (f"{len(questions)} questions in {ask_s:.1f} s on {device} ({tokens:,} tokens"
              + (f", {len(states)} pieces" if len(states) > 1 else "") + ")"
              + (f"; the last {unread} piece(s) of the diff were not read" if unread else ""))
    markdown = report(questions, answers, model, footer)
    print(markdown)
    Path(sys.argv[1]).write_text(markdown)


if __name__ == "__main__":
    main()
