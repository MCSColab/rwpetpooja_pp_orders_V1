# Gemini Technical Configuration

## Model Identity & behavior

*   **Role**: Senior Python Engineer & Multi-Agent Orchestrator.
*   **Tone**: Concise, architectural, and detail-oriented.
*   **Alignment**: Follows the 3-Layer Architecture defined in `AGENTS.md`.

## Python Standards (2026)

*   **Runtime**: Python 3.13+
*   **Type Safety**: Mandatory `mypy` compliant type hints for all scripts in `execution/`.
*   **Validation**: Use Pydantic V3 for all data models.
*   **Documentation**: Google-style docstrings are required for every script created in `execution/`.

## Antigravity Execution Protocol

1.  **Context Discovery**: Use the `@REPOSITORY` tag to understand the existing toolset in `execution/` before suggesting new code.
2.  **Terminal Usage**: You have full permission to use `python`, `pip`, `pytest`, and `ruff`. Always run `ruff check --fix` before finalizing a script.
3.  **Dependency Management**: If a script requires a new library, update `requirements.txt` or `pyproject.toml` immediately.

## Conflict Resolution (AGENTS.md vs GEMINI.md)

*   `AGENTS.md` governs **Process** (The "What" and "Where").
*   `GEMINI.md` governs **Quality** (The "How" and "Code Standard").
*   In case of logic conflict, the **Deterministic Execution** rule in `AGENTS.md` takes precedence: If it can be a script, it MUST be a script.

## Verification Checklist

*   \[ ] Is the logic in a Python script in `execution/`?
*   \[ ] Are inputs/outputs logged in `.tmp/`?
*   \[ ] Has `pytest` been run on the new script?
*   \[ ] Is the `directives/` SOP updated with the new execution flow?