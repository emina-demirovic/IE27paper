"""Statically analyze a Python task from a Git commit and its declared inputs."""

import argparse
import ast
import json
import math
import stat
import subprocess
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath


TRACKED_LIBRARIES = {"numpy", "scipy", "pandas", "sklearn", "gymnasium"}
MAX_NUMPY_HEADER_BYTES = 16 * 1024


def git_output(repository: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout


def extract_structure(tree: ast.AST) -> dict:
    node_counts = Counter()
    max_loop_depth = 0
    pending = [(tree, 0)]

    while pending:
        node, loop_depth = pending.pop()
        node_counts[type(node)] += 1

        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            loop_depth += 1
            max_loop_depth = max(max_loop_depth, loop_depth)

        pending.extend((child, loop_depth) for child in ast.iter_child_nodes(node))

    return {
        "nodeCount": sum(node_counts.values()),
        "forCount": node_counts[ast.For] + node_counts[ast.AsyncFor],
        "whileCount": node_counts[ast.While],
        "comprehensionCount": (
            node_counts[ast.ListComp] + node_counts[ast.SetComp] + node_counts[ast.DictComp]
        ),
        "generatorExpressionCount": node_counts[ast.GeneratorExp],
        "maxSyntacticLoopDepth": max_loop_depth,
        "callCount": node_counts[ast.Call],
    }


def direct_local_imports(tree: ast.AST, entry_point: PurePosixPath, tracked_paths: set) -> list:
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = PurePosixPath(*alias.name.split("."))
                modules.update((entry_point.parent / module, module))
        elif isinstance(node, ast.ImportFrom) and node.level <= len(entry_point.parents):
            base_paths = (
                (entry_point.parents[node.level - 1],)
                if node.level else (entry_point.parent, PurePosixPath("."))
            )
            for base in base_paths:
                package = base.joinpath(*(node.module or "").split("."))
                if node.module:
                    modules.add(package)
                modules.update(package / alias.name for alias in node.names if alias.name != "*")

    local_paths = set()
    for module in modules:
        for candidate in (module.parent / f"{module.name}.py", module / "__init__.py"):
            path = candidate.as_posix()
            if path in tracked_paths and path != entry_point.as_posix():
                local_paths.add(path)

    return sorted(local_paths)


def dotted_name(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return ""
    parts.append(node.id)
    return ".".join(reversed(parts))


def inspect_calls(tree: ast.AST) -> dict:
    imports = defaultdict(set)
    rebound = set()
    nodes = list(ast.walk(tree))

    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                imports[alias.asname or root].add(alias.name if alias.asname else root)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                prefix = "." * node.level + (node.module or "")
                target = f"{prefix}.{alias.name}" if node.module else prefix + alias.name
                imports[alias.asname or alias.name].add(target)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            rebound.add(node.id)
        elif isinstance(node, ast.arg):
            rebound.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler)):
            rebound.add(node.name)

    # Ignore aliases with competing definitions anywhere in this file.
    aliases = {
        name: next(iter(targets))
        for name, targets in imports.items()
        if len(targets) == 1 and name not in rebound
    }
    library_calls = Counter()
    dynamic_import_count = 0
    unresolved_call_count = 0
    range_calls = []

    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        name = dotted_name(node.func)
        head, separator, tail = name.partition(".")
        target = aliases.get(head, "") + separator + tail

        if target == "importlib.import_module" or (
            name == "__import__" and head not in imports and head not in rebound
        ):
            dynamic_import_count += 1

        if target.partition(".")[0] in TRACKED_LIBRARIES:
            library_calls[target] += 1
        elif head not in aliases:
            unresolved_call_count += 1

        if name == "range" and head not in imports and head not in rebound:
            range_calls.append({
                "line": node.lineno,
                "arguments": [ast.unparse(argument) for argument in node.args],
            })

    return {
        "libraries": sorted({
            target.split(".")[0]
            for targets in imports.values()
            for target in targets
            if target.split(".")[0] in TRACKED_LIBRARIES
        }),
        "libraryCallCounts": dict(sorted(library_calls.items())),
        "unresolvedCallCount": unresolved_call_count,
        "dynamicImportCount": dynamic_import_count,
        "rangeCalls": range_calls,
    }


def named_values(parser: argparse.ArgumentParser, items: list, option: str) -> dict:
    values = {}
    for item in items:
        name, separator, value = item.partition("=")
        if not separator or not name or name in values:
            parser.error(f"{option} requires unique NAME=VALUE entries")
        values[name] = value
    return values


def argument_value(value: str):
    try:
        parsed = json.loads(value)
    except ValueError:
        return value

    if isinstance(parsed, float) and not math.isfinite(parsed):
        return value
    return parsed if isinstance(parsed, (str, int, float, bool)) else value


