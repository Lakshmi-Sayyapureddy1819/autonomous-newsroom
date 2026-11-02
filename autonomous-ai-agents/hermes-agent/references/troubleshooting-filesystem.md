# Troubleshooting Filesystem Interactions and Stale State

This document addresses issues related to filesystem interactions, particularly `stale_write_blocked` errors, and managing dispatcher state files in persistent agent workflows.

## Pitfall: `stale_write_blocked` Errors During File Modifications

**Rule:** Repeated `stale_write_blocked` errors when attempting to modify files (e.g., dispatcher state files, application code, test files) indicate a persistent environment-level issue with file interaction or caching. This prevents programmatic updates and requires manual intervention.

**Why:** The `write_file` and `patch` tools perform internal checks to ensure the file hasn't changed on disk since it was last read by the agent. If the file is modified externally, or if there are caching issues, these tools will refuse to write to prevent accidental data loss or corruption. On Windows, this can be exacerbated by file locking mechanisms or delayed file system updates.

**Diagnosis and Workarounds:**

1.  **Verify File Existence and Timestamp Manually:**
    *   **Procedure:** After an attempted file modification (e.g., using `rm -f`), immediately check if the file still exists and inspect its modification timestamp (`mtime`). An old `mtime` indicates the file was not truly removed or was recreated with stale metadata.
    *   **Command (example):** `ls -l C:\Users\Yasaswini\.local\state\newsroom-dispatch\locks/reporter.lock`

2.  **Explicit Python Unlinking for Lock Files:**
    *   **Procedure:** If shell `rm -f` proves unreliable for lock files, try using Python's `os.unlink()` directly within an `execute_code` block. This can sometimes bypass shell-related or caching issues.
    *   **Command (example):**
        ```python
        import os
        from pathlib import Path

        lock_path = Path('C:/Users/Yasaswini/.local/state/newsroom-dispatch/locks/reporter.lock')
        if lock_path.exists():
            print(f'Attempting to unlink: {lock_path}')
            try:
                os.unlink(lock_path)
                print(f'Successfully unlinked: {lock_path}')
            except Exception as e:
                print(f'Error unlinking {lock_path}: {e}')
        else:
            print(f'Lock file does not exist: {lock_path}')
        ```

3.  **Clearing Python Bytecode Cache (`__pycache__`):**
    *   **Procedure:** Stale Python bytecode can sometimes interfere with script execution, especially after code changes. Regularly clearing the `__pycache__` directories can resolve unexpected behavior.
    *   **Command (example):** `rm -rf agents/dispatcher/__pycache__`

4.  **Clearing Dispatcher State Directory:**
    *   **Procedure:** For persistent issues with dispatcher state files (e.g., `issue-14.json`), a more aggressive approach is to clear the entire dispatcher state directory. **Use with caution**, as this resets all retry counts and signatures.
    *   **Command (example):** `rm -rf C:\Users\Yasaswini\.local\state\newsroom-dispatch`

5.  **Debugging `AgentLock.acquire` Logic:**
    *   **Procedure:** When lock acquisition repeatedly fails, add verbose debugging statements within the `AgentLock.acquire` method in `dispatch.py` to trace its execution path, file existence checks, and timestamp evaluations.
    *   **Pitfall:** Remember to remove temporary debugging statements before committing.

## Pitfall: Stale Dispatcher State Files (Out-of-Sync with GitHub Labels)

**Rule:** Dispatcher state files (e.g., `issue-<number>.json`) can become out of sync with actual GitHub labels, causing the dispatcher to misinterpret ticket status and skip agent invocations (e.g., "malformed labels", "reporter is already running" when it isn't).

**Why:** External factors (manual label changes on GitHub, network issues during dispatcher updates, or prior `stale_write_blocked` errors preventing state file writes) can lead to discrepancies between the dispatcher's local state and the canonical GitHub truth.

**Resolution:**

1.  **Manual State File Correction (if direct programmatic write is blocked):**
    *   **Procedure:** If programmatic `write_file` or `patch` is blocked, manual intervention is required. Clear the problematic state file (`rm -f <path/to/issue-N.json>`) and then trigger the dispatcher. The dispatcher will re-read the canonical GitHub labels and recreate a fresh state file.
    *   **Pitfall:** This resets retry counts for that ticket.

2.  **Ensure Dispatcher Reads Canonical Truth:** The dispatcher itself should always read the *current* state from GitHub before making decisions, and its `_labels_moved` logic should accurately reflect changes on GitHub. The `dispatcher-hardening` branch incorporates improvements to this.
