#!/usr/bin/env python3
"""Every migration that cannot be rolled back has to say so.

`docs/runbook/rollback.md` states the policy: **the application rolls back, the
database rolls forward.** `alembic downgrade` is never run on a production
database, because several migrations are irreversible in substance — a
`downgrade()` that restores a *column* does not restore what was in it. The
consequence is a rule:

> A release containing a destructive or irreversible migration **must say so**,
> and **cannot be rolled back** once deployed — so it ships on its own, never
> bundled with a feature, because bundling removes the ability to roll the
> feature back.

A rule a reviewer has to remember is a rule that holds until the Friday somebody
is in a hurry. This makes it a gate.

**What counts as destructive here**, and what deliberately does not:

* `drop_column`, `drop_table` — data goes, and no downgrade brings it back.
* `alter_column(new_column_name=...)` — a rename in place. Nothing is lost, but
  the old and new application versions **cannot share the schema**, so a rolling
  deploy serves 500s from whichever half is behind. That is the failure D14
  names, and it is why a rename that has to happen is done in two releases:
  add-and-write-both, deploy, backfill, then stop writing the old one and drop
  it later. Each half is individually rollback-able.
* `drop_constraint` is **not** on the list. Dropping a constraint loses no rows
  and is usually how a key gets widened — 0019, 0027 and 0045 all do it for
  exactly that reason. Including it would put twelve migrations behind a
  declaration instead of five, and a gate that fires mostly on safe things is a
  gate that gets its declaration pasted in without being read.

A migration declares itself with a module-level constant::

    #: This migration cannot be rolled back. See docs/runbook/rollback.md.
    DESTRUCTIVE = True

Run with no arguments; exits non-zero on a disagreement.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

VERSIONS = Path(__file__).resolve().parent.parent / "apps" / "api" / "alembic" / "versions"

#: Calls that make a migration one-way. See the module docstring for the
#: reasoning behind each, and behind `drop_constraint`'s absence.
DESTRUCTIVE_CALLS = {"drop_column", "drop_table"}


def _destructive_ops(tree: ast.Module) -> set[str]:
    """What `upgrade()` does that cannot be undone.

    `upgrade()` only: a `drop_column` inside `downgrade()` is that function
    doing its job — removing what `upgrade()` added — and flagging it would
    make every well-written reversible migration look one-way.
    """
    ops: set[str] = set()
    for node in tree.body:
        if not (isinstance(node, ast.FunctionDef) and node.name == "upgrade"):
            continue
        for sub in ast.walk(node):
            if not (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)):
                continue
            if sub.func.attr in DESTRUCTIVE_CALLS:
                ops.add(sub.func.attr)
            elif sub.func.attr == "alter_column" and any(
                kw.arg == "new_column_name" for kw in sub.keywords
            ):
                ops.add("rename_column")
    return ops


def _declares_destructive(tree: ast.Module) -> bool:
    for node in tree.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "DESTRUCTIVE":
                value = node.value
                if isinstance(value, ast.Constant) and value.value is True:
                    return True
    return False


def main() -> int:
    undeclared: list[tuple[str, set[str]]] = []
    stale: list[str] = []

    for path in sorted(VERSIONS.glob("[0-9]*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        ops = _destructive_ops(tree)
        declared = _declares_destructive(tree)
        if ops and not declared:
            undeclared.append((path.name, ops))
        elif declared and not ops:
            # Not fatal on its own, but worth saying: a declaration nobody can
            # trace to an operation is one that gets copied into the next file.
            stale.append(path.name)

    for name in stale:
        print(f"note: {name} declares DESTRUCTIVE but upgrade() does nothing one-way")

    if undeclared:
        print(
            "\nThese migrations cannot be rolled back and do not say so.\n"
            "Add, at module level:\n\n"
            "    #: This migration cannot be rolled back. See docs/runbook/rollback.md.\n"
            "    DESTRUCTIVE = True\n\n"
            "and ship the release on its own rather than bundled with a feature —\n"
            "bundling removes the ability to roll the feature back.\n",
            file=sys.stderr,
        )
        for name, ops in undeclared:
            print(f"  {name}: {', '.join(sorted(ops))}", file=sys.stderr)
        return 1

    total = sum(1 for p in VERSIONS.glob("[0-9]*.py"))
    declared = sum(
        1
        for p in VERSIONS.glob("[0-9]*.py")
        if _declares_destructive(ast.parse(p.read_text(encoding="utf-8")))
    )
    print(
        f"migration safety: {total} migrations, {declared} declared one-way, "
        "and every one that is says so"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
