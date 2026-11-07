"""Signatures of the repository names a plan uses, for a coder that cannot read.

A plan says "call parseListen() on loadHubConfig()'s listen"; a coder with no
read rounds and without config.ts in its files then guesses the shape (live,
vortex:31f3d17: `const { host, port }: String = ...`, twice, both type errors).
For each name the plan writes as `name` or name(), the exported declaration's
first line is looked up in the case worktree and listed under the plan, so the
coder gets the facts without whole extra files in its window.
"""
import re
import subprocess

MAX_NAMES = 12
DECL = r"^export (default )?(async )?(function|const|let|class|interface|type|enum) {name}\b"


def names(plan):
    # `name`, name(), and bare code-shaped words: camelCase / PascalCase with an
    # inner capital (parseListen, HubStore) or UPPER_SNAKE (PRINCIPAL_RE)
    found = re.findall(r"`([A-Za-z_$][\w$]*)(?:\(\))?`|\b([A-Za-z_$][\w$]{3,})\("
                       r"|\b([a-zA-Z][a-z0-9]+[A-Z]\w*|[A-Z][A-Z0-9]*_[A-Z0-9_]+)\b", plan)
    seen = []
    for groups in found:
        n = next(g for g in groups if g)
        if n not in seen:
            seen.append(n)
    return seen[:MAX_NAMES * 2]


def lookup(root, name):
    result = subprocess.run(["git", "-C", str(root), "grep", "-n", "-E", DECL.format(name=re.escape(name)),
                             "--", "*.ts", "*.tsx", "*.js", "*.py", "*.ex"],
                            capture_output=True, text=True)
    hits = [line for line in result.stdout.splitlines() if line]
    if len(hits) != 1:  # unknown, or ambiguous: say nothing rather than mislead
        return None
    path, number, text = hits[0].split(":", 2)
    text = text.strip()
    if text.endswith("{"):  # the body opens on this line; the signature is what precedes it
        text = text[:-1].rstrip()
    return f"{path}:{number}: {text}"


def section(root, plan):
    """'' or a block listing the plan's repository names with their declarations."""
    lines = []
    for name in names(plan):
        found = lookup(root, name)
        if found and found not in lines:
            lines.append(found)
        if len(lines) == MAX_NAMES:
            break
    if not lines:
        return ""
    return "\n\nDeclarations of the names this plan uses (as they are in the repository):\n" + "\n".join(lines)
