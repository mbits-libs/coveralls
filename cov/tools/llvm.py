# Copyright (c) 2026 Marcin Zdun
# This code is licensed under MIT license (see LICENSE for details)

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from cov.base import BaseTool, FileInfo, FunctionDecl, LineDecl, recurse


@dataclass
class CoverageSegment:
    line: int
    column: int
    count: int
    has_count: bool
    is_entry: bool
    is_gap: bool


@dataclass
class LCS:
    line: int
    execution_count: int | None = None


def _is_start_of_region(segment: CoverageSegment):
    return not segment.is_gap and segment.has_count and segment.is_entry


def _line_coverage_stats(
    line_segments: list[CoverageSegment],
    wrapped_segment: CoverageSegment | None,
    line: int,
):
    result = LCS(line)
    min_region_count = 0
    for segment in line_segments:
        if min_region_count > 1:
            break
        if _is_start_of_region(segment):
            min_region_count += 1

    start_of_skipped_region = (
        len(line_segments) > 0
        and line_segments[0].has_count
        and line_segments[0].is_entry
    )

    mapped = not start_of_skipped_region and (
        (wrapped_segment is not None and wrapped_segment.has_count)
        or (min_region_count > 0)
    )

    if not mapped:
        return result

    if wrapped_segment is not None:
        result.execution_count = wrapped_segment.count

    for segment in line_segments:
        if _is_start_of_region(segment):
            result.execution_count = max(
                cast(int, result.execution_count), segment.count
            )

    return result


def _line_coverage_iterator(coverage: list[CoverageSegment]):
    wrapped: CoverageSegment | None = None
    line: int = coverage[0].line if len(coverage) else 0
    segments: list[CoverageSegment] = []
    end_index = len(coverage)
    index = 0

    while index < end_index:
        if len(segments):
            wrapped = segments[-1]
        segments = []
        while index < end_index and coverage[index].line == line:
            segments.append(coverage[index])
            index += 1

        yield _line_coverage_stats(segments, wrapped, line)
        line += 1


@dataclass(order=True)
class TextPos:
    line: int = 0
    col: int = 0


@dataclass(order=True)
class RegionRef:
    start: TextPos
    end: TextPos


@dataclass
class FileRef:
    valid: bool = False
    start: TextPos = field(default_factory=TextPos)
    end: TextPos = field(default_factory=TextPos)


def _function_encompassing_region(regions: list[list[int]]):
    result: RegionRef | None = None

    for region in regions:
        if len(region) < 8:
            continue
        if region[7] != 0 or region[5] != 0:
            continue
        start_line, start_col, end_line, end_col = region[:4]
        start = TextPos(start_line, start_col)
        end = TextPos(end_line, end_col)

        if result is None:
            result = RegionRef(start, end)
            continue

        if result.start > start:
            result.start = start
        if result.end < end:
            result.end = end

    if result is not None:
        return FileRef(True, result.start, result.end)

    return FileRef()


def is_script(path):
    with open(path, "rb") as f:
        maybe_hash_bang = f.read(2)
        return maybe_hash_bang == b"#!"


class LLVM(BaseTool):
    def __init__(
        self, cov_tool: str, merge_tool: str, target: str, bin_dir: Path, int_dir: Path
    ):
        self.cov_tool = Path(cov_tool)
        self.merge_tool = Path(merge_tool)
        self.target = target
        self.bin_dir = bin_dir
        self.int_dir = int_dir

    def exclude(self):
        return ["clang", "llvm"]

    def ext(self):
        return ".profjson"

    def _export(self, profile_data_file: Path, exe: Path):
        p = subprocess.run(
            [
                self.cov_tool,
                "export",
                "-format",
                "text",
                # "-skip-functions",
                "-skip-expansions",
                "-instr-profile",
                str(profile_data_file),
                str(exe),
            ],
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if p.returncode:
            print(p.stderr, file=sys.stderr)
            print("error:", p.returncode, file=sys.stderr)
            sys.exit(1)
        return p.stdout

    def preprocess(self):
        raw = list(recurse(self.bin_dir.absolute(), ".profraw"))
        if not raw:
            return
        profile_data_file = self.int_dir / "coverage.profdata"
        p = subprocess.run(
            [
                str(self.merge_tool),
                "merge",
                "-sparse",
                *raw,
                "-o",
                str(profile_data_file),
            ],
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if p.returncode:
            print(p.stderr, file=sys.stderr)
            print("error:", p.returncode, file=sys.stderr)
            sys.exit(1)

        ext = ".exe" if os.name == "nt" else ""
        re_ext = r"\.exe" if os.name == "nt" else ""
        versioned_target = f"^{re.escape(self.target)}(-[0-9.]+)?{re_ext}$"
        suffix = f"-test{ext}"
        execs: list[Path] = []

        bin_dir = self.bin_dir / "bin"

        for root, dirnames, filenames in bin_dir.walk():
            dirnames[:] = []
            for filename in filenames:
                if re.match(versioned_target, filename) or filename.endswith(suffix):
                    execs.append(root / filename)

        for exe in execs:
            local = self.int_dir / (str(exe.relative_to(self.bin_dir)) + ".profjson")
            local.parent.mkdir(parents=True, exist_ok=True)
            blob = self._export(profile_data_file, exe)
            with open(local, "wb") as out:
                out.write(blob)

    def stats(self, intermediate_file: str | Path):
        with open(intermediate_file, encoding="UTF-8") as data:
            coverage_root = cast(dict, json.load(data))
        coverage = coverage_root.get("data", [])
        version = int(coverage_root.get("version", "0.0.0").split(".", 1)[0])
        if version != 2:
            return None

        result: dict[Path, FileInfo] = {}
        for export in coverage:
            for file in export.get("files", []):
                filename = cast(str | None, file.get("filename"))
                if filename is None:
                    continue

                lines: list[LineDecl] = []
                segments = [
                    CoverageSegment(line, column, count, has_count, is_entry, is_gap)
                    for line, column, count, has_count, is_entry, is_gap in file.get(
                        "segments", []
                    )
                ]
                for stats in _line_coverage_iterator(segments):
                    if stats.execution_count is None:
                        continue
                    lines.append(LineDecl(stats.line, stats.execution_count, None))

                result[Path(filename)] = FileInfo([], lines)

        for export in coverage:
            for function in export.get("functions", []):
                count = cast(int | None, function.get("count"))
                name = cast(str | None, function.get("name"))
                filenames = cast(list[str], function.get("filenames", []))
                if count is None or name is None:
                    continue

                ref = _function_encompassing_region(function.get("regions", []))

                if not ref.valid or not filenames:
                    continue

                filename = Path(filenames[0])

                func_decl = FunctionDecl(
                    ref.start.line,
                    ref.end.line,
                    ref.start.col,
                    ref.end.col,
                    count,
                    name,
                )

                try:
                    result[filename].functions.append(func_decl)
                except KeyError:
                    result[filename] = FileInfo([func_decl], [])

        return result
