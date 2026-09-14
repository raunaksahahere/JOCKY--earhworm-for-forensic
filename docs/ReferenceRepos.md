# Reference material

What was learned from existing projects, and the line between learning from
something and taking from it.

**No reference repository is vendored into this product.** The only derived
artefact shipped is `analysis/data/driver_risk_reference.json`, which records its
own source.

## Velociraptor

*An endpoint-visibility platform with its own query language.*

**Taken:** the shape of the idea — a declarative language describing evidence to
collect, compiled and dispatched to enrolled endpoints, with results returned as
structured data rather than text.

**Deliberately not taken:** Velociraptor's VQL can execute arbitrary code on an
endpoint, which is right for its purpose and wrong for this one. JOCKY's plan
tasks name a source from a fixed registry and cannot express anything else. The
control plane's worst case is a forensic collection request, not code execution.

## LOLDrivers

*A catalogue of drivers that have been abused.*

**Taken:** the data. 687 entries, 831 names and 2,266 SHA-256 hashes were derived
into `analysis/data/driver_risk_reference.json`, which records the upstream
source and a description stating it is for verification only.

**How it is used:** to say a driver known to have been abused elsewhere is
present on this machine. Never to say it was abused here — several entries are
legitimate signed vendor drivers still in use for their intended purpose, and
the finding text says so every time.

**A lesson from getting it wrong:** matching by bare filename paired the Linux
`msr` module with the Windows `msr.sys` driver on every Linux host. Filename
matching is now attempted only for Windows-style records, and is reported at low
confidence even then.

## MemProcFS

*Memory analysis as a filesystem.*

**Taken:** the read-only posture. Memory analysis is a read of an image, never a
write, and never execution of anything found in it. `analysis/memory.py` records
`read_only: true`, `memory_written: false`, `code_executed: false` on every
result.

**Not taken:** live memory acquisition. JOCKY analyses an image the investigator
supplies.

## Volatility3

*The memory analysis tool JOCKY drives when it is present.*

**Taken:** its plugin output format. `_normalize_processes` handles
`ImageFileName` (windows.pslist), `COMM` (linux.pslist) and `Name` (mac.pslist),
because each plugin names the column differently.

**Status:** driven through `shutil.which`, never bundled. The path is exercised
only against fixtures; no real image has been analysed.

## Compiler and IR material

**Taken:** the separation that makes the whole compiler worth having — a
platform-neutral IR between the language and the platform. It is what lets the
same program produce a Linux plan today and a Windows plan later without the
grammar, the parser or the IR changing.

**A lesson from getting it wrong:** ignoring whitespace globally in the grammar
let names swallow the keyword that followed, and eighteen statements parsed as
five. Statements are newline-terminated for that reason.

## The original JOCKY

The earlier iteration of this project established the command language, the
report structure and the local-first, loopback-only posture. This pass kept all
three and added the investigation language, the endpoint architecture and the
casework layer around them.

## Offensive material

Any offensive project present in the surrounding materials was treated purely as
a threat model — a description of what an investigator might be looking for.
None of its behaviour is implemented. See `docs/SecurityBoundaries.md`.
