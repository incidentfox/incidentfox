#!/usr/bin/env python3
"""
Static observability gap analyzer.

Parses source code via AST (Python) and regex patterns (JS/TS/Go/Java)
to mechanically detect missing logging, metrics, and tracing.

This is NOT an LLM — it's deterministic static analysis that:
1. Finds code paths that SHOULD have observability but DON'T
2. Outputs structured JSON for LLM-powered suggestion generation
3. Runs in <1 second on most codebases

Technical approach:
- Python: Full AST parsing via `ast` module
- JS/TS: Regex-based pattern matching (no node dependency)
- Go/Java: Regex-based pattern matching

The LLM layer (SKILL.md) consumes this output and adds:
- Business context ("why this matters at 3am")
- Concrete code suggestions matching project conventions
- Priority ranking based on incident impact
"""

import ast
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Gap:
    """A detected observability gap."""
    file: str
    line: int
    end_line: Optional[int]
    category: str        # error_handling, external_call, auth, state_transition, data_mutation
    severity: str        # critical, high, medium
    gap_type: str        # specific gap identifier
    description: str     # human-readable description
    code_snippet: str    # the problematic code
    suggestion_hint: str # hint for LLM on what to suggest


@dataclass
class FileReport:
    """Analysis report for a single file."""
    file: str
    language: str
    lines: int
    has_logging: bool
    logging_library: Optional[str]
    has_metrics: bool
    has_tracing: bool
    error_handlers: int      # total catch/except blocks
    logged_handlers: int     # handlers that have logging
    external_calls: int      # HTTP/DB/API calls detected
    gaps: list = field(default_factory=list)


@dataclass
class ScanReport:
    """Full scan report."""
    files_scanned: int
    total_gaps: int
    critical: int
    high: int
    medium: int
    score: int  # 1-10
    files: list = field(default_factory=list)


# ============================================================================
# Detection patterns
# ============================================================================

# Logging library detection
PYTHON_LOGGING = re.compile(
    r'(?:import\s+(?:logging|structlog)|from\s+(?:logging|structlog|\..*logging)\s+import|'
    r'logger\s*=\s*(?:logging\.getLogger|structlog\.get_logger|get_logger))',
    re.MULTILINE,
)
JS_LOGGING = re.compile(
    r'(?:require\s*\(\s*[\'"](?:winston|pino|bunyan|log4js)[\'"]|'
    r'import\s+.*(?:winston|pino|bunyan|log4js)|'
    r'const\s+logger\s*=)',
    re.MULTILINE,
)
GO_LOGGING = re.compile(
    r'(?:import\s+.*(?:log/slog|zerolog|logrus|zap)|'
    r'slog\.\w+|log\.\w+|logger\.\w+)',
    re.MULTILINE,
)

# Logging call detection
PYTHON_LOG_CALLS = re.compile(
    r'(?:logger|log|logging)\.\s*(?:debug|info|warning|warn|error|critical|fatal|exception)\s*\(',
    re.MULTILINE,
)
JS_LOG_CALLS = re.compile(
    r'(?:logger|log|console)\.\s*(?:debug|info|warn|error|log|trace)\s*\(',
    re.MULTILINE,
)
GO_LOG_CALLS = re.compile(
    r'(?:slog|log|logger)\.\s*(?:Debug|Info|Warn|Error|Fatal)\s*(?:f|w|Context)?\s*\(',
    re.MULTILINE,
)

# Metrics detection
METRICS_PATTERN = re.compile(
    r'(?:prometheus|prom_client|statsd|datadog|metrics|counter|histogram|gauge)\.',
    re.IGNORECASE | re.MULTILINE,
)

# Tracing detection
TRACING_PATTERN = re.compile(
    r'(?:opentelemetry|otel|tracer|span|trace\.|@trace|tracing)',
    re.IGNORECASE | re.MULTILINE,
)

