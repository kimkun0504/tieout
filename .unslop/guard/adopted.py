import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import unquote, urlparse

ROOT = Path.cwd().resolve()
CONFIG = Path(".unslop/adopt.json")
BASELINES = Path(".unslop/baseline")
DIFF_COVER = "diff-cover==11.0.1"
GUARD_PATHS = (".unslop/*", "tools/guard/*", "scripts/*")
LINE = re.compile(r"^(?P<path>[^:\n]+):(?P<line>\d+):\d+: (?P<message>.*)$")
MSBUILD_LINE = re.compile(
    r"^(?P<path>[^(\n]+?)\((?P<line>\d+),\d+(?:,\d+,\d+)?\): (?:warning|error) (?P<rule>[A-Za-z]+\d+): (?P<message>.*?)(?: \[[^\]]*\])?$"
)
COMPILER_LINE = re.compile(r"^(?P<path>[^:\n]+\.[A-Za-z]+):(?P<line>\d+):\d+: (?:warning|error): (?P<message>.*)$")
ELIXIR_WARNING = re.compile(r"^\s*warning: (?P<message>.*)$")
ELIXIR_LOCATION = re.compile(r"^\s*(?:└─ )?(?P<path>[^\s:]+\.exs?):(?P<line>\d+)(?::\d+)?:")
TERMINAL_CODES = re.compile(r"\x1b\]8;;[^\x1b]*\x1b\\|\x1b\[[0-9;?]*[A-Za-z]")
QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'|`[^`]*`|\d+")
SWIFT_GROUP = re.compile(r"\[#(?P<group>[A-Za-z]+)\]")
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
TSC_LINE = re.compile(r"^(?P<path>.+?)\((?P<line>\d+),\d+\): error (?P<rule>TS\d+): (?P<message>.*)$")

type Json = dict[str, object]


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    rule: str
    line: int
    message: str

    def render(self) -> str:
        return f"  {self.path}:{self.line}: [{self.rule}] {self.message}"


class BrokenCheckError(Exception):
    def __init__(self, name: str, problem: str) -> None:
        super().__init__(f"{name}: {problem}; fix the command in .unslop/adopt.json instead of trusting an empty result")


def relative(raw: str) -> str:
    text = unquote(urlparse(raw).path) if raw.startswith("file:") else raw
    path = Path(text)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            return path.as_posix()
    return Path(os.path.normpath(text)).as_posix()


def objects(value: object) -> list[Json]:
    return [cast("Json", item) for item in cast("list[object]", value) if isinstance(item, dict)] if isinstance(value, list) else []


def field(value: Json, *keys: str) -> object:
    current: object = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = cast("Json", current).get(key)
    return current


