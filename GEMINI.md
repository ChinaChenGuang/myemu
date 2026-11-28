# KEMU Workspace Guardrails

## Mandatory Official-Doc Verification (Palladium ICE & IXCOM)

When designing, editing, or reviewing anything related to Cadence Palladium (ICE, IXCOM/SA, `vavlog`, `vavhdl`, `vaelab`, `vlan`, `vhan`, `ixcom`, `xeCompile`, `xeDebug`, `xrun` SA, QEL/XEL scripts, `va.lib`, `libmaprc`, `computeFarm.json`, or `XE_*`/`DBE_HOST` env vars):

1. **Never guess CLI flags, XEL/QEL commands, file formats, or defaults from memory.**
2. **Always verify exact syntax against the local WXE 24.05 official manuals** under `/home/chen/proj/Cadence/wxe_doc/` (`xecmdref.pdf`, `compileICE.pdf`, `compileIXCOM.pdf`, `emulator.pdf`, `DebuggingDesigns.pdf`) and activate the `palladium-wxe-docs` skill before emitting specifications, templates, or wrapper code.
3. **Cite evidence**: For every new or modified Palladium tool option, QEL command, or JSON schema field, record or cite the verifying PDF filename and page number in the design doc or review summary.

## KEMU Project Invariants

- **Shell target**: Generated runner scripts use `tcsh`/`csh` (`#!/usr/bin/env tcsh`, `setenv`, `source`, explicit `$status` checks; never `bash` or `export`).
- **Strict env isolation**: Runtime environment variables and `EMU_ROOT` come solely from `database.toml` (`[env].emu_root` and `[env.vars]`); Python code must not read external shell `os.environ` for compilation/simulation paths.
- **Keep `kemu` core lean**: Standalone preprocessing utilities (filelist cleaning, `computeFarm.json` generation, DE clock-table to `clocks.qel` conversion) belong under `tools/` sharing the same `database.toml`.
- **Strict over flexible (no redundant syntax)**: Keep CLI flags, config schema, and interfaces rigid and canonical—never add redundant compatibility aliases, fallback shims, or dual-input conveniences (e.g., use `--db` only, never `-db` + `--db`). Fewer branches mean less code and lower maintenance cost; `kemu` is a simple, maintainable template-rendering and executable-script scheduling tool, not a flexible general-purpose framework.

## Beginner-Friendly Line-by-Line Code Review

When the user asks for a code review (`review` / `审查` / `讲解代码`), treat the user as a complete beginner with zero prior programming or project background and follow **interactive, function-scoped pacing**:

- **Maximum granularity = one function per turn**: **Never** dump an entire file in one response. Cover **at most one function** (or one method, or the module header/imports/constants block) per turn, walking through it **line-by-line** (or small consecutive logical chunks in exact top-to-bottom order without skipping).
- **Three explicit dimensions for every line/chunk**:
  1. **写的什么？（What is written）**: Plain-language explanation of the literal syntax, keywords, symbols, and data structures—define any technical jargon immediately.
  2. **做了什么？（What it does）**: Concrete runtime behavior—what goes in, what happens step by step, what comes out, and how it fits into the overall flow.
  3. **为什么这么写？（Why it is written this way）**: Design rationale, edge cases or bugs prevented, and why alternative simpler-looking approaches were avoided.
- **Pause & iterate after each function**: Stop after finishing the current function, state what the next function/block is, and ask the user whether they have questions, modification ideas, or want to continue. Whenever the user raises a modification idea, **immediately evaluate its impact/trade-offs and apply the fix (with verification) if agreed** before moving on to the next function.
