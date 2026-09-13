# JOCKY command language

The authoritative syntax and normalized representation are documented in
[Command contract v1](../COMMAND_CONTRACT.md). The grammar, transformer, and
validated model remain the Python execution boundary.

```text
HASH FILE evidence.bin
ENCRYPT FILE "disposable copy.bin"
SYSTEM INFO
PROCESSES
LIST FILES "C:\Case Files\"
SEARCH FILE "invoice draft" IN "/evidence/case 1"
```

Use single or double quotes around paths containing spaces. Backslashes are
literal. Keywords are uppercase; spaces/tabs separate keywords and arguments.
The parser preserves path text instead of applying host-specific normalization.
Missing/extra arguments, empty paths, unmatched quotes, and multiple command
lines fail explicitly. HASH selects SHA-256. ENCRYPT retains its legacy in-place
behavior and must only be tested on disposable copies.
