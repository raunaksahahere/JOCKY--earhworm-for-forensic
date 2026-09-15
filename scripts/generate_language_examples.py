#!/usr/bin/env python3
"""
Regenerate the client's copy of the example programs from `examples/*.x`.

    python3 scripts/generate_language_examples.py

The client ships the examples so the editor can offer them without a round trip
to the engine, which means the same program text exists in two places. Rather
than keep them in step by hand, this generates one from the other and
`tests/test_examples.py` fails if they have drifted.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
TARGET = ROOT / "flutter_client" / "lib" / "features" / "language" / "language_examples.dart"

#: Order is the order the editor offers them: simplest first.
ORDER = ["basic", "filtering", "correlation", "multihost", "conditional"]
SUMMARIES = {
    "basic": "Case, target, window, collection, report",
    "filtering": "Bindings, lists and boolean predicates",
    "correlation": "Several sources, correlated",
    "multihost": "One playbook across several endpoints",
    "conditional": "One program, a different plan per platform",
}

HEADER = '''/// The example JOCKY programs shipped with this build.
///
/// GENERATED FROM `examples/*.x` — do not edit by hand. `tests/test_examples.py`
/// asserts that this file still matches those files, so an example cannot be
/// changed in the repository and left stale in the client.
library;

class JockyExample {
  const JockyExample({required this.name, required this.summary, required this.source});

  final String name;
  final String summary;
  final String source;
}

const List<JockyExample> jockyExamples = [
'''


def dart_string(text: str) -> str:
    """A Dart literal for one program.

    A raw triple-quoted string is used wherever the program allows it, because
    JOCKY programs are full of backslashes in regular expressions and `$` in
    variable references, and escaping those by hand is how an example stops
    compiling.
    """
    if "'''" in text:
        raise ValueError("a program containing ''' cannot be embedded as a Dart raw string")
    if "\\" not in text and "$" not in text:
        return f"r'''{text}'''"
    escaped = text.replace("\\", "\\\\").replace("$", "\\$")
    return f"'''{escaped}'''"


def render() -> str:
    parts = []
    for name in ORDER:
        source = (EXAMPLES / f"{name}.x").read_text(encoding="utf-8")
        parts.append(
            "  JockyExample(\n"
            f"    name: '{name}',\n"
            f"    summary: '{SUMMARIES[name]}',\n"
            f"    source: {dart_string(source)},\n"
            "  ),"
        )
    return HEADER + "\n".join(parts) + "\n];\n"


def main() -> int:
    rendered = render()
    if "--check" in sys.argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != rendered:
            print(f"{TARGET} is stale; run scripts/generate_language_examples.py")
            return 1
        print(f"{TARGET} is up to date")
        return 0
    TARGET.write_text(rendered, encoding="utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
