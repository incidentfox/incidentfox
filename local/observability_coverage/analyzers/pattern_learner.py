#!/usr/bin/env python3
"""
Observability pattern learner.

Instead of hardcoded rules, this learns what "good observability" looks like
from the org's OWN codebase, then finds code that doesn't match.

This is the moat: generic tools say "add logging." We say "your team logs
payment errors with {user_id, amount, error_code, retry_count} in service A —
service B should do the same."

Approach:
1. Scan codebase for existing log statements
2. Extract patterns: field names, log levels, event naming conventions
3. Cluster similar code paths (error handlers, API calls, auth checks)
4. Compare: well-instrumented code vs poorly-instrumented code
5. Generate suggestions that match YOUR conventions, not generic best practices

The output is a "pattern profile" — a learned model of how THIS org does
observability. It's used by the LLM layer to make org-specific suggestions.
"""

import ast
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class LogPattern:
    """A single observed logging pattern."""
    file: str
    line: int
    level: str              # debug, info, warning, error, critical
    event_name: str         # first arg if string literal
    fields: list[str]       # keyword argument names
    in_error_handler: bool  # inside try/except
    function_name: str      # enclosing function
    has_correlation_id: bool
    has_user_context: bool
    has_error_context: bool


@dataclass
class OrgProfile:
    """Learned observability profile for an organization/codebase."""
    files_scanned: int
    total_log_statements: int
    logging_libraries: dict          # library -> count of files using it
    log_level_distribution: dict     # level -> count
    naming_convention: str           # snake_case, camelCase, dot.notation
    common_fields: list[str]         # most common log fields across codebase
    common_event_prefixes: list[str] # e.g., ["mcp_", "github_", "slack_"]
    error_handler_patterns: dict     # what good error handlers look like
    field_consistency: dict          # field name -> how consistently it's used
    correlation_id_usage: float      # % of log statements with correlation ID
    well_instrumented_files: list[str]  # files with best coverage (exemplars)
    poorly_instrumented_files: list[str]  # files with worst coverage
    suggestions: list[dict]          # cross-file consistency suggestions


class PatternExtractor(ast.NodeVisitor):
    """Extract logging patterns from Python AST."""

    LOG_METHODS = {"debug", "info", "warning", "warn", "error", "critical", "fatal", "exception"}
    LOGGER_NAMES = {"logger", "log", "logging", "self"}
    CORRELATION_FIELDS = {"correlation_id", "request_id", "trace_id", "span_id", "run_id"}
    USER_FIELDS = {"user_id", "userId", "user", "org_id", "team_id", "team_node_id"}
    ERROR_FIELDS = {"error", "err", "exception", "exc_info", "error_code", "error_message", "reason"}

    def __init__(self, source: str, filepath: str):
        self.source = source
        self.lines = source.splitlines()
        self.filepath = filepath
        self.patterns: list[LogPattern] = []
        self._current_function = "<module>"
        self._in_except = False

    def visit_FunctionDef(self, node):
        old = self._current_function
        self._current_function = node.name
        self.generic_visit(node)
        self._current_function = old

    def visit_AsyncFunctionDef(self, node):
        old = self._current_function
        self._current_function = node.name
        self.generic_visit(node)
        self._current_function = old

    def visit_ExceptHandler(self, node):
        old = self._in_except
        self._in_except = True
        self.generic_visit(node)
        self._in_except = old

    def visit_Call(self, node):
        """Detect logging calls and extract their patterns."""
        func = node.func

        # Match: logger.info(...), log.error(...), etc.
        if isinstance(func, ast.Attribute) and func.attr in self.LOG_METHODS:
            is_logger = False
            if isinstance(func.value, ast.Name) and func.value.id in self.LOGGER_NAMES:
                is_logger = True
            elif isinstance(func.value, ast.Attribute) and func.value.attr in self.LOGGER_NAMES:
                is_logger = True

            if is_logger:
                self._extract_pattern(node, func.attr)

        self.generic_visit(node)

    def _extract_pattern(self, call: ast.Call, level: str):
        """Extract a logging pattern from a call node."""
        # Get event name (first positional string arg)
        event_name = ""
        if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
            event_name = call.args[0].value

        # Get field names from keyword args
        fields = [kw.arg for kw in call.keywords if kw.arg is not None]

        # Check for exc_info in keywords
        has_exc_info = any(kw.arg == "exc_info" for kw in call.keywords)

        # Classify fields
        has_correlation = bool(set(fields) & self.CORRELATION_FIELDS)
        has_user = bool(set(fields) & self.USER_FIELDS)
        has_error = bool(set(fields) & self.ERROR_FIELDS) or has_exc_info

        self.patterns.append(LogPattern(
            file=self.filepath,
            line=call.lineno,
            level=level,
            event_name=event_name,
            fields=fields,
            in_error_handler=self._in_except,
            function_name=self._current_function,
            has_correlation_id=has_correlation,
            has_user_context=has_user,
            has_error_context=has_error,
        ))

    def extract(self) -> list[LogPattern]:
        try:
            tree = ast.parse(self.source)
            self.visit(tree)
        except SyntaxError:
            pass
        return self.patterns