def text(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def number(value: object) -> int:
    return value if isinstance(value, int) else 0


def sarif(report: str) -> Iterator[Finding]:
    document = cast("Json", json.loads(report))
    for run in objects(document.get("runs")):
        for result in objects(run.get("results")):
            locations = objects(result.get("locations"))
            location = locations[0] if locations else {}
            uri = text(field(location, "physicalLocation", "artifactLocation", "uri"), "<unknown>")
            yield Finding(
                relative(uri),
                text(result.get("ruleId"), "unnamed"),
                number(field(location, "physicalLocation", "region", "startLine")),
                text(field(result, "message", "text")),
            )


def pyright(report: str) -> Iterator[Finding]:
    document = cast("Json", json.loads(report))
    for diagnostic in objects(document.get("generalDiagnostics")):
        yield Finding(
            relative(text(diagnostic.get("file"), "<unknown>")),
            text(diagnostic.get("rule"), text(diagnostic.get("severity"), "unnamed")),
            number(field(diagnostic, "range", "start", "line")) + 1,
            text(diagnostic.get("message")).splitlines()[0] if text(diagnostic.get("message")) else "",
        )


def eslint(report: str) -> Iterator[Finding]:
    for entry in objects(json.loads(report)):
        for message in objects(entry.get("messages")):
            yield Finding(
                relative(text(entry.get("filePath"), "<unknown>")),
                text(message.get("ruleId"), "fatal"),
                number(message.get("line")),
                text(message.get("message")),
            )


def tsc(report: str) -> Iterator[Finding]:
    for line in report.splitlines():
        match = TSC_LINE.match(line)
        if match is not None:
            yield Finding(relative(match["path"]), match["rule"], int(match["line"]), match["message"])


def lines(report: str) -> Iterator[Finding]:
    for line in report.splitlines():
        match = LINE.match(line)
        if match is not None:
            message = match["message"]
            yield Finding(relative(match["path"]), message.split(";")[0].split(" (")[0], int(match["line"]), message)


def shape(message: str) -> str:
    return QUOTED.sub("_", message).strip()


def cargo(report: str) -> Iterator[Finding]:
    for line in report.splitlines():
        if not line.startswith("{"):
            continue
        entry = cast("Json", json.loads(line))
        message = entry.get("message")
        if entry.get("reason") != "compiler-message" or not isinstance(message, dict):
            continue
        diagnostic = cast("Json", message)
        primary = [span for span in objects(diagnostic.get("spans")) if span.get("is_primary") is True]
        if not primary:
            continue
        text_ = text(diagnostic.get("message"))
        rule = text(field(diagnostic, "code", "code"), shape(text_))
        yield Finding(relative(text(primary[0].get("file_name"))), rule, number(primary[0].get("line_start")), text_)


def msbuild(report: str) -> Iterator[Finding]:
    seen: set[str] = set()
    for line in report.splitlines():
        match = MSBUILD_LINE.match(line.strip())
        if match is not None and line.strip() not in seen:
            seen.add(line.strip())
            yield Finding(relative(match["path"]), match["rule"], int(match["line"]), match["message"])


def compiler(report: str) -> Iterator[Finding]:
    seen: set[str] = set()
    for line in report.splitlines():
        match = COMPILER_LINE.match(line.strip())
        if match is not None and line.strip() not in seen:
            seen.add(line.strip())
            message = match["message"]
            group = SWIFT_GROUP.search(message)
            rule = group["group"] if group is not None else shape(message)
            yield Finding(relative(match["path"]), rule, int(match["line"]), message)


def elixir(report: str) -> Iterator[Finding]:
    pending: str | None = None
    for line in report.splitlines():
        warning = ELIXIR_WARNING.match(line)
        if warning is not None:
            pending = warning["message"]
            continue
        location = ELIXIR_LOCATION.match(line)
        if location is not None and pending is not None:
            yield Finding(relative(location["path"]), shape(pending), int(location["line"]), pending)
            pending = None


def phpstan(report: str) -> Iterator[Finding]:
    document = cast("Json", json.loads(report))
    files = document.get("files")
    for path, entry in cast("dict[str, object]", files).items() if isinstance(files, dict) else []:
        for message in objects(field(cast("Json", entry), "messages")) if isinstance(entry, dict) else []:
            text_ = text(message.get("message"))
            yield Finding(relative(path), text(message.get("identifier"), shape(text_)), number(message.get("line")), text_)


def rubocop(report: str) -> Iterator[Finding]:
    document = cast("Json", json.loads(report))
    for entry in objects(document.get("files")):
        for offense in objects(entry.get("offenses")):
            yield Finding(
                relative(text(entry.get("path"))),
                text(offense.get("cop_name"), "unnamed"),
                number(field(offense, "location", "start_line")),
                text(offense.get("message")),
            )


def credo(report: str) -> Iterator[Finding]:
    document = cast("Json", json.loads(report))
    for issue in objects(document.get("issues")):
        yield Finding(
            relative(text(issue.get("filename"))),
            text(issue.get("check"), "unnamed"),
            number(issue.get("line_no")),
            text(issue.get("message")),
        )


PARSERS: dict[str, Callable[[str], Iterator[Finding]]] = {
    "sarif": sarif,
    "pyright": pyright,
    "eslint": eslint,
    "tsc": tsc,
    "lines": lines,
    "cargo": cargo,
    "msbuild": msbuild,
    "compiler": compiler,
    "elixir": elixir,
    "phpstan": phpstan,
    "rubocop": rubocop,
    "credo": credo,
}


def git(*arguments: str) -> str:
    return subprocess.run(["git", *arguments], capture_output=True, text=True, check=True).stdout


def base() -> str:
    return subprocess.run(["scripts/diff-base"], capture_output=True, text=True, check=True).stdout.strip()


def changed_files(since: str) -> list[str]:
    tracked = git("diff", "--name-only", "--diff-filter=ACMR", since, "--").splitlines()
    untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
    return sorted({path for path in tracked + untracked if Path(path).is_file() and not matches(path, list(GUARD_PATHS))})


def touched_lines(since: str) -> dict[str, frozenset[int] | None]:
    added: dict[str, set[int]] = {}
    current: set[int] | None = None
    for line in git("diff", "-U0", "-M", "--no-color", "--no-ext-diff", since, "--").splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            current = added.setdefault(target[2:], set()) if target.startswith("b/") else None
            continue
        hunk = HUNK.match(line)
        if hunk is not None and current is not None:
            start = int(hunk.group(1))
            length = 1 if hunk.group(2) is None else int(hunk.group(2))
            current.update(range(start, start + length))
    touched: dict[str, frozenset[int] | None] = {path: frozenset(rows) for path, rows in added.items()}
    for path in git("ls-files", "--others", "--exclude-standard").splitlines():
        touched[path] = None
    return touched


def on_touched_line(finding: Finding, touched: dict[str, frozenset[int] | None]) -> bool:
    if finding.path not in touched:
        return False
    rows = touched[finding.path]
    return rows is None or finding.line in rows


def shell(command: str) -> subprocess.CompletedProcess[str]:
    print(f"$ {command}", flush=True)
    return subprocess.run(["bash", "-c", command], capture_output=True, text=True, check=False)


def collect(check: Json) -> list[Finding]:
    report = Path(text(check.get("report")))
    report.parent.mkdir(parents=True, exist_ok=True)
    report.unlink(missing_ok=True)
    name = text(check.get("name"))
    result = shell(text(check.get("run")))
    if not report.is_file():
        sys.stderr.write(result.stdout + result.stderr)
        raise BrokenCheckError(name, f"the command wrote no report to {report}")
    content = TERMINAL_CODES.sub("", report.read_text())
    if not content.strip() and result.returncode != 0 and result.stderr.strip():
        sys.stderr.write(result.stderr[-4000:])
        raise BrokenCheckError(name, f"the command failed with exit code {result.returncode} and an empty report")
    try:
        return list(PARSERS[text(check.get("format"))](content))
    except (json.JSONDecodeError, ValueError) as error:
        sys.stderr.write(result.stderr[-4000:])
        raise BrokenCheckError(name, f"{report} is not valid JSON ({error.msg})") from error


def counts(findings: list[Finding]) -> dict[str, int]:
    return dict(sorted(Counter(f"{finding.path}::{finding.rule}" for finding in findings).items()))


def baseline_path(check: Json) -> Path:
    return BASELINES / f"{text(check.get('name'))}.json"


def ratchet(check: Json, findings: list[Finding], touched: dict[str, frozenset[int] | None] | None = None) -> bool:
    name = text(check.get("name"))
    recorded = cast("dict[str, int]", json.loads(baseline_path(check).read_text())) if baseline_path(check).is_file() else {}
    current = counts(findings)
    grown = [key for key, amount in current.items() if amount > recorded.get(key, 0)]
    shrunk = sum(amount - current.get(key, 0) for key, amount in recorded.items() if current.get(key, 0) < amount)
    for key in grown:
        path, rule = key.split("::", 1)
        print(f"{name}: {path} has {current[key]} [{rule}] findings; the baseline allows {recorded.get(key, 0)}")
        matching = [f for f in findings if f.path == path and f.rule == rule]
        fresh = [f for f in matching if touched is not None and on_touched_line(f, touched)]
        if fresh:
            print("  on lines this change touches:")
            print("\n".join("  " + f.render() for f in fresh))
            rest = [f for f in matching if f not in fresh]
            if rest:
                print("  elsewhere in the file:")
                print("\n".join("  " + f.render() for f in rest))
        else:
            print("\n".join(f.render() for f in matching))
    if shrunk:
        print(f"{name}: {shrunk} recorded findings are fixed; a human can lock that in with scripts/rebaseline")
    if not grown:
        print(f"{name}: no new findings ({len(findings)} recorded in the baseline remain)")
    return not grown


def matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(Path(path).name, pattern) for pattern in patterns)