# External call detection
PYTHON_EXTERNAL = re.compile(
    r'(?:requests\.(?:get|post|put|delete|patch|head)|'
    r'httpx\.(?:get|post|put|delete|patch|head|AsyncClient|Client)|'
    r'aiohttp\.ClientSession|'
    r'urllib\.request|'
    r'session\.(?:execute|query|add|delete|commit|flush)|'  # SQLAlchemy
    r'cursor\.(?:execute|fetchone|fetchall)|'  # DB cursor
    r'redis\.\w+|'
    r'boto3\.\w+|'
    r'\.publish\(|\.send_message\()',  # Queue operations
    re.MULTILINE,
)
JS_EXTERNAL = re.compile(
    r'(?:fetch\s*\(|axios\.\w+|\.get\s*\(|\.post\s*\(|'
    r'supabase\.\w+|prisma\.\w+|mongoose\.\w+|'
    r'\.query\s*\(|\.execute\s*\(|'
    r'new\s+(?:Redis|S3Client|DynamoDBClient))',
    re.MULTILINE,
)

# Auth pattern detection
AUTH_PATTERN = re.compile(
    r'(?:authenticate|authorize|login|logout|verify_token|check_permission|'
    r'jwt\.(?:sign|verify|decode)|bcrypt|hash_password|check_password|'
    r'session\.create|session\.destroy|'
    r'raise\s+(?:ValueError|AuthError|PermissionError|HTTPException).*(?:token|auth|permission|forbidden|unauthorized))',
    re.IGNORECASE | re.MULTILINE,
)


# ============================================================================
# Python AST Analyzer (the good stuff)
# ============================================================================