def _detect_naming_convention(event_names: list[str]) -> str:
    """Detect whether event names use snake_case, camelCase, or dot.notation."""
    if not event_names:
        return "unknown"

    snake = sum(1 for n in event_names if "_" in n and n == n.lower())
    camel = sum(1 for n in event_names if any(c.isupper() for c in n[1:]) and "_" not in n)
    dot = sum(1 for n in event_names if "." in n)

    counts = {"snake_case": snake, "camelCase": camel, "dot.notation": dot}
    winner = max(counts, key=counts.get)
    return winner if counts[winner] > 0 else "unknown"


def _extract_prefixes(event_names: list[str], min_count: int = 3) -> list[str]:
    """Extract common event name prefixes."""
    prefix_counts = Counter()
    for name in event_names:
        parts = re.split(r'[_.]', name)
        if len(parts) >= 2:
            prefix_counts[parts[0] + "_"] += 1

    return [prefix for prefix, count in prefix_counts.most_common(10) if count >= min_count]


def learn_patterns(target: str, max_files: int = 300) -> OrgProfile:
    """
    Scan a codebase and learn its observability patterns.

    This produces a "pattern profile" — a model of how this org does observability.
    """
    target_path = Path(target)
    all_patterns: list[LogPattern] = []
    file_pattern_counts: dict[str, int] = {}
    file_handler_counts: dict[str, tuple[int, int]] = {}  # file -> (total_handlers, logged_handlers)
    logging_libs: Counter = Counter()

    files_scanned = 0

    # Walk the codebase
    if target_path.is_file():
        paths = [str(target_path)]
    else:
        paths = []
        for root, dirs, files in os.walk(target_path):
            dirs[:] = [d for d in dirs if d not in (
                "node_modules", ".git", "__pycache__", ".venv", "venv",
                "dist", "build", ".next", ".cache", "vendor",
                ".mypy_cache", ".pytest_cache", ".tox",
            )]
            for fname in sorted(files):
                if fname.endswith(".py") and not fname.startswith("test_"):
                    paths.append(os.path.join(root, fname))
                    if len(paths) >= max_files:
                        break

    for fpath in paths:
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()
        except (OSError, IOError):
            continue

        files_scanned += 1

        # Detect logging library
        if "structlog" in source:
            logging_libs["structlog"] += 1
        elif "import logging" in source:
            logging_libs["logging"] += 1
        elif "get_logger" in source:
            logging_libs["get_logger (custom)"] += 1

        # Extract patterns
        extractor = PatternExtractor(source, fpath)
        patterns = extractor.extract()
        all_patterns.extend(patterns)
        file_pattern_counts[fpath] = len(patterns)

        # Count error handlers via simple AST walk
        try:
            tree = ast.parse(source)
            total_handlers = 0
            logged_handlers = 0
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    total_handlers += 1
                    # Check if handler has logging (simplified)
                    handler_source = ast.get_source_segment(source, node) or ""
                    if re.search(r'logger\.\w+|log\.\w+|logging\.\w+|_log\(', handler_source):
                        logged_handlers += 1
            file_handler_counts[fpath] = (total_handlers, logged_handlers)
        except SyntaxError:
            pass

    # Aggregate analysis
    event_names = [p.event_name for p in all_patterns if p.event_name]
    all_fields = [f for p in all_patterns for f in p.fields]
    field_counts = Counter(all_fields)

    # Level distribution
    level_dist = Counter(p.level for p in all_patterns)

    # Naming convention
    naming = _detect_naming_convention(event_names)

    # Common prefixes
    prefixes = _extract_prefixes(event_names)

    # Common fields (top 20)
    common_fields = [f for f, _ in field_counts.most_common(20)]

    # Correlation ID usage
    total_logs = len(all_patterns)
    corr_logs = sum(1 for p in all_patterns if p.has_correlation_id)
    corr_usage = corr_logs / max(total_logs, 1)

    # Error handler logging in error handlers
    error_logs = [p for p in all_patterns if p.in_error_handler]
    error_with_context = sum(1 for p in error_logs if p.has_error_context)
    error_with_corr = sum(1 for p in error_logs if p.has_correlation_id)

    error_handler_patterns = {
        "total_error_logs": len(error_logs),
        "with_error_context": error_with_context,
        "with_correlation_id": error_with_corr,
        "common_error_fields": [
            f for f, _ in Counter(
                f for p in error_logs for f in p.fields
            ).most_common(10)
        ],
    }

    # Field consistency: how consistently each field is used across files
    field_per_file = defaultdict(set)
    for p in all_patterns:
        for f in p.fields:
            field_per_file[f].add(p.file)

    files_with_logging = set(p.file for p in all_patterns)
    field_consistency = {}
    for f in common_fields[:10]:
        files_using = len(field_per_file[f])
        total_files = max(len(files_with_logging), 1)
        field_consistency[f] = round(files_using / total_files, 2)

    # Find well-instrumented vs poorly-instrumented files
    file_scores = {}
    for fpath, (total, logged) in file_handler_counts.items():
        log_count = file_pattern_counts.get(fpath, 0)
        if total == 0 and log_count == 0:
            continue  # Skip files with no error handling and no logging
        ratio = logged / max(total, 1)
        # Score: handler coverage + log density
        lines = 1
        try:
            with open(fpath) as f:
                lines = max(sum(1 for _ in f), 1)
        except:
            pass
        density = min(log_count / (lines / 100), 1.0)  # logs per 100 lines, capped at 1
        file_scores[fpath] = ratio * 0.6 + density * 0.4

    sorted_files = sorted(file_scores.items(), key=lambda x: x[1], reverse=True)
    well_instrumented = [f for f, s in sorted_files[:5] if s > 0.5]
    poorly_instrumented = [f for f, s in sorted_files[-5:] if s < 0.3]

    # Cross-file consistency suggestions
    suggestions = []

    # Suggestion: inconsistent correlation ID usage
    if 0.1 < corr_usage < 0.8:
        files_without_corr = [
            p.file for p in all_patterns
            if not p.has_correlation_id and p.level in ("error", "warning", "info")
        ]
        unique_files = list(set(files_without_corr))[:5]
        suggestions.append({
            "type": "correlation_id_inconsistency",
            "severity": "high",
            "message": f"Correlation IDs used in {corr_usage:.0%} of log statements. "
                       f"These files are missing them: {', '.join(os.path.basename(f) for f in unique_files)}",
            "files": unique_files,
        })

    # Suggestion: error handlers without error context
    if error_logs and error_with_context / max(len(error_logs), 1) < 0.5:
        suggestions.append({
            "type": "error_context_missing",
            "severity": "high",
            "message": f"Only {error_with_context}/{len(error_logs)} error handler logs include error context "
                       f"(error message, error code, exc_info). "
                       f"Best practice in this codebase: {error_handler_patterns['common_error_fields'][:5]}",
        })

    # Suggestion: files with error handlers but no logging at all
    dark_files = [
        fpath for fpath, (total, logged) in file_handler_counts.items()
        if total > 2 and logged == 0
    ]
    if dark_files:
        suggestions.append({
            "type": "completely_dark_files",
            "severity": "critical",
            "message": f"{len(dark_files)} files have error handlers but ZERO logging. "
                       f"These are completely blind in production.",
            "files": dark_files[:10],
        })

    return OrgProfile(
        files_scanned=files_scanned,
        total_log_statements=total_logs,
        logging_libraries=dict(logging_libs),
        log_level_distribution=dict(level_dist),
        naming_convention=naming,
        common_fields=common_fields,
        common_event_prefixes=prefixes,
        error_handler_patterns=error_handler_patterns,
        field_consistency=field_consistency,
        correlation_id_usage=round(corr_usage, 2),
        well_instrumented_files=well_instrumented,
        poorly_instrumented_files=poorly_instrumented,
        suggestions=suggestions,
    )


