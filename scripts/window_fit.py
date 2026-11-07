"""Refuse a dispatch that cannot fit one coder window before it costs an hour.

The coder reads its whole prompt before writing a token, inside the same
15-minute generation window. Measured on the oneAPI router (2026-11-06,
lucet-coder-4b-omega): prefill ~43 tok/s at 3.4k tokens, ~22 tok/s at 15.5k;
vortex:59aea97 (a 646-line file, 15.5k tokens) spent 700 s of 900 reading.
A card whose named files would take over half the window to read leaves too
little time to answer: split it so each card touches less, or finish it by hand.
Re-measure these numbers when the model, build or hardware changes.
"""
from pathlib import Path

WINDOW_SECONDS = 900
PREFILL_TOK_PER_S = 25        # measured 22-43 on the oneAPI router, lower at long context
BYTES_PER_TOKEN = 3.0         # source code, numbered lines
OVERHEAD_TOKENS = 5000        # system prompt, request, trail, check
MAX_SHARE = 0.5


def estimate(worktree, files):
    """(prompt tokens, seconds to read them) for the named files that exist."""
    size = 0
    for name in files:
        path = Path(worktree) / name
        if path.is_file():
            size += path.stat().st_size
    tokens = int(size / BYTES_PER_TOKEN) + OVERHEAD_TOKENS
    return tokens, tokens / PREFILL_TOK_PER_S


def check(worktree, files):
    """Raise ValueError when the named files cannot fit one window."""
    if worktree is None:
        return
    tokens, seconds = estimate(worktree, files)
    if seconds > WINDOW_SECONDS * MAX_SHARE:
        raise ValueError(
            f"too large for one coder window: ~{tokens} prompt tokens, ~{seconds / 60:.0f} of "
            f"{WINDOW_SECONDS // 60} min just to read them; split the card so each touches less, "
            "or finish it by hand (no launch)")
