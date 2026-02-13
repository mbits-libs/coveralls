# Copyright (c) 2026 Marcin Zdun
# This code is licensed under MIT license (see LICENSE for details)

import os
import xml.etree.ElementTree as ET
from pathlib import Path

from cov.base import BaseTool, FileInfo, FunctionDecl, LineDecl, recurse


def printET(node, depth, max_depth):
    if depth == max_depth:
        return
    prefix = depth * "   "
    print("{}{} {}".format(prefix, node.tag, node.attrib))
    if node.text is not None:
        text = node.text.strip()
        if text:
            print("{}   # {}".format(prefix, text))
    if node.tail is not None:
        text = node.tail.strip()
        if text:
            print("{}# {}".format(prefix, text))
    depth += 1
    for child in node:
        printET(child, depth, max_depth)


def diskname_from_xml(sources):
    disks = [child.text for child in sources if child.text is not None]
    if len(disks) == 1:
        return disks[0]


class CoberturaXML(BaseTool):
    def __init__(self, path):
        self.path = path

    def exclude(self):
        return ["msvc"]

    def preprocess(self):
        pass

    def ext(self):
        return ".xml"

    def stats(self, intermediate_file: str | Path):
        root = ET.parse(intermediate_file).getroot()
        sources, packages = None, None
        for child in root:
            if child.tag == "sources":
                sources = child
            if child.tag == "packages":
                packages = child

        if packages is None:
            return {}

        diskname = None
        if sources is not None:
            diskname = diskname_from_xml(sources)
        if diskname is None:
            diskname = os.path.splitdrive(os.path.abspath(intermediate_file))[0]
        if len(diskname) and diskname[len(diskname) - 1] not in "\\/":
            diskname += os.sep

        result: dict[Path, FileInfo] = {}
        for package in packages:
            for classes in package:
                for klass in classes:
                    try:
                        filename = klass.attrib["filename"]
                    except KeyError:
                        continue

                    filename = Path(os.path.join(diskname, filename))

                    lines = None
                    for info in klass:
                        if info.tag == "lines":
                            lines = info

                    if lines is None:
                        continue

                    raw_lines: list[LineDecl] = []
                    for line in lines:
                        try:
                            number = int(line.attrib["number"])
                            hits = int(line.attrib["hits"])
                            raw_lines.append(LineDecl(number, hits, False))
                        except KeyError:
                            continue
                        except ValueError:
                            continue

                    coverage = list(sorted(raw_lines))
                    if not len(coverage):
                        continue
                    result[filename] = FileInfo([], coverage)

        return result
