# File manager: rules, permissions and limits (Milestone 3)

Code: `ossim/managers/file/fs.py` (the file system) and `ossim/managers/file/manager.py` (the manager that runs scripts
and process requests). Everything lives in Python objects. No host path is opened, so a script that names a real file
(for example `cat /etc/passwd`) only ever looks inside the simulated tree.

## Commands (spec 4.3)

| Command | Arguments | Rule |
| --- | --- | --- |
| `mkdir` | path | Parent must exist (no `-p`). Duplicate names are rejected. |
| `mkfile` | path | Creates an empty file. Parent must exist. |
| `ls` | [path] (default `/`) | Directory: names sorted, directories end in `/`. A file prints its own name. |
| `write` | path text | Replaces the content. The file must already exist (use `mkfile` first). |
| `append` | path text | Adds to the end. The file must already exist. |
| `cat` | path | Prints the content and counts the bytes read. |
| `rm` | path | Files only. A directory gives `is a directory`. |
| `rmdir` | path | Empty directories only. The root can never be removed. |

Every error leaves the tree unchanged. Error messages name the path, for example `already exists: /docs`,
`no such file: /docs/missing.txt`, `directory not empty: /docs`, `no such directory: /nodir`, `is a directory: /docs`.

## Paths and names

Paths must be absolute (start with `/`). `.` and `..` are resolved, doubled slashes collapse, and `..` above the root
is an error (`path escapes the root`). Names use letters, digits, `.`, `_`, `-` and are at most 64 characters.
Relative paths are rejected (`path must be absolute`). There is no current-directory command.

## Limits (stress boundaries)

10,000 files and directories, 1,000,000 bytes per file, 10,000,000 bytes in total, path depth 32, and 2,000 script
lines through the dashboard. Hitting a limit is a safe error, not a crash.

## Metadata and permissions

Each node keeps owner, group, mode (three octal digits), size in UTF-8 bytes, and created and modified times (ticks;
1 tick = 0.1 ms). Open-handle counts are not modeled.

* New files are mode 640, new directories 750, the root is 755 owned by `admin`.
* Users map to groups (default: admin to admin, alice and bob to staff, guest to guests). Users listed as admins skip
  every check. A command run with no user is a system command and is never checked.
* Checks use owner bits if the user owns the node, otherwise group bits if the user is in its group, otherwise the
  other bits. `ls` and `cat` need read; `write` and `append` need write on the file; `mkdir`, `mkfile`, `rm` and
  `rmdir` need write on the parent directory. Execute (traverse) permission is not checked.
* A refused command has outcome `denied` and severity `warning`. It is not counted as a failed command, so
  `succeeded + failed + denied = operations`.
* Full users, roles, login and audit are Milestone 4 (Security manager). This is the minimum needed for "authorized
  process file requests".

## Time and events

A command costs its latency (defaults in ticks: mkdir 20, ls 10, mkfile 20, write 30, append 30, cat 10, rm 20,
rmdir 20). The manager serves one command at a time, so a command that arrives while another is being served starts
when that one finishes. Each command emits one `FILE_OP` event. A command issued by a process also emits `BLOCK` when
it starts and `UNBLOCK` (waiting to ready) when it is served.

## Metrics

Operations, succeeded, failed, denied, bytes read and written, files and directories created and deleted, storage
used, node count, average latency (ms), plus a per-command table of counts and latency (`snapshot()["per_command"]`).
Export: `export("csv")` is the chronological operation log, `export("json")` is snapshot + metrics + events.