def reformat(rule: Json, path: str, content: bytes) -> bytes | None:
    command = text(rule.get("run")).replace("{path}", shlex.quote(path))
    result = subprocess.run(["bash", "-c", command], input=content, capture_output=True, check=False)
    return result.stdout if result.returncode == 0 else None


def tracked_before(since: str, path: str) -> bytes | None:
    result = subprocess.run(["git", "show", f"{since}:{path}"], capture_output=True, check=False)
    return result.stdout if result.returncode == 0 else None


def formatted(rule: Json, since: str) -> bool:
    patterns = [text(pattern) for pattern in cast("list[object]", rule.get("glob", []))]
    regressions: list[str] = []
    for path in (path for path in changed_files(since) if matches(path, patterns)):
        content = Path(path).read_bytes()
        if reformat(rule, path, content) in {content, None}:
            continue
        before = tracked_before(since, path)
        if before is None:
            regressions.append(f"  {path}: new file is not formatted")
        elif reformat(rule, path, before) == before:
            regressions.append(f"  {path}: was formatted before this change and is not now")
    if regressions:
        print(f"{rule.get('name')}: run the formatter on these files")
        print("\n".join(regressions))
    return not regressions


def tested(tests: Json, since: str) -> bool:
    result = shell(text(tests.get("run")))
    sys.stdout.write(result.stdout[-4000:])
    if result.returncode != 0:
        sys.stderr.write(result.stderr[-4000:])
        print("tests: failed")
        return False
    pattern = text(tests.get("coverage"))
    if not pattern:
        return True
    reports = sorted(path.as_posix() for path in Path().glob(pattern) if path.is_file())
    if not reports:
        print(f"coverage: the tests wrote no report matching {pattern}")
        return False
    roots = sorted(
        {
            root
            for item in cast("list[object]", tests.get("src_roots", []))
            for root in (path.as_posix() for path in Path().glob(text(item)))
            if Path(root).is_dir()
        }
    )
    command = ["uv", "run", "--quiet", "--no-project", "--with", DIFF_COVER, "diff-cover", *reports]
    command += ["--compare-branch", since, "--fail-under", "100", "--include-untracked"]
    command += ["--exclude", *GUARD_PATHS]
    if roots:
        command += ["--src-roots", *roots]
    print(f"$ {shlex.join(command)}", flush=True)
    covered = subprocess.run(command, check=False)
    if covered.returncode != 0:
        print("coverage: every changed line must be covered by a test")
    return covered.returncode == 0


def configuration() -> Json:
    return cast("Json", json.loads(CONFIG.read_text()))


def check() -> int:
    config = configuration()
    since = base()
    results = [formatted(rule, since) for rule in objects(config.get("format"))]
    touched = touched_lines(since)
    results += [ratchet(item, collect(item), touched) for item in objects(config.get("checks"))]
    tests = config.get("tests")
    if isinstance(tests, dict):
        results.append(tested(cast("Json", tests), since))
    return 0 if all(results) else 1


def rebaseline() -> int:
    BASELINES.mkdir(parents=True, exist_ok=True)
    for item in objects(configuration().get("checks")):
        findings = collect(item)
        _ = baseline_path(item).write_text(json.dumps(counts(findings), indent=2) + "\n")
        print(f"{item.get('name')}: recorded {len(findings)} findings in {baseline_path(item)}")
    return 0


def main(argv: list[str]) -> int:
    commands = {"check": check, "baseline": rebaseline}
    if len(argv) != 1 or argv[0] not in commands:
        sys.stderr.write("usage: adopted.py check|baseline\n")
        return 2
    try:
        return commands[argv[0]]()
    except BrokenCheckError as failure:
        sys.stderr.write(f"{failure}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
