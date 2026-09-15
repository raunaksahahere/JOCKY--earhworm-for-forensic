"""
Paths that came from evidence, not from this machine.

A path in a record belongs to the host that was examined, and that host is not
necessarily the one doing the analysis. Evidence collected from a Linux endpoint
and correlated on a Windows workstation is an ordinary case -- it is what the
multi-endpoint architecture is for -- and `os.path` is the wrong tool for it:
`os.path.abspath("/usr/bin/curl")` on Windows returns `D:\\usr\\bin\\curl`,
inventing a drive that was never in the evidence and breaking every join that
depended on the path.

So these functions treat a path as text from a record. They never touch the
filesystem, never consult the current directory, and behave identically
whichever platform is running them.

For paths that really are local -- a file this machine is about to open --
`os.path` remains correct and is still used.
"""

from __future__ import annotations

import re

#: A drive-qualified Windows path, with either separator.
_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
#: A UNC share.
_UNC = re.compile(r"^\\\\[^\\]+\\")


def normalize(path: str | None) -> str:
    """One spelling for one path, so records about it can be joined.

    Separators become forward slashes and repeats collapse. Case is left alone:
    two paths differing only in case are the same file on Windows and different
    files on Linux, and the evidence does not say which host it came from.
    """
    if not path:
        return ""
    text = str(path).replace("\\", "/")
    while "//" in text[2:]:
        text = text[:2] + text[2:].replace("//", "/")
    if len(text) > 1 and text.endswith("/"):
        text = text.rstrip("/") or "/"
    return text


def is_absolute(path: str | None) -> bool:
    """Whether a path names a location outright, on any platform.

    A relative path in a record cannot be resolved -- the working directory it
    was relative to is not in the evidence -- so callers use this to decline
    rather than to guess.
    """
    if not path:
        return False
    text = str(path)
    return bool(text.startswith("/") or _DRIVE.match(text) or _UNC.match(text)
                or text.startswith("\\\\"))


def basename(path: str | None) -> str:
    """The last segment, splitting on either separator."""
    return normalize(path).rsplit("/", 1)[-1] if path else ""


def dirname(path: str | None) -> str:
    """Everything before the last segment."""
    text = normalize(path)
    if "/" not in text:
        return ""
    head = text.rsplit("/", 1)[0]
    return head or "/"


def same_path(left: str | None, right: str | None) -> bool:
    """Whether two records name the same location."""
    return bool(left) and bool(right) and normalize(left) == normalize(right)
