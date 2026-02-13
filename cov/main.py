# Copyright (c) 2026 Marcin Zdun
# This code is licensed under MIT license (see LICENSE for details)

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any, cast

from cov import base
from cov.base import BaseTool, recurse
from cov.ci import get_base_header, get_report_header
from cov.excludes import coverage_stats, excludes
from cov.git import get_git_header
from cov.tools import guess_tool


def file_md5(path: str | Path):
    m = hashlib.md5()
    lines = 0
    with open(path, "rb") as f:
        for line in f:
            if line.endswith(b"\r\n"):
                line = line[:-2] + b"\n"
            m.update(line)
            lines += 1
    return (m.hexdigest(), lines)


def parse_args():
    parser = argparse.ArgumentParser(description="Gather GCOV data for Coveralls")
    handler = parser.add_mutually_exclusive_group(required=True)
    handler.add_argument(
        "--cobertura",
        help="look for .xml cobertura files instead of .gcno gcov files",
        action="store_true",
    )
    handler.add_argument(
        "--gcov", metavar="PATH", help="path to the gcov/llvm-cov program"
    )
    parser.add_argument(
        "--merge", metavar="PATH", help="path to the llvm-profdata program"
    )
    parser.add_argument(
        "--target",
        metavar="FILENAME",
        required=True,
        help="name of the tested application",
    )
    parser.add_argument(
        "--src_dir", metavar="DIR", required=True, help="directory for source files"
    )
    parser.add_argument(
        "--bin_dir", metavar="DIR", required=True, help="directory for generated files"
    )
    parser.add_argument(
        "--int_dir",
        metavar="DIR",
        required=True,
        help="directory for temporary gcov files",
    )
    parser.add_argument(
        "--dirs",
        metavar="DIR:DIR:...",
        required=True,
        help="directory filters for relevant sources, separated with':'",
    )
    parser.add_argument(
        "--out", metavar="JSON", required=True, help="output JSON file for Coveralls"
    )
    parser.add_argument(
        "--debug",
        required=False,
        help="prints JSON, if present",
        action="store_true",
        default=False,
    )

    return parser.parse_args()


def props(build_dir: Path):
    path = build_dir / "report_answers.txt"
    try:
        text = path.read_text("utf-8")
        lines = [line[2:] for line in text.split("\n") if line.startswith("-p")]

        result = {}
        for line in lines:
            name, value = line.split("=", 2)

            try:
                num = int(value)
                result[name] = num
                continue
            except ValueError:
                # Not an integer; fall through to handle booleans and strings below.
                pass

            if value.lower() in ["on", "true", "yes"]:
                result[name] = True
                continue

            if value.lower() in ["off", "false", "no"]:
                result[name] = False
                continue

            if value.startswith("'") and value.endswith("'"):
                result[name] = value[1:-1]
                continue

            result[name] = value

        return result

    except FileNotFoundError:
        return {}


def build_job_flag_name(props: dict[str, Any]) -> str:
    if props.get("compiler") == "msvc" and props.get("compiler.version"):
        del props["compiler.version"]
    if props.get("os.version") is None:
        props["os.version"] = "latest"

    props["flag_name"] = ""
    key_change = [
        ("os", "os.version", "-{}"),
        ("compiler", "compiler.version", "-{}"),
        ("flag_name", "build_type", "{}"),
        ("flag_name", "os", ", {}"),
        ("flag_name", "compiler", ", {}"),
        ("flag_name", "sanitizer", ", sanitizer"),
    ]

    for parent_key, child_key, fmt in key_change:
        parent = props.get(parent_key)
        child = props.get(child_key)
        if parent is None or child is None:
            continue
        if "{}" not in fmt and isinstance(child, bool):
            child = fmt
        else:
            child = fmt.format(child)
        props[parent_key] = f"{parent}{child}"
        del props[child_key]

    return props["flag_name"]


