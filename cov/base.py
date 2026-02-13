import os
import subprocess
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

GIT_EXECUTABLE: str = ""


def run(*args):
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    return (out, err, p.returncode)


def output(*args):
    return run(*args)[0].strip().decode("utf-8")


def git_log_format(fmt):
    return output(GIT_EXECUTABLE, "log", "-1", "--pretty=format:%" + fmt)


def ENV(name: str):
    return os.environ.get(name)


def recurse(root: Path, ext: str) -> Iterable[Path]:
    for current, _, files in root.walk():
        for filename in files:
            path = current / filename
            if path.suffix == ext:
                yield path


@contextmanager
def cd(dirname: str | Path):
    dirname = Path(dirname).expanduser()
    current = Path().absolute()
    os.chdir(dirname)
    try:
        yield
    finally:
        os.chdir(current)


def mkdir_p(path: str | Path):
    Path(path).mkdir(parents=True, exist_ok=True)


@dataclass
class FunctionDecl:
    start_line: int | None
    end_line: int | None
    start_column: int | None
    end_column: int | None
    execution_count: int | None
    name: str | None
    demangled_name: str | None = field(default=None)


@dataclass(order=True)
class LineDecl:
    number: int
    count: int
    unexecuted_block: bool | None


@dataclass
class FileInfo:
    functions: list[FunctionDecl] = field(default_factory=list)
    lines: list[LineDecl] = field(default_factory=list)

    def append_as(
        self,
        name: str,
        full_path: Path,
        coverage: dict[str, list[dict]],
        paths: dict[str, Path],
    ):
        for line in self.lines:
            if name not in coverage:
                coverage[name] = [{}, {}]
                paths[name] = full_path
            if line.number not in coverage[name][0]:
                coverage[name][0][line.number] = 0
            coverage[name][0][line.number] += line.count

        for function in self.functions:
            if None in [
                function.start_line,
                function.name,
                function.execution_count,
            ]:
                continue
            if name not in coverage:
                coverage[name] = [{}, {}]
                paths[name] = full_path
            if function.name not in coverage[name][1]:
                coverage[name][1][function.name] = {"name": function.name, "count": 0}
            coverage[name][1][function.name]["count"] += function.execution_count
            coverage[name][1][function.name]["start_line"] = function.start_line
            for value, key_name in [
                (function.end_line, "end_line"),
                (function.start_column, "start_column"),
                (function.end_column, "end_column"),
                (function.demangled_name, "demangled"),
            ]:
                if value is not None:
                    coverage[name][1][function.name][key_name] = value


class BaseTool(ABC):
    @abstractmethod
    def exclude(self) -> list[str]: ...

    @abstractmethod
    def preprocess(self) -> None: ...

    @abstractmethod
    def ext(self) -> str: ...

    @abstractmethod
    def stats(self, intermediate_file: str | Path) -> dict[Path, FileInfo] | None: ...
