# YAML confirmation and file-write coordination

The component coordinates mutations of a resolved file path within Home
Assistant's event loop. Separate requests and MCP clients share the guard;
operations on different files can progress independently. Symlink and lexical
aliases resolving to the same path share it. Idle guards are weakly held.

| Operation | Protected work |
| --- | --- |
| YAML key edit (`add`, `replace`, `remove`) | Read the current source, construct the proposed result, verify confirmation, write, and report activation/configuration-check results. |
| Whole-file YAML restore (`replace_file`) | Replace the file and collect the resulting metadata. |
| Generic file write | Check existence/overwrite policy, write, and collect metadata. |
| File deletion | Check existence/type, collect metadata, and delete. |

## Confirmation

The token binds the normalized requested path, original source text and
proposed resulting text. Reading preserves line endings: comments, values,
formatting and LF/CRLF conversions all affect the source fingerprint. Replacing
or removing a section cannot hide changes made inside that section.

A confirmation queued behind another edit re-reads the file after acquiring
the guard. A mismatching token returns a fresh preview with
`confirm_token_mismatch: true` and `written: false`. Review that new diff before
confirming again. Unchanged source/result content remains confirmable; the
token is not a file-identity, timestamp or authorization check.

When confirmation is disabled, YAML edits still read and modify the latest
source under the guard. Explicit whole-file replacement and generic overwrite
remain intentional replacements, not merges.

## Write failure and cancellation

YAML edits and whole-file restores use uniquely named temporary files beside
the target, then replace it. Existing permission bits are preserved; new files
use the temporary file's restrictive permissions. Temporary files are removed
on failure, including failed source checks and failed replacements. This does
not add a crash-durability guarantee or change generic writes into atomic ones.

A request cancelled while waiting for the guard makes no change. Once an
executor mutation starts, cancellation waits for that job to finish before
releasing the guard, including repeated cancellation. The filesystem operation
is never retried automatically, and cancellation still propagates to the
caller. A cancelled request can therefore have saved a change without
completing activation or the configuration check: inspect the current file and
check the configuration before retrying.

## Boundaries

SSH, editors, other integrations and other processes do not acquire this
guard. Before replacing a YAML file, a final source-content comparison detects
external edits made while the result was being prepared. On a mismatch the
operation refuses the write and asks for a fresh preview. A non-cooperating
writer can still race after that comparison; this is not an operating-system
compare-and-swap. Avoid editing the same file through another interface while
applying a confirmed change.

The guard covers one component file operation. It does not make edits across
multiple files, server-side backup capture plus a write, Home Assistant
configuration validation, or activation a single transaction. Existing backup
policies, path allowlists, caller authorization and confirmation toggles remain
in force.