class PythonAnalyzer(ast.NodeVisitor):
    """AST-based analyzer for Python files."""

    def __init__(self, source: str, filepath: str):
        self.source = source
        self.lines = source.splitlines()
        self.filepath = filepath
        self.gaps: list[Gap] = []
        self.error_handlers = 0
        self.logged_handlers = 0
        self.external_calls = 0
        self._in_except = False
        self._current_except_has_log = False

    def _get_lines(self, start: int, end: int) -> str:
        """Extract source lines."""
        return "\n".join(self.lines[start - 1 : end])

    def _has_logging_in_body(self, body: list[ast.stmt]) -> bool:
        """Check if a list of statements contains a logging call."""
        for node in ast.walk(ast.Module(body=body, type_ignores=[])):
            if isinstance(node, ast.Call):
                func = node.func
                # logger.error(...), log.info(...), logging.warning(...)
                if isinstance(func, ast.Attribute) and func.attr in (
                    "debug", "info", "warning", "warn", "error",
                    "critical", "fatal", "exception",
                ):
                    if isinstance(func.value, ast.Name) and func.value.id in (
                        "logger", "log", "logging", "self",
                    ):
                        return True
                    # self.logger.error(...)
                    if isinstance(func.value, ast.Attribute):
                        if func.value.attr in ("logger", "log"):
                            return True
                # print(...) counts as minimal logging
                if isinstance(func, ast.Name) and func.id == "print":
                    return True
                # _log(...) custom logging
                if isinstance(func, ast.Name) and func.id == "_log":
                    return True
        return False

    def _is_bare_except(self, handler: ast.ExceptHandler) -> bool:
        """Check if this is a bare except (catches everything with no specificity)."""
        return handler.type is None

    def _is_pass_only(self, body: list[ast.stmt]) -> bool:
        """Check if body is just `pass` or `...`"""
        if len(body) == 1:
            if isinstance(body[0], ast.Pass):
                return True
            if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if body[0].value.value is ...:
                    return True
        return False

    def visit_ExceptHandler(self, node: ast.ExceptHandler):
        """Analyze except/catch blocks for logging gaps."""
        self.error_handlers += 1
        has_logging = self._has_logging_in_body(node.body)

        if has_logging:
            self.logged_handlers += 1

        # Gap: except block with no logging at all
        if not has_logging:
            # Determine severity
            is_bare = self._is_bare_except(node)
            is_pass = self._is_pass_only(node.body)

            if is_bare and is_pass:
                severity = "critical"
                gap_type = "bare_except_pass"
                desc = "Bare `except: pass` swallows ALL errors silently"
            elif is_bare:
                severity = "critical"
                gap_type = "bare_except_no_log"
                desc = "Bare `except` catches all errors without logging"
            elif is_pass:
                severity = "high"
                gap_type = "except_pass"
                desc = f"Exception caught ({ast.dump(node.type) if node.type else 'all'}) but silently ignored"
            else:
                severity = "high"
                gap_type = "except_no_log"
                desc = "Exception caught but not logged"

            snippet = self._get_lines(node.lineno, min(node.end_lineno or node.lineno, node.lineno + 5))

            self.gaps.append(Gap(
                file=self.filepath,
                line=node.lineno,
                end_line=node.end_lineno,
                category="error_handling",
                severity=severity,
                gap_type=gap_type,
                description=desc,
                code_snippet=snippet,
                suggestion_hint="Add structured logging with error context, exception type, and business impact",
            ))

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Check functions for observability patterns."""
        self._check_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Check async functions for observability patterns."""
        self._check_function(node)
        self.generic_visit(node)

    def _check_function(self, node):
        """Analyze a function for observability gaps."""
        func_source = self._get_lines(node.lineno, node.end_lineno or node.lineno)
        func_name = node.name

        # Skip private/dunder methods and test functions
        if func_name.startswith("__") or func_name.startswith("test_"):
            return

        # Check for auth-related functions without logging
        auth_keywords = ("auth", "login", "logout", "verify", "permission", "token", "credential")
        is_auth_func = any(kw in func_name.lower() for kw in auth_keywords)

        if is_auth_func and not self._has_logging_in_body(node.body):
            self.gaps.append(Gap(
                file=self.filepath,
                line=node.lineno,
                end_line=node.end_lineno,
                category="auth",
                severity="high",
                gap_type="auth_no_logging",
                description=f"Auth function `{func_name}` has no logging — auth failures are invisible",
                code_snippet=self._get_lines(node.lineno, min(node.lineno + 3, node.end_lineno or node.lineno)),
                suggestion_hint="Log auth decisions (success/failure) with user context but NOT secrets",
            ))

        # Check for external calls in function body
        if PYTHON_EXTERNAL.search(func_source):
            self.external_calls += 1
            # Check if there's any timing/latency tracking
            has_timing = any(kw in func_source for kw in ("time.monotonic", "time.time", "perf_counter", "timer", "latency", "duration"))
            if not has_timing and "test" not in func_name.lower():
                # Only flag if function has external calls but no timing
                self.gaps.append(Gap(
                    file=self.filepath,
                    line=node.lineno,
                    end_line=node.end_lineno,
                    category="external_call",
                    severity="medium",
                    gap_type="external_call_no_timing",
                    description=f"Function `{func_name}` makes external calls without latency tracking",
                    code_snippet=self._get_lines(node.lineno, min(node.lineno + 2, node.end_lineno or node.lineno)),
                    suggestion_hint="Add timing around external calls to track latency in logs or metrics",
                ))

    def visit_Return(self, node: ast.Return):
        """Check for silent early returns in important contexts."""
        # This is a simple heuristic — flag returns inside try blocks that return None
        # without any logging (common pattern for "fail silently")
        self.generic_visit(node)

    def analyze(self) -> list[Gap]:
        """Run the full analysis."""
        try:
            tree = ast.parse(self.source)
            self.visit(tree)
        except SyntaxError:
            pass  # Can't parse = can't analyze
        return self.gaps


# ============================================================================
# Regex-based analyzer for JS/TS/Go/Java
# ============================================================================

