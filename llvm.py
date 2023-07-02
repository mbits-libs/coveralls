import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Tuple


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
    execution_count: Optional[int] = None


def _is_start_of_region(segment: CoverageSegment):
    return not segment.is_gap and segment.has_count and segment.is_entry


def _line_coverage_stats(
    line_segments: List[CoverageSegment],
    wrapped_segment: Optional[CoverageSegment],
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
            result.execution_count = max(result.execution_count, segment.count)

    return result


def _line_coverage_iterator(coverage: List[CoverageSegment]):
    wrapped: Optional[CoverageSegment] = None
    line: int = coverage[0].line if len(coverage) else 0
    segments: List[CoverageSegment] = []
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


class LLVM:
    def __init__(self, cov_tool: str, merge_tool: str, bin_dir: str, int_dir: str):
        self.cov_tool = cov_tool
        self.merge_tool = merge_tool
        self.bin_dir = bin_dir
        self.int_dir = int_dir

    def ext(self):
        return ".profjson"

    def _export(self, profile_data_file: str, exe: str):
        p = subprocess.run(
            [
                self.cov_tool,
                "export",
                "-format",
                "text",
                "-skip-functions",
                "-skip-expansions",
                "-instr-profile",
                profile_data_file,
                exe,
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

    def preprocess(self, recurse: Callable[[str, str], Iterable[str]]):
        raw = list(recurse(os.path.abspath(self.bin_dir), ".profraw"))
        if not len(raw):
            return
        profile_data_file = f"{self.int_dir}/coverage.profdata"
        args = [
            self.merge_tool,
            "merge",
            "-sparse",
            *raw,
            "-o",
            profile_data_file,
        ]
        p = subprocess.run(
            args, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if p.returncode:
            print(p.stderr, file=sys.stderr)
            print("error:", p.returncode, file=sys.stderr)
            sys.exit(1)

        ext = ".exe" if os.name == "nt" else ""
        suffix = f"-test{ext}"
        execs: List[str] = []
        bin_dir = os.path.join(self.bin_dir, "bin")
        for root, dirnames, filenames in os.walk(bin_dir):
            dirnames[:] = []
            for filename in filenames:
                if filename == f"cov{ext}" or filename[-len(suffix) :] == suffix:
                    execs.append(os.path.join(root, filename))
        for exe in execs:
            local = os.path.join(
                self.int_dir, os.path.relpath(exe, self.bin_dir) + ".profjson"
            )
            os.makedirs(os.path.dirname(local), exist_ok=True)
            text = self._export(profile_data_file, exe)
            with open(local, "wb") as out:
                out.write(text)

    def stats(self, profile_json_file: str):
        with open(profile_json_file, encoding="UTF-8") as data:
            coverage_root = json.load(data)
        coverage = coverage_root.get("data", [])
        version = int(coverage_root.get("version", "0.0.0").split(".", 1)[0])
        if version != 2:
            return None

        result = {}
        for export in coverage:
            for file in export.get("files", []):
                filename = file.get("filename")
                if filename is None:
                    continue

                lines: List[Tuple[int, int, None]] = []
                segments = [
                    CoverageSegment(line, column, count, has_count, is_entry, is_gap)
                    for line, column, count, has_count, is_entry, is_gap in file.get(
                        "segments", []
                    )
                ]
                for stats in _line_coverage_iterator(segments):
                    if stats.execution_count is None:
                        continue
                    lines.append((stats.line, stats.execution_count, None))

                result[filename] = [[], lines]

        return result
