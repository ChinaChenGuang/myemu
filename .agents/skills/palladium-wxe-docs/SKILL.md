---
name: palladium-wxe-docs
description: >-
  Official Cadence Palladium Z2/Z3 (WXE 24.05) documentation lookup workflow and
  verified syntax reference for ICE, IXCOM (SA), emulator/computeFarm, xeDebug,
  and xecmdref. Use this skill whenever writing, reviewing, or designing Palladium
  configs, Jinja2 templates, QEL/XEL scripts, or CLI wrappers for vavlog, vavhdl,
  vaelab, vlan, vhan, ixcom, xeCompile, xeDebug, or computeFarm.json.
---

# Cadence Palladium (WXE 24.05) Official Docs Lookup & Reference

## 1. Authoritative Local Manuals (`/home/chen/proj/Cadence/wxe_doc/`)

| Manual | Scope | Use For |
|---|---|---|
| `xecmdref.pdf` | **Command Reference (Source of Truth)** | Exact syntax/flags for `xeCompile`, `xeDebug`, and all XEL/QEL commands (`design`, `importOption`, `netlistFile`, `designImport`, `compilerOption`, `precompileOption`, `keepNet`, `emulatorConfiguration`, `compile`, `compileFind`, `debug`, `host`) |
| `compileICE.pdf` | **ICE Compilation Flow** | `va.lib`, `vavlog`, `vavhdl`, `vaelab`, design setup, precompile, unified vs PPC flow |
| `compileIXCOM.pdf` | **IXCOM / SA Flow** | Single-step vs multi-step (`vlan`, `vhan`, `libmaprc`, `-makelib`), `ixcom -ua +dut+... -target ...`, `ixcom.qel`, `compilerOptions.qel` |
| `emulator.pdf` | **Emulator & Compute Farm** | `emulatorConfiguration` (`host` vs `file`), `*.et3confg`, `XE_HOST` / `XE_HOST_FILE` / `XE_BOARDS` / `DBE_HOST`, symmetric compile, `.bp`/`.br`, `computeFarm.json`, LSF |
| `DebuggingDesigns.pdf` | **Runtime & Debugging** | `xeDebug` modes (GUI/script/offline), multi-session directory layout, ICE & SA debug sequences |
| `ClockingICE_SA.pdf` | **Clocking** | SCM / CAKE 1X / 2X / 0.5X modes, clock constraints |
| `DisCompICE.pdf` | **Distributed Compile** | PPC, LSF/NC distributed synthesis and compile |

## 2. Mandatory Lookup Procedure

Before writing or changing any Palladium command, flag, QEL line, or config schema:

1. **Locate the section** via outline:
   ```bash
   mutool show /home/chen/proj/Cadence/wxe_doc/<manual>.pdf outline | grep -i "<keyword>"
   ```
2. **Extract and read exact pages** (never extrapolate flags from memory or Xcelium/VCS habits):
   ```bash
   pdftotext /home/chen/proj/Cadence/wxe_doc/<manual>.pdf - | python3 -c "
   import sys
   pages = sys.stdin.read().split('\x0c')
   for i, p in enumerate(pages, 1):
       if '<keyword>' in p:
           print(f'P{i}:', [l.strip() for l in p.splitlines() if l.strip()][:3])
   "
   ```
   Then print the full text of the matched pages and verify exact flag spelling, argument order, and mutual exclusions.
3. **Cite the PDF filename and page number** when documenting or proposing changes.

## 3. Verified WXE 24.05 High-Risk Pitfalls

### ICE Frontend (`compileICE.pdf` P49–P68)
- Library map file is **`va.lib`** (`DEFINE <logical_lib> <dir>`), not `cds.lib`.
- Log flag for `vavlog` / `vavhdl` / `vaelab` is **`-logFile <log_file>`** (`vavhdl` and `vaelab` do not accept `-l`).
- `vavhdl` filelist/options file is **`-file <arg>`**; VHDL standards are **`-V2008`** / **`-V1987`** (not `-v93`); concurrent session locking uses `-lock`.
- `vaelab` takes `<topModule>` as a **positional argument** (no `-top`); cross-library references use **`-refLib <arg>`** (no `-liblist`); gate-level Verilog output is `-outputVlog <file>`; platform is `-Platform <z1|z2|z3>`; native LSF parallelization is `-parallelLSFMultiBsub <N>`.