def analyze_with_regex(source: str, filepath: str, language: str) -> tuple[list[Gap], int, int, int]:
    """
    Regex-based analysis for non-Python files.
    Returns (gaps, error_handlers, logged_handlers, external_calls).
    """
    gaps = []
    lines = source.splitlines()
    error_handlers = 0
    logged_handlers = 0
    external_calls = 0

    if language in ("javascript", "typescript"):
        log_pattern = JS_LOG_CALLS
        ext_pattern = JS_EXTERNAL
    elif language == "go":
        log_pattern = GO_LOG_CALLS
        ext_pattern = PYTHON_EXTERNAL  # reuse for now
    else:
        log_pattern = PYTHON_LOG_CALLS
        ext_pattern = PYTHON_EXTERNAL

    # Find catch blocks and check for logging
    catch_pattern = re.compile(
        r'(?:catch\s*\([^)]*\)|except\s+\w+|rescue\s+=>?)',
        re.MULTILINE,
    )

    for match in catch_pattern.finditer(source):
        error_handlers += 1
        # Check surrounding ~10 lines for logging calls
        start_pos = match.start()
        line_num = source[:start_pos].count("\n") + 1
        context_end = min(line_num + 10, len(lines))
        context = "\n".join(lines[line_num - 1 : context_end])

        if log_pattern.search(context):
            logged_handlers += 1
        else:
            snippet = "\n".join(lines[line_num - 1 : min(line_num + 4, len(lines))])
            gaps.append(Gap(
                file=filepath,
                line=line_num,
                end_line=min(line_num + 5, len(lines)),
                category="error_handling",
                severity="high",
                gap_type="catch_no_log",
                description="Catch block without logging",
                code_snippet=snippet,
                suggestion_hint="Add structured error logging with context",
            ))

    # Count external calls
    for match in ext_pattern.finditer(source):
        external_calls += 1

    # Check for empty catch blocks specifically
    empty_catch = re.compile(r'catch\s*\([^)]*\)\s*\{\s*\}', re.MULTILINE)
    for match in empty_catch.finditer(source):
        line_num = source[:match.start()].count("\n") + 1
        gaps.append(Gap(
            file=filepath,
            line=line_num,
            end_line=line_num + 1,
            category="error_handling",
            severity="critical",
            gap_type="empty_catch",
            description="Empty catch block — errors are completely invisible",
            code_snippet=match.group(0),
            suggestion_hint="Add error logging with full context",
        ))

    return gaps, error_handlers, logged_handlers, external_calls


# ============================================================================
# File scanning
# ============================================================================

LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".rs": "rust",
}


def detect_language(filepath: str) -> Optional[str]:
    """Detect language from file extension."""
    ext = Path(filepath).suffix.lower()
    return LANGUAGE_MAP.get(ext)


def analyze_file(filepath: str) -> Optional[FileReport]:
    """Analyze a single file for observability gaps."""
    language = detect_language(filepath)
    if not language:
        return None

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            source = f.read()
    except (OSError, IOError):
        return None

    lines = len(source.splitlines())
    if lines == 0:
        return None

    # Detect existing observability
    if language == "python":
        has_logging = bool(PYTHON_LOGGING.search(source))
        logging_lib = None
        if "structlog" in source:
            logging_lib = "structlog"
        elif "import logging" in source:
            logging_lib = "logging"
    elif language in ("javascript", "typescript"):
        has_logging = bool(JS_LOGGING.search(source)) or "console." in source
        logging_lib = None
        for lib in ("pino", "winston", "bunyan", "log4js"):
            if lib in source:
                logging_lib = lib
                break
        if not logging_lib and "console." in source:
            logging_lib = "console"
    elif language == "go":
        has_logging = bool(GO_LOGGING.search(source))
        logging_lib = None
        for lib in ("slog", "zerolog", "logrus", "zap"):
            if lib in source:
                logging_lib = lib
                break
    else:
        has_logging = bool(PYTHON_LOG_CALLS.search(source) or JS_LOG_CALLS.search(source))
        logging_lib = None

    has_metrics = bool(METRICS_PATTERN.search(source))
    has_tracing = bool(TRACING_PATTERN.search(source))

    # Run analysis
    if language == "python":
        analyzer = PythonAnalyzer(source, filepath)
        gaps = analyzer.analyze()
        error_handlers = analyzer.error_handlers
        logged_handlers = analyzer.logged_handlers
        external_calls = analyzer.external_calls
    else:
        gaps, error_handlers, logged_handlers, external_calls = analyze_with_regex(
            source, filepath, language
        )

    return FileReport(
        file=filepath,
        language=language,
        lines=lines,
        has_logging=has_logging,
        logging_library=logging_lib,
        has_metrics=has_metrics,
        has_tracing=has_tracing,
        error_handlers=error_handlers,
        logged_handlers=logged_handlers,
        external_calls=external_calls,
        gaps=[asdict(g) for g in gaps],
    )