def numpy_header(file) -> dict:
    prefix = file.read(8)
    versions = {
        b"\x01\x00": (2, "latin1"),
        b"\x02\x00": (4, "latin1"),
        b"\x03\x00": (4, "utf-8"),
    }
    if prefix[:6] != b"\x93NUMPY" or prefix[6:] not in versions:
        raise ValueError("unsupported NumPy file header")

    length_bytes, encoding = versions[prefix[6:]]
    length_data = file.read(length_bytes)
    length = int.from_bytes(length_data, "little")
    if len(length_data) != length_bytes or not 0 < length <= MAX_NUMPY_HEADER_BYTES:
        raise ValueError("invalid NumPy header length")

    payload = file.read(length)
    if len(payload) != length:
        raise ValueError("truncated NumPy header")

    header = ast.literal_eval(payload.decode(encoding).strip())
    if not isinstance(header, dict):
        raise ValueError("invalid NumPy header")
    shape = header.get("shape")
    descriptor = header.get("descr")
    if (
        not isinstance(shape, tuple)
        or any(type(size) is not int or size < 0 for size in shape)
        or not isinstance(descriptor, (str, list))
    ):
        raise ValueError("invalid NumPy shape or dtype descriptor")

    json.dumps(descriptor, allow_nan=False)
    return {"shape": list(shape), "dtypeDescriptor": descriptor}


def inspect_inputs(inputs: dict) -> tuple:
    metadata = {}
    unavailable = {}

    for name, filename in inputs.items():
        path = Path(filename)
        key = f"inputs.{name}"
        try:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                unavailable[key] = "not_a_regular_file"
                continue
        except FileNotFoundError:
            unavailable[key] = "file_not_found"
            continue
        except OSError:
            unavailable[key] = "file_not_readable"
            continue

        suffix = path.suffix.lower()
        metadata[name] = {"format": suffix.lstrip(".") or "unknown", "sizeBytes": info.st_size}
        if suffix == ".npy":
            try:
                with path.open("rb") as file:
                    metadata[name].update(numpy_header(file))
            except (OSError, ValueError, SyntaxError, TypeError, RecursionError):
                unavailable[f"{key}.arrayMetadata"] = "unreadable_or_unsupported_numpy_header"
        else:
            unavailable[f"{key}.arrayMetadata"] = "unsupported_format"

    return metadata, unavailable


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd(), help="Local Git repository")
    parser.add_argument("--commit", required=True, help="Git commit or ref to resolve")
    parser.add_argument("--entry-point", required=True, help="Repository-relative .py path")
    parser.add_argument("--arg", action="append", default=[], metavar="NAME=VALUE",
                        help="Task argument. JSON scalars are recognized. Repeat per argument.")
    parser.add_argument("--input", action="append", default=[], metavar="NAME=PATH",
                        help="Local input file, relative to the current directory if needed.")
    args = parser.parse_args()

    entry_point = PurePosixPath(args.entry_point)
    if entry_point.is_absolute() or ".." in entry_point.parts or entry_point.suffix != ".py":
        parser.error("--entry-point must be a repository-relative .py path")

    task_args = named_values(parser, args.arg, "--arg")
    inputs = named_values(parser, args.input, "--input")
    path = entry_point.as_posix()
    try:
        commit = git_output(
            args.repository, "rev-parse", "--verify", "--end-of-options", args.commit + "^{commit}"
        ).decode("ascii").strip()
        source = git_output(args.repository, "cat-file", "blob", f"{commit}:{path}")
        trees = {path: ast.parse(source, filename=path)}
        tracked_paths = set(
            git_output(args.repository, "ls-tree", "-r", "--name-only", "-z", commit)
            .decode("utf-8", errors="surrogateescape").split("\0")
        )
    except subprocess.CalledProcessError as error:
        parser.exit(1, error.stderr.decode(errors="replace"))
    except (OSError, SyntaxError, ValueError) as error:
        parser.exit(1, f"{error}\n")

    metadata, unavailable = inspect_inputs(inputs)
    for local_path in direct_local_imports(trees[path], entry_point, tracked_paths):
        try:
            source = git_output(args.repository, "cat-file", "blob", f"{commit}:{local_path}")
            trees[local_path] = ast.parse(source, filename=local_path)
        except (subprocess.CalledProcessError, OSError, SyntaxError, ValueError):
            unavailable[f"source.{local_path}"] = "cannot_parse_local_module"

    calls_by_file = {name: inspect_calls(tree) for name, tree in trees.items()}
    warnings = []
    if any(calls["dynamicImportCount"] for calls in calls_by_file.values()):
        warnings.append("dynamic_import_detected")
        unavailable["source.dynamicImportTargets"] = "not_resolved_statically"

    record = {
        "schemaVersion": 1,
        "task": {"gitCommit": commit, "entryPoint": path},
        "features": {
            "known": {
                "arguments": {name: argument_value(value) for name, value in task_args.items()},
                "inputs": metadata,
            },
            "derived": {
                "ast": {
                    "entryPoint": extract_structure(trees[path]),
                    "localModules": {
                        name: extract_structure(tree) for name, tree in trees.items() if name != path
                    },
                },
                "callsByFile": calls_by_file,
            },
            "unavailable": unavailable,
        },
        "coverage": {
            "importScope": "direct_local_candidates",
            "scannedFiles": list(trees),
            "warnings": warnings,
        },
    }
    print(json.dumps(record, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
