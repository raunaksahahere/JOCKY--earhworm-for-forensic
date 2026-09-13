# Command contract v1

Python owns parsing, validation, dispatch, forensic results, and reports.
The existing six actions and synchronous dispatcher remain in place.

## Entry points

`parse_validated_command(text) -> Command` parses and validates an immutable
dataclass. `Command.to_dict()` provides the versioned wire representation:

```json
{
  "schema_version": 1,
  "action": "search",
  "target": "file",
  "path": "invoice draft",
  "search_path": "C:\\Case Files\\"
}
```

The JSON above escapes backslashes because it is JSON. The command language
does not use backslash escapes.

`parse_command(text) -> dict` remains the compatibility entry point. It returns
exactly the legacy dispatcher shape, without schema metadata or unused keys.
`Command.to_dispatch_dict()` returns the same shape. Only the API/model boundary
adds `schema_version`; the dispatcher does not need modification.

| Action | Target | Arguments |
| --- | --- | --- |
| `hash` | `file` | `path` |
| `encrypt` | `file` | `path` |
| `list` | `files` | `path` |
| `search` | `file` | `path` (name substring), `search_path` (directory) |
| `system_info` | omitted | none |
| `processes` | omitted | none |

## Accepted syntax

```text
HASH FILE evidence.bin
HASH FILE "C:\Case Files\नमूना.bin"
HASH FILE "\\server\share name\file.bin"
ENCRYPT FILE "disposable copy.bin"
SYSTEM INFO
PROCESSES
LIST FILES "C:\Case Files\"
LIST FILES './evidence sources'
SEARCH FILE "invoice draft" IN "/evidence/case 1"
HASH FILE "O'Brien.bin"
HASH FILE 'a"b.bin'
```

- Keywords are uppercase and separated by spaces or tabs. Only one command
  line is accepted. Leading/trailing horizontal whitespace outside arguments
  is ignored. Concatenated keywords, extra arguments, newlines, and control
  characters are rejected.
- Arguments are bare non-whitespace tokens without quote characters, or are
  entirely enclosed in matching single/double quotes. Empty or whitespace-only
  arguments are rejected. Other leading/trailing spaces inside quotes survive.
- Backslashes are always literal, including a trailing backslash before a
  closing quote. There are no shell, Python, JSON, or Unicode escape sequences.
  Use the opposite outer quote to include a literal quote in a filename. A path
  containing both quote types is not representable in v1; concatenated quoted
  fragments and escaped delimiters are rejected rather than guessed.
- Unicode and punctuation are preserved. No environment expansion, tilde
  expansion, globbing, slash conversion, case folding, `..` collapse, absolute
  resolution, existence check, or symlink resolution occurs during parsing.
- Relative paths retain the existing execution rule: resolve against the
  backend process's working directory. Callers must control that directory.
  Windows path text parses on Linux (and vice versa); this does not make a
  foreign platform's paths accessible on the execution host.
- SEARCH remains a recursive, case-insensitive filename **substring** match.
- HASH commands select SHA-256. Other algorithms remain available to the
  existing Python `hash_file(path, algorithm)` function, not new language syntax.
- ENCRYPT syntax is preserved, but execution now fails safely unless an explicit separate export destination and recovery passphrase are supplied through the evidence export API. Source evidence is never overwritten.
  Regression tests use disposable copies. It is not a production evidence
  protection design. DECRYPT exists as a Python helper, not a language action.

## Errors and HTTP compatibility

`CommandSyntaxError` (`code=invalid_syntax`, `kind=parser`) identifies malformed
syntax and includes line/column. `CommandValidationError`
(`code=invalid_command`, `kind=validation`) identifies invalid text types,
empty arguments, or invalid domain combinations. Both derive from
`CommandError`, a `ValueError`. Filesystem/execution exceptions are separate.

The API keeps `status`, `command`, `result`, `report`, and string-or-null `error`.
It adds `normalized_command`, `error_code`, and `error_kind`. Expected failures
retain HTTP 400 for compatibility; unexpected bugs produce HTTP 500 with a
generic client message and logged exception. Error kinds are `validation`,
`parser`, `execution`, and `internal`. Successful responses set error fields to
null. Reports exist even for malformed JSON or an empty command. A request with
no valid string command uses an empty command identity and null normalized
command; execution failures retain the successfully parsed action and target.

Report timestamps are UTC with an explicit offset. Reports include their schema
version and a copy of the result, including skipped/truncated data and collector
warnings. Completed means execution completed, not that collection was complete
or evidence is authentic. Inspect `complete`, `truncated`, `skipped_count`, and
`warnings` in collector results. API reports also retain normalized commands,
including both SEARCH arguments.

## Correctness changes

- Search rejects a regular file root, propagates an inaccessible root, and
  reports unreadable descendants. Lists and searches expose skipped/truncated
  observations. List scanning stops after 20,000 entries and returns at most
  500; search scans at most 20,000 files and returns at most 200 matches.
- Process memory is nullable when unavailable. Per-process CPU is always null
  in this snapshot collector, because no interval was sampled. Warnings explain
  this. Clients must render null as unavailable, not zero.
- Hash `created` is nullable when birth time is unavailable. Linux metadata
  change time is exposed separately as `metadata_changed`; it is not creation.
- Hashing checks file identity, size, and nanosecond timestamps around the
  structural check and digest read. An observed change fails without a ledger
  entry. This detects races; it is not a filesystem snapshot or write blocker.
- Ledger corruption/read/write errors raise `LedgerError`; no successful hash
  report or integrity claim is returned when history is unusable. Existing
  contents are not silently reset. Compare+append is serialized for threads
  within one process, with atomic file replacement. Multiple backend processes
  remain unsupported until transactional persistence is introduced.
- Structural checks are heuristics. Marker-only JPEG/PNG/PDF results do not
  validate the full format. Input checking is capped at 128 MiB, archive output
  at 64 MiB, and ZIP members at 10,000. Exceeding a limit returns unknown rather
  than a clean verdict. Hashing still reads the full file. No wall-clock deadline
  or cancellation facility is introduced in this slice.

## Deliberately deferred

SQLite, production WSGI/runtime supervision, authentication/CORS hardening,
safe encryption export, platform collectors, persisted IR, and Flutter remain
separate work. User-data locations and process-safe ledger persistence are the
next storage boundary to establish.
