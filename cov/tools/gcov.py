# Copyright (c) 2026 Marcin Zdun
# This code is licensed under MIT license (see LICENSE for details)

import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

from cov.base import BaseTool, FileInfo, FunctionDecl, LineDecl, cd, recurse


class Base(BaseTool):

    def __init__(self, gcov: str, bin_dir: Path, int_dir: Path):
        self.gcov = Path(gcov)
        self.bin_dir = bin_dir
        self.int_dir = int_dir

    def exclude(self):
        return ["gcc"]

    def preprocess(self):
        gcno_dirs: dict[Path, list[str]] = {}
        bin_dir = self.bin_dir.absolute()
        for gcno in recurse(bin_dir, ".gcno"):
            dirname = gcno.parent
            filename = gcno.name
            if dirname not in gcno_dirs:
                gcno_dirs[dirname] = []
            gcno_dirs[dirname].append(filename)

        for dirname in gcno_dirs:
            int_dir = self.int_dir / str(dirname.relative_to(self.bin_dir)).replace(
                os.sep, "#"
            )

            int_dir.mkdir(parents=True, exist_ok=True)
            files = [str(dirname / filename) for filename in gcno_dirs[dirname]]

            with cd(int_dir):
                p = subprocess.Popen(
                    [str(self.gcov), "-l", "-b", "-c", "-i", "-p", "-o", str(dirname)]
                    + files,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                _, err = p.communicate()
                if p.returncode:
                    print(err, file=sys.stderr)
                    print("error:", p.returncode, file=sys.stderr)
                    sys.exit(1)


class GCOV8(Base):
    def ext(self):
        return ".gcov"

    def stats(self, intermediate_file: str | Path):
        result: dict[Path, FileInfo] = {}
        filename: Path | None = None
        file: FileInfo | None = None

        with open(intermediate_file) as src:
            for line in src:
                split = line.split(":", 1)
                if len(split) < 2:
                    continue
                if split[0] == "file":
                    if file and filename:
                        result[filename] = file
                    filename = Path(split[1].strip())
                    if not filename.is_absolute():
                        filename = (self.bin_dir / filename).resolve()
                    file = FileInfo()
                    continue

                if split[0] == "function":
                    start, stop, count, name = split[1].split(",")
                    if file:
                        file.functions.append(
                            FunctionDecl(
                                int(start), int(stop), 0, 0, int(count), name.strip()
                            )
                        )
                        print(file.functions[-1])
                    continue

                if split[0] == "lcount":
                    line, count, has_unexecuted = split[1].split(",")
                    if file:
                        file.lines.append(
                            LineDecl(int(line), int(count), int(has_unexecuted) != 0)
                        )
                    continue

            if file and filename:
                result[filename] = file
        return result


class JSON1(Base):
    def ext(self):
        return ".gcov.json.gz"

    def stats(self, intermediate_file: str | Path):
        result: dict[Path, FileInfo] = {}
        with gzip.open(intermediate_file, "rb") as compressed:
            data = json.loads(compressed.read().decode("ascii"))["files"]
            for coverage in data:
                filename = Path(coverage["file"])
                if not filename.is_absolute():
                    filename = (self.bin_dir / filename).resolve()
                file = FileInfo()

                functions = [
                    FunctionDecl(
                        fun.get("start_line"),
                        fun.get("end_line"),
                        fun.get("start_column"),
                        fun.get("end_column"),
                        fun.get("execution_count"),
                        fun.get("name"),
                        fun.get("demangled_name"),
                    )
                    for fun in coverage["functions"]
                ]

                lines = [
                    LineDecl(
                        line["line_number"], line["count"], line["unexecuted_block"]
                    )
                    for line in coverage["lines"]
                ]

                result[filename] = FileInfo(functions, lines)
        return result