def gather_coverage(
    cov_tool: BaseTool,
    src_dir: Path,
    int_dir: Path,
    dirs: list[Path],
    excl_stats: coverage_stats,
):
    result: list[dict] = []
    try:
        EXCL_LIST = {"win32": ["win32"], "linux": ["linux", "posix"]}[sys.platform]
    except KeyError:
        EXCL_LIST = []

    EXCL_LIST.extend(cov_tool.exclude())

    cov_tool.preprocess()

    coverage: dict[str, list[dict]] = {}
    maps: dict[str, Path] = {}
    for intermediate_file in recurse(int_dir, cov_tool.ext()):
        data = cov_tool.stats(intermediate_file)
        if not data:
            continue
        for src, info in data.items():
            if not src.is_relative_to(src_dir):
                continue
            name = src.relative_to(src_dir)
            relevant = False
            for dirname in dirs:
                if name.is_relative_to(dirname):
                    relevant = True
                    break
            if not relevant:
                continue

            info.append_as(name.as_posix(), src, coverage=coverage, paths=maps)

    for src in sorted(coverage.keys()):
        lines, functions = coverage[src]
        digest, line_count = file_md5(maps[src])
        excluded_blocks, empties = excludes.find_excl_blocks(EXCL_LIST, src, src_dir)
        excl_stats.erase_lines(lines, excluded_blocks, empties)
        result.append(
            excl_stats.clean_file_report(src, digest, line_count, lines, functions)
        )

    return result


def tool():
    base.GIT_EXECUTABLE = shutil.which("git") or "git"

    args = parse_args()
    dirs = [Path(dirname) for dirname in args.dirs.split(":")]

    bin_dir = Path(args.bin_dir)

    flag_name = build_job_flag_name(props(bin_dir))
    JSON = get_report_header(flag_name, parallel=True)
    get_git_header(JSON, args.src_dir)
    if args.debug:
        from pprint import pprint

        pprint(JSON)

    cov_tool = guess_tool(
        args.gcov,
        args.cobertura,
        args.merge,
        args.target,
        bin_dir,
        Path(args.int_dir),
    )

    src_dir = Path(args.src_dir).absolute()
    excl_stats = coverage_stats()

    JSON["source_files"][:] = gather_coverage(
        cov_tool,
        src_dir=src_dir,
        int_dir=Path(args.int_dir),
        dirs=dirs,
        excl_stats=excl_stats,
    )

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"-- Writing {out.relative_to(args.src_dir, walk_up=True)}")
    with out.open("wb") as j:
        text = json.dumps(JSON, ensure_ascii=False, indent=2)
        if not text.endswith("\n"):
            text += "\n"
        j.write(text.encode())

    excl_stats.report()


def simple():
    base.GIT_EXECUTABLE = shutil.which("git") or "git"

    args = parse_args()
    dirs = [Path(dirname) for dirname in args.dirs.split(":")]

    bin_dir = Path(args.bin_dir)

    print("-- Building simplified report for later merge")

    JSON = get_base_header()
    get_git_header(JSON, args.src_dir, only_hash=True)
    if args.debug:
        from pprint import pprint

        pprint(JSON)

    cov_tool = guess_tool(
        args.gcov,
        args.cobertura,
        args.merge,
        args.target,
        bin_dir,
        Path(args.int_dir),
    )

    src_dir = Path(args.src_dir).absolute()
    excl_stats = coverage_stats()

    JSON["source_files"] = gather_coverage(
        cov_tool,
        src_dir=src_dir,
        int_dir=Path(args.int_dir),
        dirs=dirs,
        excl_stats=excl_stats,
    )

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"-- Writing {out.relative_to(src_dir.resolve(), walk_up=True)}")
    with out.open("wb") as j:
        text = json.dumps(JSON, ensure_ascii=False, indent=2)
        if not text.endswith("\n"):
            text += "\n"
        j.write(text.encode())

    excl_stats.report()