def main():
    if len(sys.argv) < 2:
        print("Usage: python pattern_learner.py <directory> [--json]", file=sys.stderr)
        sys.exit(1)

    target = sys.argv[1]
    as_json = "--json" in sys.argv

    profile = learn_patterns(target)

    if as_json:
        print(json.dumps(asdict(profile), indent=2, default=str))
    else:
        print(f"\n{'='*60}")
        print(f"  OBSERVABILITY PATTERN PROFILE")
        print(f"{'='*60}")
        print(f"  Files scanned:      {profile.files_scanned}")
        print(f"  Log statements:     {profile.total_log_statements}")
        print(f"  Libraries:          {profile.logging_libraries}")
        print(f"  Naming convention:  {profile.naming_convention}")
        print(f"  Correlation ID %:   {profile.correlation_id_usage:.0%}")
        print(f"{'='*60}")

        print(f"\n  Log Level Distribution:")
        for level, count in sorted(profile.log_level_distribution.items(), key=lambda x: -x[1]):
            bar = "█" * min(count // 5, 40)
            print(f"    {level:>10}: {count:>4} {bar}")

        print(f"\n  Top Fields (your conventions):")
        for f in profile.common_fields[:10]:
            consistency = profile.field_consistency.get(f, 0)
            print(f"    {f:>25}: used in {consistency:.0%} of logged files")

        print(f"\n  Event Prefixes: {', '.join(profile.common_event_prefixes)}")

        print(f"\n  Error Handler Logging:")
        ehp = profile.error_handler_patterns
        print(f"    Total error logs:      {ehp['total_error_logs']}")
        print(f"    With error context:    {ehp['with_error_context']}")
        print(f"    With correlation ID:   {ehp['with_correlation_id']}")
        print(f"    Common error fields:   {ehp['common_error_fields'][:5]}")

        if profile.well_instrumented_files:
            print(f"\n  Well-instrumented (exemplars):")
            for f in profile.well_instrumented_files:
                print(f"    + {f}")

        if profile.poorly_instrumented_files:
            print(f"\n  Poorly-instrumented (needs work):")
            for f in profile.poorly_instrumented_files:
                print(f"    - {f}")

        if profile.suggestions:
            print(f"\n  Cross-Codebase Suggestions:")
            for s in profile.suggestions:
                icon = {"critical": "!!!", "high": " ! ", "medium": " . "}.get(s["severity"], " ? ")
                print(f"    [{icon}] {s['message']}")

        print()


if __name__ == "__main__":
    main()
