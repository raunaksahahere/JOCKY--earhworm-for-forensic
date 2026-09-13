import * as React from "react";
import { fetchCommandReference } from "@/services/api";
import type { CommandReferenceEntry } from "@/lib/types";

// Mirrors compiler/Language_meta.py. Used before the API reference loads,
// or if the API is unreachable, so the console still shows correct syntax.
export const FALLBACK_COMMAND_REFERENCE: CommandReferenceEntry[] = [
  {
    name: "HASH",
    syntax: "HASH FILE <path>",
    example: "HASH FILE evidence.bin",
    description: "Compute a cryptographic hash of a file for integrity verification.",
    category: "integrity",
  },
  {
    name: "ENCRYPT",
    syntax: "ENCRYPT FILE <path>",
    example: "ENCRYPT FILE evidence.bin",
    description: "Encrypt a file in place to protect evidence at rest.",
    category: "evidence-handling",
  },
  {
    name: "SYSTEM INFO",
    syntax: "SYSTEM INFO",
    example: "SYSTEM INFO",
    description: "Collect read-only host system information (OS, CPU, memory, runtime).",
    category: "system",
  },
  {
    name: "LIST FILES",
    syntax: "LIST FILES <path>",
    example: "LIST FILES ./evidence",
    description: "List files and directories at a given path with metadata.",
    category: "filesystem",
  },
  {
    name: "PROCESSES",
    syntax: "PROCESSES",
    example: "PROCESSES",
    description: "Observe currently running processes (read-only).",
    category: "system",
  },
  {
    name: "SEARCH FILE",
    syntax: "SEARCH FILE <name> IN <path>",
    example: "SEARCH FILE malware.exe IN ./samples",
    description: "Search a directory tree for files matching a name.",
    category: "filesystem",
  },
];

export function useCommandReference(): CommandReferenceEntry[] {
  const [reference, setReference] = React.useState<CommandReferenceEntry[]>(
    FALLBACK_COMMAND_REFERENCE,
  );

  React.useEffect(() => {
    let cancelled = false;
    fetchCommandReference().then((entries) => {
      if (!cancelled && entries.length > 0) setReference(entries);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  return reference;
}
