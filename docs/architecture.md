q# Architecture decision record 001: Python-first v0.1

**Status:** Accepted (2026-08-18)

## Decision

Build the first useful version in Python with Textual, Rich, `nbformat`,
`jupyter_client`, `ipykernel`, and Typer.

The application is split into four boundaries:

1. `model.py` owns a typed in-memory notebook representation.
2. `storage.py` is the only layer that translates to and from `.ipynb` and
   performs atomic saves.
3. `kernel.py` translates Jupyter messages into semantic execution updates.
4. `tui.py` maps keys to actions and renders state; it never handles wire
   protocol messages or notebook JSON.

## Rationale

Python's mature Jupyter libraries remove protocol work from the product's
critical path. Textual includes a capable multiline editor, while Rich renders
Markdown, syntax, tables, and tracebacks. This lets v0.1 test the interaction
model rather than a transport implementation.

The boundaries deliberately keep a later Rust component possible: storage,
execution, or rendering can be replaced behind its API without changing the
notebook controller.

## Deferred

Cell insertion/deletion, command mode, output virtualization, non-Python
kernels, image protocols, and configuration are follow-on work. The kernel
name is already obtained from notebook metadata rather than hard-coded.

