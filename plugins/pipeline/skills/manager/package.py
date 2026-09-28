#!/usr/bin/env python3
import argparse
import os
import re
import subprocess
import sys


def git(*args):
    result = subprocess.run(["git", *args], capture_output=True, encoding="utf-8",
                            errors="replace")
    return result.returncode, result.stdout or "", (result.stderr or "").strip()


def write(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def review(args):
    for label, rev in (("base", args.base), ("head", args.head)):
        if git("rev-parse", "--verify", "--quiet", rev)[0] != 0:
            sys.exit(f"bad {label}: {rev}")
    if git("merge-base", "--is-ancestor", args.base, args.head)[0] != 0:
        sys.exit(f"{args.head} is not a descendant of {args.base}")
    _, count, _ = git("rev-list", "--count", f"{args.base}..{args.head}")
    if int(count.strip() or 0) == 0:
        sys.exit(f"empty commit range: {args.base}..{args.head}")
    span = f"{args.base}..{args.head}"
    _, commits, _ = git("log", "--oneline", span)
    _, stat, _ = git("diff", "--stat", span)
    _, diff, _ = git("diff", "-U10", span)
    _, history, _ = git("log", "-p", "-m", "--format=commit %h %s", span)
    short = lambda rev: git("rev-parse", "--short", rev)[1].strip()
    name = args.name or f"{short(args.base)}..{short(args.head)}"
    package = os.path.join(args.out_dir, f"review-{name}.diff")
    patches = os.path.join(args.out_dir, f"review-{name}.history.patch")
    write(package, f"# Review package: {span}\n\n## Commits\n{commits}\n"
                   f"## Files changed\n{stat}\n## Diff\n{diff}")
    write(patches, f"# Commit-by-commit patches: {span}\n\n{history}")
    print(f"package: {package}")
    print(f"history: {patches}")
    print(f"{count.strip()} commit(s)")


def brief(args):
    any_heading = re.compile(r"^(#+)[ \t]")
    task_heading = re.compile(r"^(#+)[ \t]+Task[ \t]+(\d+)")
    fenced = False
    keep = False
    level = 0
    lines = []
    with open(args.plan, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("```"):
                fenced = not fenced
            task = None if fenced else task_heading.match(line)
            other = None if fenced or task else any_heading.match(line)
            if task:
                keep = task.group(2) == str(args.task)
                level = len(task.group(1))
            elif keep and other and len(other.group(1)) <= level:
                keep = False
            if keep:
                lines.append(line)
    if not lines:
        sys.exit(f"task {args.task} not found in {args.plan}")
    write(args.out, "".join(lines))
    print(f"brief: {args.out} ({len(lines)} lines)")


def main():
    parser = argparse.ArgumentParser(prog="package.py")
    commands = parser.add_subparsers(dest="command", required=True)

    review_cmd = commands.add_parser("review", help="write a review package and history patches for BASE..HEAD")
    review_cmd.add_argument("--base", required=True)
    review_cmd.add_argument("--head", required=True)
    review_cmd.add_argument("--name", help="file name stem, default BASE..HEAD short SHAs")
    review_cmd.add_argument("--out-dir", default=".superpowers/reviews")
    review_cmd.set_defaults(run=review)

    brief_cmd = commands.add_parser("brief", help="extract one task's text from a plan file")
    brief_cmd.add_argument("--plan", required=True)
    brief_cmd.add_argument("--task", required=True)
    brief_cmd.add_argument("--out", required=True)
    brief_cmd.set_defaults(run=brief)

    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