### ICE Backend & XEL/QEL (`compileICE.pdf` P15–P18, P93–P94, P117–P118; `xecmdref.pdf` P194–P407)
- `xeCompile` CLI uses **`-log <log_file>`** (not `-l`), platform `-z2` / `-z3` / `-z3_Lsystem`, and `-checksyntax`.
- Netlist import uses `importOption { mode full|incr } { library <lib> }`, `refLib ...`, `netlistFile { verilog <file> }`, and `designImport [-useLSF]` (not `import -format edif`).
- `precompile` sequence opens `design <lib> <cell>`, sets **`compilerOption -add {mode ice|vd}`** (mandatory; missing causes `ERROR (legacy-30039)`), `precompileOption -add ...`, `keepNet -add ...`, sources external `clocks.qel` if needed, and runs `precompile`.
- `emulatorConfiguration -add {host <hostname> | file <et3confg_path>} {boards <sub_board>}`: `host` and `file` are mutually exclusive; `boards` also supports `'*'` for automatic domain calculation (`emulator.pdf` P15–P20, `xecmdref.pdf` P353–P354).

### IXCOM / SA Flow (`compileIXCOM.pdf` P17–P50, P189–P216; `emulator.pdf` P15–P16)
- Multi-step flow uses `libmaprc` + `vlan` (supports `-parallelBlock start/stop`) + `vhan`; single-step flow uses `-makelib <dir>[:<lib>] ... -endlib`.
- Hardware compilation uses `ixcom -ua +dut+<dut_top> -top <tb_top>` with staged `-target <ixvcg|swmodel|hdlice|xecompile|xecompile:designImport|xecompile:precompile|xecompile:et3pass1|xecompile:et3pass2>`.
- IXCOM invokes `xeCompile` on `<XE_Install_DIR>/share/vxe/etc/qel/ixcom.qel` and reads local `compilerOptions.qel`; avoid overriding `compile.qel` unless strictly required (`compileIXCOM.pdf` P49).
- SA mode selects hardware via `XE_HOST` (or mutually exclusive `XE_HOST_FILE`), `XE_BOARDS`, and `DBE_HOST` (`emulator.pdf` P15–P16).

### `computeFarm.json` (`emulator.pdf` P117–P120)
- Official keys: `"farmName"` (`"LSF"`, `"NC"`, or `"custom"`) and `"farmOptions"` (`"FullDesign"`, `"Partitions"`, `"Buckets"`, `"Import"`, `"dbgPrepare"`).
- PPC flow requires `set PPC(computeFarm) "auto"` prior to `compile` / `compileFind`.

### Runtime `xeDebug` (`DebuggingDesigns.pdf` P27–P31; `xecmdref.pdf` P202–P203)
- Batch/script mode is the default when `-gui` is omitted (no `-nc` flag; suppress echo with `-noecho`).
- CLI supports `-z2|-z3`, `-host <host>`, `-session <name>`, `-log <log_file>`, `-init <tcl_file>`, `-input <script|@cmds>`.
- Inside ICE script, open DB with `debug <db_path>` and bind host with `host <emu_host> -path [pwd]`.

## 4. Validation Checklist

1. Confirm every emitted CLI flag and XEL command directly matches `xecmdref.pdf` or the corresponding flow manual (`compileICE.pdf` / `compileIXCOM.pdf` / `emulator.pdf` / `DebuggingDesigns.pdf`).
2. When Palladium binaries are installed in the target environment, validate generated QEL scripts with `xeCompile -checksyntax <script.qel>`.