def scan_path(target: str, max_files: int = 200) -> ScanReport:
    """Scan a file or directory for observability gaps."""
    target_path = Path(target)
    reports = []

    if target_path.is_file():
        report = analyze_file(str(target_path))
        if report:
            reports.append(report)
    elif target_path.is_dir():
        count = 0
        for root, dirs, files in os.walk(target_path):
            # Skip common non-source directories
            dirs[:] = [
                d for d in dirs
                if d not in (
                    "node_modules", ".git", "__pycache__", ".venv", "venv",
                    "dist", "build", ".next", ".cache", "vendor",
                    ".mypy_cache", ".pytest_cache", ".tox", "egg-info",
                )
            ]
            for fname in sorted(files):
                if count >= max_files:
                    break
                fpath = os.path.join(root, fname)
                report = analyze_file(fpath)
                if report:
                    reports.append(report)
                    count += 1

    # Aggregate
    all_gaps = []
    for r in reports:
        all_gaps.extend(r.gaps)

    critical = sum(1 for g in all_gaps if g["severity"] == "critical")
    high = sum(1 for g in all_gaps if g["severity"] == "high")
    medium = sum(1 for g in all_gaps if g["severity"] == "medium")

    # Score calculation
    total_handlers = sum(r.error_handlers for r in reports)
    logged_handlers = sum(r.logged_handlers for r in reports)

    if total_handlers == 0:
        handler_ratio = 1.0  # No handlers = no gaps (or no error handling at all)
    else:
        handler_ratio = logged_handlers / total_handlers

    # Score: weighted combination
    # - 40% error handler coverage
    # - 30% presence of logging library
    # - 20% no critical gaps
    # - 10% has metrics/tracing
    files_with_logging = sum(1 for r in reports if r.has_logging)
    logging_ratio = files_with_logging / max(len(reports), 1)
    critical_penalty = min(critical * 0.15, 0.6)
    metrics_bonus = 0.1 if any(r.has_metrics for r in reports) else 0

    raw_score = (
        handler_ratio * 0.4
        + logging_ratio * 0.3
        + (1 - critical_penalty) * 0.2
        + metrics_bonus
    )
    score = max(1, min(10, round(raw_score * 10)))

    return ScanReport(
        files_scanned=len(reports),
        total_gaps=len(all_gaps),
        critical=critical,
        high=high,
        medium=medium,
        score=score,
        files=[asdict(r) for r in reports],
    )


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python scan.py <file_or_directory> [--json]", file=sys.stderr)
        sys.exit(1)

    target = sys.argv[1]
    as_json = "--json" in sys.argv

    report = scan_path(target)

    if as_json:
        print(json.dumps(asdict(report), indent=2, default=str))
    else:
        # Human-readable summary
        print(f"\n{'='*60}")
        print(f"  OBSERVABILITY COVERAGE SCAN")
        print(f"{'='*60}")
        print(f"  Files scanned:  {report.files_scanned}")
        print(f"  Score:          {report.score}/10")
        print(f"  Total gaps:     {report.total_gaps}")
        print(f"    Critical:     {report.critical}")
        print(f"    High:         {report.high}")
        print(f"    Medium:       {report.medium}")
        print(f"{'='*60}\n")

        for file_report in report.files:
            if not file_report["gaps"]:
                continue
            print(f"\n  {file_report['file']}")
            print(f"  Language: {file_report['language']} | "
                  f"Logging: {'yes (' + (file_report['logging_library'] or 'unknown') + ')' if file_report['has_logging'] else 'NO'} | "
                  f"Handlers: {file_report['logged_handlers']}/{file_report['error_handlers']} logged")
            print(f"  {'─'*56}")

            for gap in file_report["gaps"]:
                icon = {"critical": "!!!", "high": " ! ", "medium": " . "}[gap["severity"]]
                print(f"  [{icon}] Line {gap['line']}: {gap['description']}")
                # Show first 2 lines of snippet
                snippet_lines = gap["code_snippet"].splitlines()[:2]
                for sl in snippet_lines:
                    print(f"        {sl.strip()}")
                print()

        if report.total_gaps == 0:
            print("  No observability gaps detected. Nice work!\n")


if __name__ == "__main__":
    main()
