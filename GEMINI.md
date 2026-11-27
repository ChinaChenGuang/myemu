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
