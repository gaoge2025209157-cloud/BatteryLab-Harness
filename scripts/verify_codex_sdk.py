"""Perform a no-research-data smoke check of the local Codex SDK lifecycle."""
from __future__ import annotations

from pathlib import Path

from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    client = Codex(CodexConfig(cwd=str(PROJECT_ROOT)))
    try:
        thread = client.thread_start(
            approval_mode=ApprovalMode.deny_all,
            sandbox=Sandbox.read_only,
            developer_instructions=(
                "Answer the user request only. Do not access files, network, or run commands."
            ),
            ephemeral=False,
        )
        result = thread.run("Return exactly: SDK_SMOKE_OK")
        status = str(result.status).casefold()
        if "completed" not in status or result.error or not result.final_response:
            raise RuntimeError(
                "Codex turn failed: status={!r}, error={!r}".format(
                    result.status, result.error
                )
            )

        restored = client.thread_resume(
            thread.id,
            approval_mode=ApprovalMode.deny_all,
            sandbox=Sandbox.read_only,
        )
        restored_snapshot = restored.read(include_turns=False)
        if not restored_snapshot:
            raise RuntimeError("Codex thread restoration returned no thread data.")

        print("SDK_SMOKE_OK")
        print("thread_lifecycle=started_and_resumed")
        print("response_chars={}".format(len(result.final_response)))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
