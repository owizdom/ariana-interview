#!/usr/bin/env python3
from __future__ import annotations

import ast
import re

from dataclasses import dataclass


@dataclass
class FunctionHit:
    name: str
    start_line: int
    end_line: int
    kind: str


class PythonFunctionVisitor(ast.NodeVisitor):
    def __init__(self):
        self.scope: list[str] = []
        self.functions: list[FunctionHit] = []

    def _name(self, name: str) -> str:
        return ".".join(self.scope + [name]) if self.scope else name

    def visit_ClassDef(self, node: ast.ClassDef):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        start = node.lineno
        end = getattr(node, "end_lineno", start) or start
        self.functions.append(FunctionHit(self._name(node.name), start, end, "python_function"))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        start = node.lineno
        end = getattr(node, "end_lineno", start) or start
        self.functions.append(FunctionHit(self._name(node.name), start, end, "python_async_function"))
        self.generic_visit(node)


def extract_python_functions(source: str) -> list[FunctionHit]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    visitor = PythonFunctionVisitor()
    visitor.visit(tree)
    return visitor.functions


JS_PATTERNS = [
    re.compile(r"^\s*(?:export\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\("),
    re.compile(r"^\s*(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?\("),
    re.compile(r"^\s*(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?\([^\)]*\)\s*=>"),
    re.compile(r"^\s*(?:async\s+)?(?P<name>[A-Za-z_$][\w$]*)\s*\([^\)]*\)\s*\{"),
]


def _regex_functions(source: str, patterns: list[re.Pattern], kind: str) -> list[FunctionHit]:
    out: list[FunctionHit] = []
    for line_no, line in enumerate(source.splitlines(), start=1):
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                out.append(FunctionHit(match.group("name"), line_no, 0, kind))
                break
    return out


def extract_js_functions(source: str) -> list[FunctionHit]:
    return _regex_functions(source, JS_PATTERNS, "js_function")


def extract_go_functions(source: str) -> list[FunctionHit]:
    pattern = re.compile(r"^\s*func\s+(?:\([^\)]+\)\s*)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\(")
    return _regex_functions(source, [pattern], "go_function")


def extract_java_like_functions(source: str) -> list[FunctionHit]:
    pattern = re.compile(
        r"^\s*(?:public|private|protected|static|final|synchronized|abstract\s+)?"
        r"(?:[A-Za-z_<>,\[\]\.]+\s+)+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*\([^\)]*\)\s*(?:throws\s+[^\{]+)?\{"
    )
    return _regex_functions(source, [pattern], "java_like_function")


def extract_ruby_functions(source: str) -> list[FunctionHit]:
    pattern = re.compile(r"^\s*def\s+(?P<name>[A-Za-z_]?[A-Za-z0-9_]+(?:\.[A-Za-z_][A-Za-z0-9_]*)?)")
    return _regex_functions(source, [pattern], "ruby_method")


EXTRACTORS: dict[str, callable] = {
    ".py": extract_python_functions,
    ".pyi": extract_python_functions,
    ".js": extract_js_functions,
    ".jsx": extract_js_functions,
    ".ts": extract_js_functions,
    ".tsx": extract_js_functions,
    ".go": extract_go_functions,
    ".java": extract_java_like_functions,
    ".cs": extract_java_like_functions,
    ".rb": extract_ruby_functions,
    ".cpp": extract_java_like_functions,
    ".c": extract_java_like_functions,
    ".cc": extract_java_like_functions,
    ".cxx": extract_java_like_functions,
    ".h": extract_java_like_functions,
    ".hpp": extract_java_like_functions,
}
