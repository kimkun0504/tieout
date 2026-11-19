import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import tree_sitter_language_pack as pack

COMMENT_TYPES = frozenset(
    {
        "comment",
        "line_comment",
        "block_comment",
        "doc_comment",
        "multiline_comment",
        "html_comment",
        "jsx_comment",
    }
)
NOT_SOURCE = frozenset(
    {
        "json",
        "jsonc",
        "json5",
        "yaml",
        "toml",
        "ini",
        "properties",
        "xml",
        "html",
        "markdown",
        "markdown_inline",
        "rst",
        "csv",
        "tsv",
        "gitignore",
        "gitattributes",
        "editorconfig",
        "requirements",
        "diff",
    }
)
NAMED_FILES = {"Dockerfile": "dockerfile", "Makefile": "make", "Justfile": "just"}
GENERATED = re.compile(r"Code generated .* DO NOT EDIT|@generated|maintained automatically by")
HEADER_LINES = 5
HEADER_DIRECTIVES = (re.compile(r"^#!"), re.compile(r"^#.*coding[:=]"))
DIRECTIVES = (
    re.compile(r"^//go:"),
    re.compile(r"^//line "),
    re.compile(r"^//export "),
    re.compile(r"^/// <reference "),
    re.compile(r"^// swift-tools-version"),
    re.compile(r"^# (syntax|escape|check)="),
)


HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True, slots=True)
class Violation:
    path: str
    line: int
    column: int

    def render(self) -> str:
        return f"{self.path}:{self.line}:{self.column}: comments are forbidden (ADR-0001)"


def language_of(path: Path) -> str | None:
    named = NAMED_FILES.get(path.name)
    if named is not None or path.name.startswith("Dockerfile."):
        return named or "dockerfile"
    language = pack.detect_language_from_path(str(path))
    return None if language is None or language in NOT_SOURCE else language


def is_directive(text: str, row: int) -> bool:
    in_header = row <= 1 and any(pattern.match(text) for pattern in HEADER_DIRECTIVES)
    return in_header or any(pattern.match(text) for pattern in DIRECTIVES)


def comment_nodes(root: pack.Node) -> Iterator[pack.Node]:
    pending = [root]
    while pending:
        node = pending.pop()
        if node.type in COMMENT_TYPES:
            yield node
        else:
            pending.extend(reversed(node.children))


def git(*arguments: str) -> str:
    return subprocess.run(["git", *arguments], capture_output=True, text=True, check=True).stdout


def added_lines(base: str) -> dict[str, frozenset[int] | None]:
    added: dict[str, set[int]] = {}
    current: set[int] | None = None
    for line in git("diff", "-U0", "-M", "--no-color", "--no-ext-diff", base, "--").splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            current = added.setdefault(target[2:], set()) if target.startswith("b/") else None
            continue
        hunk = HUNK.match(line)
        if hunk is not None and current is not None:
            start = int(hunk.group(1))
            length = 1 if hunk.group(2) is None else int(hunk.group(2))
            current.update(range(start, start + length))
    changed: dict[str, frozenset[int] | None] = {
        path: frozenset(rows) for path, rows in added.items()
    }
    for path in git("ls-files", "--others", "--exclude-standard").splitlines():
        changed[path] = None
    return changed


def touches(violation: Violation, end_line: int, rows: frozenset[int] | None) -> bool:
    return rows is None or any(row in rows for row in range(violation.line, end_line + 1))


def violations(path: Path, rows: frozenset[int] | None = None) -> list[Violation]:
    language = language_of(path)
    if language is None:
        return []
    source = path.read_bytes()
    header = b"\n".join(source.splitlines()[:HEADER_LINES]).decode(errors="replace")
    if GENERATED.search(header):
        return []
    tree = pack.get_parser(language).parse(source)
    found: list[Violation] = []
    for node in comment_nodes(tree.root_node):
        text = source[node.start_byte : node.end_byte].decode(errors="replace")
        row, column = node.start_point
        violation = Violation(str(path), row + 1, column + 1)
        if not is_directive(text, row) and touches(violation, node.end_point[0] + 1, rows):
            found.append(violation)
    return sorted(found, key=lambda v: (v.line, v.column))


def main(argv: list[str]) -> int:
    changed: dict[str, frozenset[int] | None] | None = None
    if argv[:1] == ["--since"]:
        changed = added_lines(argv[1])
        argv = argv[2:]
    names = sys.stdin.read().split("\0") if argv == ["-"] else argv
    paths = [Path(name) for name in names if Path(name).is_file()]
    if changed is not None:
        paths = [path for path in paths if path.as_posix() in changed]
    found = [
        v
        for path in paths
        for v in violations(path, None if changed is None else changed[path.as_posix()])
    ]
    _ = sys.stdout.write("".join(f"{v.render()}\n" for v in found))
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
