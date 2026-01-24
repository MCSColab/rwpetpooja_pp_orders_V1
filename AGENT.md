# Agent Instructions: 3-Layer Orchestrator

> This file defines the operational philosophy. For technical implementation rules, see GEMINI.md.

You operate within a 3-layer architecture. Your primary goal is to minimize probabilistic LLM drift by pushing logic into deterministic Python execution.

## The 3-Layer Architecture

**Layer 1: Directive (SOPs in `directives/`)**

*   High-level intent. If a task lacks a directive, your first step is to draft one.

**Layer 2: Orchestration (Decision Making - Gemini)**

*   You are the glue. You must never perform data processing or heavy logic in the chat window. You must delegate to Layer 3.

**Layer 3: Execution (Deterministic Python in `execution/`)**

*   All production code lives here. You are authorized to create, debug, and run these scripts using the Antigravity terminal.

## Operating Principles

1.  **Tool-Centricity**: Before answering "How do I...", check `execution/`. If no tool exists, write a Python script to perform the task.
2.  **The "Plan-then-Code" Loop**:
    *   State the intent.
    *   Check `directives/`.
    *   Execute/Create Python script in `execution/`.
    *   Verify output.
3.  **Self-Annealing**: If a Python script fails, read the stack trace, fix the script in `execution/`, and update the corresponding `directives/` file to prevent future regressions.

## Workspace Rules

*   **Intermediates**: All processing data must stay in `.tmp/`.
*   **Persistence**: Final results must be pushed to Google Workspace (Sheets/Docs) via `execution/` scripts using local `credentials.json`.
*   **Safety**: Do not overwrite existing `execution/` scripts without creating a `.bak` or checking Git status.
