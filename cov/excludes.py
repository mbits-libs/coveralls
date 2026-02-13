# Copyright (c) 2026 Marcin Zdun
# This code is licensed under MIT license (see LICENSE for details)

import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

MATCHES_TAGS = re.compile(r"(?:G|L|GR)COV_EXCL_(?:START|LINE)\[([^\]]+)\]")
MATCHES_LINE = re.compile(r"(?:G|L|GR)COV_EXCL_LINE")
MATCHES_START = re.compile(r"(?:G|L|GR)COV_EXCL_START")
MATCHES_STOP = re.compile(r"(?:G|L|GR)COV_EXCL_STOP")
MATCHES_END = re.compile(r"(?:G|L|GR)COV_EXCL_END")


def matches_tags(line: str):
    return MATCHES_TAGS.search(line)


def matches_line(line: str):
    return MATCHES_LINE.search(line)


def matches_start(line: str):
    return MATCHES_START.search(line)


def matches_stop(line: str):
    return MATCHES_STOP.search(line)


def matches_end(line: str):
    return MATCHES_END.search(line)


@dataclass
class file_ref:
    line_no: int = field(default=0)
    column: int = field(default=0)
    match: str = field(default="")


@dataclass(order=True)
class excl_block:
    start: int
    end: int


class line_kind(Enum):
    unimportant = None
    visited = True
    unvisited = False


@dataclass
class excludes:
    path: str
    markers: list[str]
    inside_exclude: bool = field(default=False)
    last_start: file_ref = field(default_factory=file_ref)
    single_lines: list[int] = field(default_factory=list)
    result: list[excl_block] = field(default_factory=list)
    empties: set[int] = field(default_factory=set)

    def __post_init__(self):
        self.markers = [marker.lower() for marker in self.markers]

    def on_line(self, line_no: int, text: str):
        if not text.strip():
            self.empties.add(line_no)
            return

        has_tags = matches_start(text)
        if has_tags:
            markers = has_tags.group(1).lower().split(",")
            has_any_marker = False
            for marker in markers:
                marker = marker.strip()
                if marker in self.markers:
                    has_any_marker = True
                    break

                if has_any_marker:
                    break

            if not has_any_marker:
                return

        switch_off = False
        is_matching_line = False

        end_match = matches_end(text)
        start_match = matches_start(text)

        if matches_stop(text):
            switch_off = True
        elif end_match:
            if self.inside_exclude:
                end = end_match.group(0)
                self.warn(
                    line_no,
                    end_match.start(),
                    f"found {end}; did you mean {end[:-len('_END')]}_STOP?",
                )
        elif start_match:
            if self.inside_exclude:
                self.warn(
                    line_no,
                    start_match.start(0),
                    f"double start: found {start_match.group(0)}",
                )
                self.note(
                    self.last_start.line_no,
                    self.last_start.column,
                    "see previous start",
                )
                self.include_back(self.last_start.line_no)
            self.last_start = file_ref(
                line_no, start_match.start(0), start_match.group(0)
            )
            self.inside_exclude = True
        elif matches_line(text):
            is_matching_line = True
            self.single_lines.append(line_no)

        if self.inside_exclude or is_matching_line:
            self.exclude(line_no)

        if switch_off:
            self.inside_exclude = False

    def after_lines(self):
        if not self.inside_exclude:
            return

        match = self.last_start.match
        self.warn(
            self.last_start.line_no,
            self.last_start.column,
            f"{match} not matched with {match[:-len("_START")]}_STOP",
        )
        self.include_back(self.last_start.line_no)

    def exclude(self, line_no: int):
        if self.result and self.result[-1].end + 1 == line_no:
            self.result[-1].end = line_no
            return

        self.result.append(excl_block(line_no, line_no))
        self.single_lines = []

    def include_back(self, line_no: int):
        while self.result and self.result[-1].start >= line_no:
            self.result.pop()

        for line in self.single_lines:
            self.exclude(line)

    def warn(self, line_no: int, column: int, message: str):
        self.message(line_no, column, "\033[1;35mwarning", message)

    def note(self, line_no: int, column: int, message: str):
        self.message(line_no, column, "\033[1;36mnote", message)

    def message(self, line_no: int, column: int, tag: str, message: str):
        print(
            f"\033[1;37m{self.path}:{line_no}:{column}:\033[m {tag}:\033[m {message}\n",
            file=sys.stderr,
        )

    @staticmethod
    def find_excl_blocks(markers: list[str], file_name: str, src_dir: Path):
        full_path = src_dir / file_name
        builder = excludes(path=str(full_path), markers=markers)
        try:
            for line_no, text in enumerate(full_path.read_text().split("\n")):
                builder.on_line(line_no, text)

            builder.after_lines()
        except FileNotFoundError:
            pass

        return (builder.result, builder.empties)


def _clean_functions(lines: dict[int, int], functions: dict[str, dict]):
    cleaned: dict[str, dict] = {}
    counter = 0
    fn_set = {line + 1 for line, _ in []}
    for key, fn in functions.items():
        start_line = fn.get("start_line", 0)
        end_line = fn.get("end_line", start_line)
        excluded = True
        for line in range(start_line, end_line + 1):
            if line in lines and line not in fn_set:
                excluded = False
                break
        if not excluded:
            cleaned[key] = fn
        else:
            counter += 1
    return cleaned, counter


@dataclass
class stats:
    relevant: int = field(default=0)
    covered: int = field(default=0)
    excluded: int = field(default=0)

    @property
    def percent(self):
        return (
            int(self.covered * 10000 / self.relevant + 0.5) / 100
            if self.relevant
            else 0
        )

    def __str__(self):
        excl = ""
        if self.excluded:
            excl = f" excluded: {self.excluded}"
        return f"{self.covered}/{self.relevant} ({self.percent}%){excl}"


@dataclass
class coverage_stats:
    lines: stats = field(default_factory=stats)
    functions: stats = field(default_factory=stats)
    patches: list = field(default_factory=list)

    def erase_lines(
        self,
        lines: dict[int, int],
        excluded_blocks: list[excl_block],
        empties: set[int],
    ):
        for exclude in excluded_blocks:
            for line_no in range(exclude.start, exclude.end + 1):
                self._erase_line(lines, line_no, hard_remove=True)

        for line_no in empties:
            self._erase_line(lines, line_no, hard_remove=False)

    def _erase_line(self, lines: dict[int, int], line_no: int, *, hard_remove: bool):
        if line_no in lines and (hard_remove or lines[line_no] == 0):
            self.lines.excluded += 1
            del lines[line_no]

    def clean_file_report(
        self,
        name: str,
        digest: str,
        line_count: int,
        lines: dict[int, int],
        functions: dict[str, dict],
    ):
        functions, excluded_functions = _clean_functions(lines, functions)
        self.functions.excluded += excluded_functions

        self.functions.relevant += len(functions)
        for fn in functions.values():
            count = fn.get("count")
            if count:
                self.functions.covered += 1

        size = max(line_count, max(lines.keys())) if len(lines) else 0
        cvg: list[int | None] = [None] * size

        self.lines.relevant += len(lines)
        for line in lines:
            val = lines[line]
            if val:
                self.lines.covered += 1
            cvg[line - 1] = val

        return {
            "name": name,
            "source_digest": digest,
            "coverage": cvg,
            "functions": [functions[key] for key in sorted(functions.keys())],
        }

    def report(self):
        print(f"-- Line coverage:      {self.lines}")
        print(f"-- Function coverage:  {self.functions}")
