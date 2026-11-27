"""Strict TOML configuration parser and validator for KEMU.

Enforces strict environment isolation (never imports or reads ``os.environ``)
and validates fields against ``TOML_SPEC.md`` (Cadence WXE 24.05).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import re
import tomllib
from typing import Any


class ConfigError(ValueError):
    """Raised when ``database.toml`` violates schema, path, or semantic rules."""


_IDENT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")

VALID_TARGET_SYSTEMS = ("Z2", "Z3", "Z3_Lsystem")
VALID_FARM_NAMES = ("LSF", "NC", "custom")
VALID_IMPT_MODES = ("full", "incr")
VALID_COMP_FLOWS = ("unified", "ppc")
VALID_IXCOM_COMPILE_MODES = ("multi", "single")
VALID_IXCOM_DUMP_MODES = ("online", "offline")
VALID_PM_MODES = ("", "la", "stb", "vd")
VALID_WAVE_MODES = ("offline", "online")

TOP_SECTIONS = frozenset({
    "netlist",
    "database",
    "env",
    "emulator",
    "filelist",
    "analysis",
    "elaborate",
    "impt",
    "precomp",
    "comp",
    "ixcom",
    "sim",
    "release",
})

SECTION_KEYS: dict[str, frozenset[str]] = {
    "netlist": frozenset({"name", "design_top", "testbench_top", "platform", "desc"}),
    "database": frozenset({"name", "netlist", "netlist_dir", "design_lib", "design_top", "testbench_top", "desc"}),
    "env": frozenset({"emu_root", "setup_scripts", "bsub", "queues", "bsub_opts", "vars", "farm"}),
    "env.farm": frozenset({"farm_name", "full_design", "partitions", "buckets", "import", "dbg_prepare"}),
    "emulator": frozenset({"active", "target_system", "machines"}),
    "emulator.machine": frozenset({"host", "et3confg", "target_system"}),
    "filelist": frozenset({"delete", "replace"}),
    "analysis": frozenset({"max_workers", "bsub_opts", "queues", "vlog_opts", "vhdl_opts", "define_list", "module"}),
    "analysis.module": frozenset({"name", "worklib", "verilog_filelist", "vhdl_filelist", "define_list", "vlog_opts", "vhdl_opts"}),
    "elaborate": frozenset({"bsub_opts", "queues", "opts", "dut_opts", "tb_opts", "extra_lines"}),
    "impt": frozenset({"mode", "ref_libs", "netlist_files", "extra_netlists", "opts"}),
    "precomp": frozenset({"opts", "precompile_options", "keep_nets", "clocks_qel", "module_stubs", "instance_stubs", "user_command_pre_precomp"}),
    "comp": frozenset({
        "flow", "compiler_options", "boards", "symmetric_boards",
        "target_compile_scripts", "ice_prepare", "compile_cmd", "opts",
        "user_command_pre_comp", "user_command_post_comp", "symmetric",
    }),
    "comp.symmetric": frozenset({"emulator", "host", "file", "boards", "locations", "advanced_placements"}),
    "ixcom": frozenset({
        "compile_mode", "hw_mode", "parallel_hdlice", "dump_mode",
        "vaelab_opts", "xecompile_opts", "use_custom_impt_qel",
        "use_custom_comp_qel", "opts", "bsub_opts", "queues",
    }),
    "sim": frozenset({
        "bsub_opts", "queues", "tcl_file", "opts", "pm_mode",
        "target_relocate_script", "target_run_scripts", "run_cmd",
        "auto_exit", "user_command_post_download", "user_command_pre_run",
        "user_command_post_run", "extra_lines", "wave", "tdf",
    }),
    "sim.wave": frozenset({
        "enable", "mode", "name", "continuous_upload", "num_files",
        "time_unit", "trigger_pos", "trace_mem_size", "probe_scripts", "probes",
    }),
    "sim.tdf": frozenset({
        "name", "tdf_file", "scope", "trigger_pos", "post_trigger_samples",
        "enable1", "enable2", "counter1", "counter2", "aliases", "triggers",
        "acquire", "no_acquire", "extra_lines", "halt_on_trigger", "auto_probe",
    }),
    "release": frozenset({"dest_dir", "db_prefix", "include", "exclude"}),
}

INLINE_TDF_RENDER_FIELDS = ("scope", "triggers", "acquire", "no_acquire", "aliases", "extra_lines")


def _norm_posix(path_str: str) -> str:
    """Lexically normalize a POSIX path without reading filesystem or env."""
    return str(PurePosixPath(path_str))


def resolve_db_path(db_arg: str) -> Path:
    """Resolve CLI ``-db <db_name>`` (auto-appending ``.toml`` when omitted)."""
    text = db_arg.strip()
    if not text:
        raise ConfigError("CLI -db argument must not be empty.")
    if not text.endswith(".toml"):
        text = f"{text}.toml"
    path = Path(text)
    if not path.is_file():
        raise ConfigError(f"Database configuration file not found: {path}")
    return path


def expand_env_vars(value: str, env_map: dict[str, str], field_path: str) -> str:
    """Expand ``$VAR`` / ``${VAR}`` strictly using ``env_map`` (no ``os.environ``)."""

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1) or match.group(2)
        if name not in env_map:
            defined = ", ".join(sorted(env_map.keys())) or "<none>"
            raise ConfigError(
                f"{field_path}: undefined variable '${name}'. "
                f"Only [env].emu_root and [env.vars] are visible ({defined})."
            )
        return env_map[name]

    return _VAR_RE.sub(_replace, value)


def resolve_path(raw: str, emu_root: Path, env_map: dict[str, str], field_path: str) -> str:
    """Expand env vars and anchor relative paths to ``emu_root``."""
    if raw == "":
        return ""
    expanded = expand_env_vars(raw, env_map, field_path)
    p = PurePosixPath(expanded)
    if p.is_absolute():
        return str(p)
    return _norm_posix(str(PurePosixPath(str(emu_root)) / p))


def resolve_cli_path(raw: str, emu_root: Path, env_map: dict[str, str], arg_name: str) -> Path:
    """Resolve a CLI path argument (``--comdir``, ``--db-path``, ``--simdir``)."""
    text = raw.strip()
    if not text:
        raise ConfigError(f"CLI {arg_name} must not be empty.")
    return Path(resolve_path(text, emu_root, env_map, f"CLI {arg_name}"))


def _check_keys(table: dict[str, Any], schema_name: str, context: str) -> None:
    allowed = SECTION_KEYS[schema_name]
    unknown = sorted(set(table.keys()) - allowed)
    if unknown:
        valid_str = ", ".join(sorted(allowed))
        raise ConfigError(
            f"[{context}] contains unknown key(s): {', '.join(unknown)}. "
            f"Valid keys: {valid_str}"
        )


def _require_table(val: Any, context: str) -> dict[str, Any]:
    if not isinstance(val, dict):
        raise ConfigError(f"[{context}] must be a TOML table.")
    return val


def _require_str(val: Any, field_path: str) -> str:
    if not isinstance(val, str):
        raise ConfigError(f"{field_path} must be a string, got {type(val).__name__}.")
    return val


def _require_bool(val: Any, field_path: str) -> bool:
    if not isinstance(val, bool):
        raise ConfigError(f"{field_path} must be a boolean, got {type(val).__name__}.")
    return val


def _require_int(val: Any, field_path: str) -> int:
    if isinstance(val, bool) or not isinstance(val, int):
        raise ConfigError(f"{field_path} must be an integer, got {type(val).__name__}.")
    return val


def _require_str_list(val: Any, field_path: str) -> list[str]:
    if not isinstance(val, list) or any(not isinstance(item, str) for item in val):
        raise ConfigError(f"{field_path} must be a list of strings.")
    return list(val)


def _check_ident(value: str, field_path: str) -> None:
    if value and not _IDENT_RE.match(value):
        raise ConfigError(
            f"{field_path}='{value}' contains invalid characters; only [A-Za-z0-9_-]+ is allowed."
        )


def _check_enum(value: str, allowed: tuple[str, ...], field_path: str) -> None:
    if value not in allowed:
        opts = ", ".join(repr(x) for x in allowed)
        raise ConfigError(f"{field_path}='{value}' is invalid; expected one of: {opts}.")


@dataclass
class NetlistConfig:
    name: str = ""
    design_top: str = ""
    testbench_top: str = ""
    platform: str = ""
    desc: str = ""


@dataclass
class DatabaseConfig:
    name: str = ""
    netlist: str = ""
    netlist_dir: str = ""
    design_lib: str = "work"
    design_top: str = ""
    testbench_top: str = ""
    desc: str = ""


@dataclass
class EnvFarmConfig:
    farm_name: str = "LSF"
    full_design: str = ""
    partitions: str = ""
    buckets: str = ""
    import_: str = ""
    dbg_prepare: str = ""


@dataclass
class EnvConfig:
    emu_root: str = ""
    setup_scripts: list[str] = field(default_factory=list)
    bsub: bool = False
    queues: list[str] = field(default_factory=list)
    bsub_opts: list[str] = field(default_factory=list)
    vars: dict[str, str] = field(default_factory=dict)
    farm: EnvFarmConfig = field(default_factory=EnvFarmConfig)


@dataclass
class EmulatorMachine:
    alias: str
    host: str
    et3confg: str = ""
    target_system: str = ""


@dataclass
class EmulatorConfig:
    active: str = ""
    target_system: str = "Z2"
    machines: dict[str, EmulatorMachine] = field(default_factory=dict)


@dataclass
class FilelistConfig:
    delete: list[str] = field(default_factory=list)
    replace: list[list[str]] = field(default_factory=list)


@dataclass
class AnalysisModule:
    name: str
    worklib: str
    verilog_filelist: list[str] = field(default_factory=list)
    vhdl_filelist: list[str] = field(default_factory=list)
    define_list: list[str] = field(default_factory=list)
    vlog_opts: list[str] = field(default_factory=list)
    vhdl_opts: list[str] = field(default_factory=list)


@dataclass
class AnalysisConfig:
    max_workers: int = 4
    bsub_opts: list[str] = field(default_factory=list)
    queues: list[str] = field(default_factory=list)
    vlog_opts: list[str] = field(default_factory=list)
    vhdl_opts: list[str] = field(default_factory=list)
    define_list: list[str] = field(default_factory=list)
    modules: list[AnalysisModule] = field(default_factory=list)


@dataclass
class ElaborateConfig:
    bsub_opts: list[str] = field(default_factory=list)
    queues: list[str] = field(default_factory=list)
    opts: list[str] = field(default_factory=list)
    dut_opts: list[str] = field(default_factory=list)
    tb_opts: list[str] = field(default_factory=list)
    extra_lines: list[str] = field(default_factory=list)


@dataclass
class ImptConfig:
    mode: str = "full"
    ref_libs: list[str] = field(default_factory=lambda: ["qtref", "generic"])
    netlist_files: list[str] = field(default_factory=list)
    extra_netlists: list[str] = field(default_factory=list)
    opts: list[str] = field(default_factory=list)


@dataclass
class PrecompConfig:
    opts: list[str] = field(default_factory=list)
    precompile_options: list[str] = field(default_factory=list)
    keep_nets: list[str] = field(default_factory=list)
    clocks_qel: str = ""
    module_stubs: list[str] = field(default_factory=list)
    instance_stubs: list[str] = field(default_factory=list)
    user_command_pre_precomp: list[str] = field(default_factory=list)


@dataclass
class CompSymmetricConfig:
    emulator: str = ""
    host: str = ""
    file: str = ""
    boards: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    advanced_placements: str = ""


@dataclass
class CompConfig:
    flow: str = "unified"
    compiler_options: list[str] = field(default_factory=list)
    boards: str = ""
    symmetric_boards: str = ""
    target_compile_scripts: list[str] = field(default_factory=list)
    ice_prepare: bool = False
    ice_prepare_explicit: bool = False
    compile_cmd: str = "compile"
    opts: list[str] = field(default_factory=list)
    user_command_pre_comp: list[str] = field(default_factory=list)
    user_command_post_comp: list[str] = field(default_factory=list)
    symmetric: list[CompSymmetricConfig] = field(default_factory=list)


@dataclass
class IxcomConfig:
    compile_mode: str = "multi"
    hw_mode: bool = True
    parallel_hdlice: int = 4
    dump_mode: str = "online"
    vaelab_opts: list[str] = field(default_factory=list)
    xecompile_opts: list[str] = field(default_factory=list)
    use_custom_impt_qel: bool = False
    use_custom_comp_qel: bool = False
    opts: list[str] = field(default_factory=list)
    bsub_opts: list[str] = field(default_factory=list)
    queues: list[str] = field(default_factory=list)


@dataclass
class SimWaveConfig:
    enable: bool = False
    mode: str = "offline"
    name: str = "wave"
    continuous_upload: bool = False
    num_files: int = 0
    time_unit: str = "ns"
    trigger_pos: int = 50
    trace_mem_size: str = ""
    probe_scripts: list[str] = field(default_factory=list)
    probes: list[str] = field(default_factory=list)


@dataclass
class SimTdfConfig:
    name: str = "trigger.tdf"
    tdf_file: str = ""
    scope: str = ""
    trigger_pos: int | None = None
    post_trigger_samples: int | None = None
    enable1: str = ""
    enable2: str = ""
    counter1: int | None = None
    counter2: int | None = None
    aliases: dict[str, str] = field(default_factory=dict)
    triggers: list[str] = field(default_factory=list)
    acquire: list[str] = field(default_factory=list)
    no_acquire: list[str] = field(default_factory=list)
    extra_lines: list[str] = field(default_factory=list)
    halt_on_trigger: bool = False
    auto_probe: bool = False
    present: bool = False


@dataclass
class SimConfig:
    bsub_opts: list[str] = field(default_factory=list)
    queues: list[str] = field(default_factory=list)
    tcl_file: str = ""
    opts: list[str] = field(default_factory=list)
    pm_mode: str = ""
    target_relocate_script: str = ""
    target_run_scripts: list[str] = field(default_factory=list)
    run_cmd: str = ""
    auto_exit: bool = False
    user_command_post_download: list[str] = field(default_factory=list)
    user_command_pre_run: list[str] = field(default_factory=list)
    user_command_post_run: list[str] = field(default_factory=list)
    extra_lines: list[str] = field(default_factory=list)
    wave: SimWaveConfig = field(default_factory=SimWaveConfig)
    tdf: SimTdfConfig = field(default_factory=SimTdfConfig)


@dataclass
class ReleaseConfig:
    dest_dir: str = ""
    db_prefix: str = "database"
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


@dataclass
class KemuConfig:
    source_path: Path
    emu_root_path: Path
    env_map: dict[str, str]
    netlist: NetlistConfig
    database: DatabaseConfig
    env: EnvConfig
    emulator: EmulatorConfig
    filelist: FilelistConfig
    analysis: AnalysisConfig
    elaborate: ElaborateConfig
    impt: ImptConfig
    precomp: PrecompConfig
    comp: CompConfig
    ixcom: IxcomConfig
    sim: SimConfig
    release: ReleaseConfig

    def active_machine(self) -> EmulatorMachine:
        """Return the active Palladium machine entry or raise ``ConfigError``."""
        if not self.emulator.active:
            raise ConfigError("[emulator].active is required for hardware compilation or simulation.")
        if self.emulator.active not in self.emulator.machines:
            avail = ", ".join(sorted(self.emulator.machines.keys())) or "<none>"
            raise ConfigError(
                f"[emulator].active='{self.emulator.active}' not found in [emulator.machines] ({avail})."
            )
        return self.emulator.machines[self.emulator.active]

    def effective_target_system(self) -> str:
        """Return active machine's target_system (or global [emulator].target_system)."""
        if self.emulator.active and self.emulator.active in self.emulator.machines:
            m = self.emulator.machines[self.emulator.active]
            if m.target_system:
                return m.target_system
        return self.emulator.target_system or "Z2"

    def effective_platform(self) -> str:
        """Return target platform for ICE elaborate (``[netlist].platform`` or emulator fallback)."""
        if self.netlist.platform:
            return self.netlist.platform
        if self.emulator.active and self.emulator.active in self.emulator.machines:
            m = self.emulator.machines[self.emulator.active]
            if m.target_system:
                return m.target_system
        return self.emulator.target_system or "Z2"

    def effective_compiler_options(self) -> list[str]:
        """Merge baseline ``['mode ice', 'visionMode FV']`` + ``[comp].compiler_options`` + PPC flow."""
        merged: list[tuple[str, str]] = [("mode", "mode ice"), ("visionMode", "visionMode FV")]
        for raw_opt in self.comp.compiler_options:
            opt = raw_opt.strip()
            if not opt:
                raise ConfigError("[comp].compiler_options must not contain empty items.")
            key = opt.split(None, 1)[0]
            replaced = False
            for idx, (existing_key, _) in enumerate(merged):
                if existing_key == key:
                    merged[idx] = (key, opt)
                    replaced = True
                    break
            if not replaced:
                merged.append((key, opt))
        if self.comp.flow == "ppc" and all(k != "distributedMulticore" for k, _ in merged):
            merged.append(("distributedMulticore", "distributedMulticore ON"))
        return [item for _, item in merged]

    def effective_ice_prepare(self) -> bool:
        """Return ``ice_prepare`` if explicitly configured, else ``bool(target_compile_scripts)``."""
        if self.comp.ice_prepare_explicit:
            return self.comp.ice_prepare
        return bool(self.comp.target_compile_scripts)

    def resolve_symmetric_configs(self) -> list[dict[str, Any]]:
        """Resolve ``[comp].symmetric_boards`` or ``[[comp.symmetric]]`` into template items."""
        if self.comp.symmetric_boards:
            active = self.active_machine()
            boards = [] if self.comp.symmetric_boards == "ALL" else [self.comp.symmetric_boards]
            return [{
                "file": active.et3confg,
                "host": "" if active.et3confg else active.host,
                "boards": boards,
                "locations": [],
                "advanced_placements": "",
            }]
        resolved: list[dict[str, Any]] = []
        for idx, sym in enumerate(self.comp.symmetric):
            file_val = sym.file
            host_val = sym.host
            if sym.emulator:
                if sym.emulator not in self.emulator.machines:
                    raise ConfigError(
                        f"[[comp.symmetric]][{idx}].emulator='{sym.emulator}' not found in [emulator.machines]."
                    )
                mach = self.emulator.machines[sym.emulator]
                file_val = mach.et3confg
                host_val = "" if mach.et3confg else mach.host
            elif not file_val and not host_val:
                active = self.active_machine()
                file_val = active.et3confg
                host_val = "" if active.et3confg else active.host
            resolved.append({
                "file": file_val,
                "host": host_val,
                "boards": list(sym.boards),
                "locations": list(sym.locations),
                "advanced_placements": sym.advanced_placements,
            })
        return resolved

    def effective_netlist_name(self) -> str:
        """Return ``[database].netlist`` if set, else ``[netlist].name``."""
        return self.database.netlist or self.netlist.name

    def netlist_workdir(self, comdir: Path) -> Path:
        """Return ``<comdir>/netlist/<netlist.name>/``."""
        if not self.netlist.name:
            raise ConfigError("[netlist].name is required to determine the netlist working directory.")
        return comdir / "netlist" / self.netlist.name

    def database_workdir(self, comdir: Path) -> Path:
        """Return ``<comdir>/database/<database.name>/``."""
        if not self.database.name:
            raise ConfigError("[database].name is required to determine the database working directory.")
        return comdir / "database" / self.database.name

    def resolve_netlist_dir(self, comdir: Path) -> Path | None:
        """Resolve frontend netlist directory from ``netlist_dir`` > ``<comdir>/netlist/<netlist>/``."""
        if self.database.netlist_dir:
            return Path(self.database.netlist_dir)
        nl_name = self.effective_netlist_name()
        if nl_name:
            return comdir / "netlist" / nl_name
        return None

    def validate_for(self, command: str, mode: str | None = None, act: str | None = None) -> None:
        """Run stage-scoped required-field validation per ``TOML_SPEC.md`` Section 4 Rule 1."""
        if command == "build" and mode == "ice":
            if act in ("analysis", "elaborate", "syn"):
                if not self.netlist.name:
                    raise ConfigError(f"[netlist].name is required for 'build ice --act {act}'.")
                if not self.netlist.design_top:
                    raise ConfigError(f"[netlist].design_top is required for 'build ice --act {act}'.")
                if act in ("analysis", "syn") and not self.analysis.modules:
                    raise ConfigError(f"At least one [[analysis.module]] is required for 'build ice --act {act}'.")
                if act in ("elaborate", "syn"):
                    _check_enum(self.effective_platform(), VALID_TARGET_SYSTEMS, "[netlist].platform")
            elif act in ("impt", "precomp", "comp"):
                if not self.database.name:
                    raise ConfigError(f"[database].name is required for 'build ice --act {act}'.")
                self.active_machine()
                has_source = bool(
                    self.database.netlist_dir
                    or self.effective_netlist_name()
                    or self.impt.netlist_files
                )
                if not has_source:
                    raise ConfigError(
                        f"Cannot locate netlist for 'build ice --act {act}': set [netlist].name, "
                        "[database].netlist, [database].netlist_dir, or [impt].netlist_files."
                    )
                if act == "comp":
                    self.resolve_symmetric_configs()
            else:
                raise ConfigError(f"Unsupported ICE build action: '{act}'.")
            return

        if command == "build" and mode == "ixcom":
            if act not in ("analysis", "swmodel", "hdlice", "xecompile", "all"):
                raise ConfigError(f"Unsupported IXCOM build action: '{act}'.")
            if self.netlist.name:
                if act in ("analysis", "all"):
                    if not self.analysis.modules:
                        raise ConfigError(f"At least one [[analysis.module]] is required for 'build ixcom --act {act}'.")
                if act != "analysis" and not self.database.name:
                    raise ConfigError(f"[database].name is required for 'build ixcom --act {act}'.")
                if not (self.netlist.design_top or self.database.design_top):
                    raise ConfigError("[database].design_top (or [netlist].design_top) is required for IXCOM build.")
            else:
                if not self.database.name:
                    raise ConfigError(f"[database].name is required for 'build ixcom --act {act}'.")
                if not self.database.design_top:
                    raise ConfigError(f"[database].design_top is required for 'build ixcom --act {act}'.")
                if act in ("analysis", "all") and not self.analysis.modules:
                    raise ConfigError(f"At least one [[analysis.module]] is required for 'build ixcom --act {act}'.")
            if self.ixcom.hw_mode and act in ("xecompile", "all"):
                self.active_machine()
            return

        if command == "sim" and mode in ("ice", "ixcom"):
            if not self.database.name:
                raise ConfigError(f"[database].name is required for 'sim {mode}'.")
            self.active_machine()
            return

        if command == "release":
            if not self.database.name:
                raise ConfigError("[database].name is required for 'release'.")
            if not self.release.dest_dir:
                raise ConfigError("[release].dest_dir is required for 'release'.")
            if not self.release.include:
                raise ConfigError("[release].include must specify at least one item for 'release'.")
            return

        raise ConfigError(f"Unknown validation target: command={command!r}, mode={mode!r}.")


def _parse_env(raw: dict[str, Any]) -> tuple[EnvConfig, Path, dict[str, str]]:
    if "env" not in raw:
        raise ConfigError("Missing required [env] section with 'emu_root'.")
    env_tbl = _require_table(raw["env"], "env")
    _check_keys(env_tbl, "env", "env")

    if "emu_root" not in env_tbl:
        raise ConfigError("[env].emu_root is required.")
    raw_root = _require_str(env_tbl["emu_root"], "[env].emu_root").strip()
    if not raw_root or not PurePosixPath(raw_root).is_absolute():
        raise ConfigError(f"[env].emu_root='{raw_root}' must be a non-empty absolute path starting with '/'.")
    if "$" in raw_root:
        raise ConfigError("[env].emu_root must not reference shell/env variables.")
    emu_root_str = _norm_posix(raw_root)
    emu_root_path = Path(emu_root_str)

    # Strict env isolation: build env_map solely from EMU_ROOT and [env.vars].
    env_map: dict[str, str] = {"EMU_ROOT": emu_root_str}
    vars_tbl = _require_table(env_tbl.get("vars", {}), "env.vars")
    parsed_vars: dict[str, str] = {}
    for k, v in vars_tbl.items():
        if not isinstance(v, str):
            raise ConfigError(f"[env.vars].{k} must be a string, got {type(v).__name__}.")
        if k == "EMU_ROOT" and _norm_posix(v) != emu_root_str:
            raise ConfigError("[env.vars].EMU_ROOT conflicts with [env].emu_root; configure EMU_ROOT in [env].emu_root only.")
        expanded_v = expand_env_vars(v, env_map, f"[env.vars].{k}")
        parsed_vars[k] = expanded_v
        env_map[k] = expanded_v
    if "XE_HOST" in parsed_vars and "XE_HOST_FILE" in parsed_vars:
        raise ConfigError("[env.vars] cannot specify both XE_HOST and XE_HOST_FILE (emulator.pdf P16).")

    setup_scripts = [
        resolve_path(s, emu_root_path, env_map, f"[env].setup_scripts[{i}]")
        for i, s in enumerate(_require_str_list(env_tbl.get("setup_scripts", []), "[env].setup_scripts"))
    ]
    bsub = _require_bool(env_tbl.get("bsub", False), "[env].bsub")
    queues = _require_str_list(env_tbl.get("queues", []), "[env].queues")
    bsub_opts = _require_str_list(env_tbl.get("bsub_opts", []), "[env].bsub_opts")

    farm_tbl = _require_table(env_tbl.get("farm", {}), "env.farm")
    _check_keys(farm_tbl, "env.farm", "env.farm")
    farm_name = _require_str(farm_tbl.get("farm_name", "LSF"), "[env.farm].farm_name")
    _check_enum(farm_name, VALID_FARM_NAMES, "[env.farm].farm_name")
    farm = EnvFarmConfig(
        farm_name=farm_name,
        full_design=_require_str(farm_tbl.get("full_design", ""), "[env.farm].full_design"),
        partitions=_require_str(farm_tbl.get("partitions", ""), "[env.farm].partitions"),
        buckets=_require_str(farm_tbl.get("buckets", ""), "[env.farm].buckets"),
        import_=_require_str(farm_tbl.get("import", ""), "[env.farm].import"),
        dbg_prepare=_require_str(farm_tbl.get("dbg_prepare", ""), "[env.farm].dbg_prepare"),
    )

    cfg = EnvConfig(
        emu_root=emu_root_str,
        setup_scripts=setup_scripts,
        bsub=bsub,
        queues=queues,
        bsub_opts=bsub_opts,
        vars=parsed_vars,
        farm=farm,
    )
    return cfg, emu_root_path, env_map


def _parse_emulator(raw: dict[str, Any], emu_root: Path, env_map: dict[str, str]) -> EmulatorConfig:
    if "emulator" not in raw:
        return EmulatorConfig()
    tbl = _require_table(raw["emulator"], "emulator")
    _check_keys(tbl, "emulator", "emulator")
    active = _require_str(tbl.get("active", ""), "[emulator].active")
    target_system = _require_str(tbl.get("target_system", "Z2"), "[emulator].target_system")
    _check_enum(target_system, VALID_TARGET_SYSTEMS, "[emulator].target_system")

    machines_tbl = _require_table(tbl.get("machines", {}), "emulator.machines")
    machines: dict[str, EmulatorMachine] = {}
    for alias, entry in machines_tbl.items():
        _check_ident(alias, f"[emulator.machines].{alias}")
        m_tbl = _require_table(entry, f"emulator.machines.{alias}")
        _check_keys(m_tbl, "emulator.machine", f"emulator.machines.{alias}")
        host = _require_str(m_tbl.get("host", ""), f"[emulator.machines.{alias}].host").strip()
        if not host:
            raise ConfigError(f"[emulator.machines.{alias}].host must be a non-empty string.")
        et3_raw = _require_str(m_tbl.get("et3confg", ""), f"[emulator.machines.{alias}].et3confg")
        et3_resolved = resolve_path(et3_raw, emu_root, env_map, f"[emulator.machines.{alias}].et3confg")
        m_ts = _require_str(m_tbl.get("target_system", ""), f"[emulator.machines.{alias}].target_system")
        if m_ts:
            _check_enum(m_ts, VALID_TARGET_SYSTEMS, f"[emulator.machines.{alias}].target_system")
        machines[alias] = EmulatorMachine(alias=alias, host=host, et3confg=et3_resolved, target_system=m_ts)

    if active and active not in machines:
        avail = ", ".join(sorted(machines.keys())) or "<none>"
        raise ConfigError(f"[emulator].active='{active}' is not defined in [emulator.machines] ({avail}).")

    return EmulatorConfig(active=active, target_system=target_system, machines=machines)


def _parse_netlist(raw: dict[str, Any]) -> NetlistConfig:
    if "netlist" not in raw:
        return NetlistConfig()
    tbl = _require_table(raw["netlist"], "netlist")
    _check_keys(tbl, "netlist", "netlist")
    name = _require_str(tbl.get("name", ""), "[netlist].name")
    _check_ident(name, "[netlist].name")
    platform = _require_str(tbl.get("platform", ""), "[netlist].platform")
    if platform:
        _check_enum(platform, VALID_TARGET_SYSTEMS, "[netlist].platform")
    return NetlistConfig(
        name=name,
        design_top=_require_str(tbl.get("design_top", ""), "[netlist].design_top"),
        testbench_top=_require_str(tbl.get("testbench_top", ""), "[netlist].testbench_top"),
        platform=platform,
        desc=_require_str(tbl.get("desc", ""), "[netlist].desc"),
    )


def _parse_database(raw: dict[str, Any], emu_root: Path, env_map: dict[str, str]) -> DatabaseConfig:
    if "database" not in raw:
        return DatabaseConfig()
    tbl = _require_table(raw["database"], "database")
    _check_keys(tbl, "database", "database")
    name = _require_str(tbl.get("name", ""), "[database].name")
    _check_ident(name, "[database].name")
    nl = _require_str(tbl.get("netlist", ""), "[database].netlist")
    _check_ident(nl, "[database].netlist")
    design_lib = _require_str(tbl.get("design_lib", "work"), "[database].design_lib")
    _check_ident(design_lib, "[database].design_lib")
    if not design_lib:
        raise ConfigError("[database].design_lib must not be empty.")
    nl_dir = resolve_path(_require_str(tbl.get("netlist_dir", ""), "[database].netlist_dir"), emu_root, env_map, "[database].netlist_dir")
    return DatabaseConfig(
        name=name,
        netlist=nl,
        netlist_dir=nl_dir,
        design_lib=design_lib,
        design_top=_require_str(tbl.get("design_top", ""), "[database].design_top"),
        testbench_top=_require_str(tbl.get("testbench_top", ""), "[database].testbench_top"),
        desc=_require_str(tbl.get("desc", ""), "[database].desc"),
    )


def _parse_filelist(raw: dict[str, Any]) -> FilelistConfig:
    if "filelist" not in raw:
        return FilelistConfig()
    tbl = _require_table(raw["filelist"], "filelist")
    _check_keys(tbl, "filelist", "filelist")
    deletes = _require_str_list(tbl.get("delete", []), "[filelist].delete")
    for idx, pat in enumerate(deletes):
        try:
            re.compile(pat)
        except re.error as exc:
            raise ConfigError(f"[filelist].delete[{idx}] invalid regex '{pat}': {exc}") from exc

    raw_replaces = tbl.get("replace", [])
    if not isinstance(raw_replaces, list):
        raise ConfigError("[filelist].replace must be a list of [old_regex, new_str] pairs.")
    replaces: list[list[str]] = []
    for idx, pair in enumerate(raw_replaces):
        if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(x, str) for x in pair):
            raise ConfigError(f"[filelist].replace[{idx}] must be a 2-element list of strings [old_regex, new_str].")
        try:
            re.compile(pair[0])
        except re.error as exc:
            raise ConfigError(f"[filelist].replace[{idx}][0] invalid regex '{pair[0]}': {exc}") from exc
        replaces.append([pair[0], pair[1]])

    return FilelistConfig(delete=deletes, replace=replaces)


def _check_defines(defines: list[str], field_path: str) -> None:
    for idx, item in enumerate(defines):
        if not item.strip():
            raise ConfigError(f"{field_path}[{idx}] must not be empty.")
        if item.strip().startswith("+define+"):
            raise ConfigError(
                f"{field_path}[{idx}]='{item}' must not include '+define+'; template prepends it automatically."
            )


def _parse_analysis(raw: dict[str, Any], emu_root: Path, env_map: dict[str, str], default_queues: list[str]) -> AnalysisConfig:
    if "analysis" not in raw:
        return AnalysisConfig(queues=list(default_queues))
    tbl = _require_table(raw["analysis"], "analysis")
    _check_keys(tbl, "analysis", "analysis")

    max_workers = _require_int(tbl.get("max_workers", 4), "[analysis].max_workers")
    if max_workers < 1:
        raise ConfigError("[analysis].max_workers must be >= 1.")
    defines = _require_str_list(tbl.get("define_list", []), "[analysis].define_list")
    _check_defines(defines, "[analysis].define_list")

    raw_mods = tbl.get("module", [])
    if not isinstance(raw_mods, list):
        raise ConfigError("[[analysis.module]] must be an array of tables.")
    seen_names: set[str] = set()
    modules: list[AnalysisModule] = []
    for idx, item in enumerate(raw_mods):
        m_tbl = _require_table(item, f"analysis.module[{idx}]")
        _check_keys(m_tbl, "analysis.module", f"analysis.module[{idx}]")
        name = _require_str(m_tbl.get("name", ""), f"[[analysis.module]][{idx}].name")
        if not name:
            raise ConfigError(f"[[analysis.module]][{idx}].name is required.")
        _check_ident(name, f"[[analysis.module]][{idx}].name")
        if name in seen_names:
            raise ConfigError(f"Duplicate [[analysis.module]] name: '{name}'.")
        seen_names.add(name)

        worklib = _require_str(m_tbl.get("worklib", name), f"[[analysis.module]][{idx}].worklib")
        if not worklib:
            raise ConfigError(f"[[analysis.module]][{idx}].worklib must not be empty.")
        _check_ident(worklib, f"[[analysis.module]][{idx}].worklib")

        vlogs = [
            resolve_path(p, emu_root, env_map, f"[[analysis.module]][{idx}].verilog_filelist[{j}]")
            for j, p in enumerate(_require_str_list(m_tbl.get("verilog_filelist", []), f"[[analysis.module]][{idx}].verilog_filelist"))
        ]
        vhdls = [
            resolve_path(p, emu_root, env_map, f"[[analysis.module]][{idx}].vhdl_filelist[{j}]")
            for j, p in enumerate(_require_str_list(m_tbl.get("vhdl_filelist", []), f"[[analysis.module]][{idx}].vhdl_filelist"))
        ]
        if not vlogs and not vhdls:
            raise ConfigError(f"[[analysis.module]] '{name}' must specify at least one of verilog_filelist or vhdl_filelist.")
        m_defs = _require_str_list(m_tbl.get("define_list", []), f"[[analysis.module]][{idx}].define_list")
        _check_defines(m_defs, f"[[analysis.module]][{idx}].define_list")

        modules.append(AnalysisModule(
            name=name,
            worklib=worklib,
            verilog_filelist=vlogs,
            vhdl_filelist=vhdls,
            define_list=m_defs,
            vlog_opts=_require_str_list(m_tbl.get("vlog_opts", []), f"[[analysis.module]][{idx}].vlog_opts"),
            vhdl_opts=_require_str_list(m_tbl.get("vhdl_opts", []), f"[[analysis.module]][{idx}].vhdl_opts"),
        ))

    return AnalysisConfig(
        max_workers=max_workers,
        bsub_opts=_require_str_list(tbl.get("bsub_opts", []), "[analysis].bsub_opts"),
        queues=_require_str_list(tbl.get("queues", default_queues), "[analysis].queues"),
        vlog_opts=_require_str_list(tbl.get("vlog_opts", []), "[analysis].vlog_opts"),
        vhdl_opts=_require_str_list(tbl.get("vhdl_opts", []), "[analysis].vhdl_opts"),
        define_list=defines,
        modules=modules,
    )


def _parse_elaborate(raw: dict[str, Any], default_queues: list[str]) -> ElaborateConfig:
    if "elaborate" not in raw:
        return ElaborateConfig(queues=list(default_queues))
    tbl = _require_table(raw["elaborate"], "elaborate")
    _check_keys(tbl, "elaborate", "elaborate")
    return ElaborateConfig(
        bsub_opts=_require_str_list(tbl.get("bsub_opts", []), "[elaborate].bsub_opts"),
        queues=_require_str_list(tbl.get("queues", default_queues), "[elaborate].queues"),
        opts=_require_str_list(tbl.get("opts", []), "[elaborate].opts"),
        dut_opts=_require_str_list(tbl.get("dut_opts", []), "[elaborate].dut_opts"),
        tb_opts=_require_str_list(tbl.get("tb_opts", []), "[elaborate].tb_opts"),
        extra_lines=_require_str_list(tbl.get("extra_lines", []), "[elaborate].extra_lines"),
    )


def _parse_impt(raw: dict[str, Any], emu_root: Path, env_map: dict[str, str]) -> ImptConfig:
    if "impt" not in raw:
        return ImptConfig()
    tbl = _require_table(raw["impt"], "impt")
    _check_keys(tbl, "impt", "impt")
    mode = _require_str(tbl.get("mode", "full"), "[impt].mode")
    _check_enum(mode, VALID_IMPT_MODES, "[impt].mode")
    nl_files = [
        resolve_path(p, emu_root, env_map, f"[impt].netlist_files[{i}]")
        for i, p in enumerate(_require_str_list(tbl.get("netlist_files", []), "[impt].netlist_files"))
    ]
    return ImptConfig(
        mode=mode,
        ref_libs=_require_str_list(tbl.get("ref_libs", ["qtref", "generic"]), "[impt].ref_libs"),
        netlist_files=nl_files,
        extra_netlists=_require_str_list(tbl.get("extra_netlists", []), "[impt].extra_netlists"),
        opts=_require_str_list(tbl.get("opts", []), "[impt].opts"),
    )


def _parse_precomp(raw: dict[str, Any], emu_root: Path, env_map: dict[str, str]) -> PrecompConfig:
    if "precomp" not in raw:
        return PrecompConfig()
    tbl = _require_table(raw["precomp"], "precomp")
    _check_keys(tbl, "precomp", "precomp")
    clocks_qel = resolve_path(
        _require_str(tbl.get("clocks_qel", ""), "[precomp].clocks_qel"),
        emu_root,
        env_map,
        "[precomp].clocks_qel",
    )
    return PrecompConfig(
        opts=_require_str_list(tbl.get("opts", []), "[precomp].opts"),
        precompile_options=_require_str_list(tbl.get("precompile_options", []), "[precomp].precompile_options"),
        keep_nets=_require_str_list(tbl.get("keep_nets", []), "[precomp].keep_nets"),
        clocks_qel=clocks_qel,
        module_stubs=_require_str_list(tbl.get("module_stubs", []), "[precomp].module_stubs"),
        instance_stubs=_require_str_list(tbl.get("instance_stubs", []), "[precomp].instance_stubs"),
        user_command_pre_precomp=_require_str_list(tbl.get("user_command_pre_precomp", []), "[precomp].user_command_pre_precomp"),
    )


def _parse_comp(raw: dict[str, Any], emu_root: Path, env_map: dict[str, str], machines: dict[str, EmulatorMachine]) -> CompConfig:
    if "comp" not in raw:
        return CompConfig()
    tbl = _require_table(raw["comp"], "comp")
    _check_keys(tbl, "comp", "comp")

    flow = _require_str(tbl.get("flow", "unified"), "[comp].flow")
    _check_enum(flow, VALID_COMP_FLOWS, "[comp].flow")

    compiler_options = _require_str_list(tbl.get("compiler_options", []), "[comp].compiler_options")
    for idx, opt in enumerate(compiler_options):
        if not opt.strip():
            raise ConfigError(f"[comp].compiler_options[{idx}] must not be empty.")

    symmetric_boards = _require_str(tbl.get("symmetric_boards", ""), "[comp].symmetric_boards")
    raw_sym = tbl.get("symmetric", [])
    if not isinstance(raw_sym, list):
        raise ConfigError("[[comp.symmetric]] must be an array of tables.")
    if symmetric_boards and raw_sym:
        raise ConfigError("[comp].symmetric_boards and [[comp.symmetric]] cannot be configured together.")

    sym_list: list[CompSymmetricConfig] = []
    for idx, item in enumerate(raw_sym):
        s_tbl = _require_table(item, f"comp.symmetric[{idx}]")
        _check_keys(s_tbl, "comp.symmetric", f"comp.symmetric[{idx}]")
        em = _require_str(s_tbl.get("emulator", ""), f"[[comp.symmetric]][{idx}].emulator")
        host = _require_str(s_tbl.get("host", ""), f"[[comp.symmetric]][{idx}].host")
        file_raw = _require_str(s_tbl.get("file", ""), f"[[comp.symmetric]][{idx}].file")
        if sum(bool(x) for x in (em, host, file_raw)) > 1:
            raise ConfigError(
                f"[[comp.symmetric]][{idx}]: 'emulator', 'host', and 'file' are mutually exclusive."
            )
        if em and em not in machines:
            raise ConfigError(f"[[comp.symmetric]][{idx}].emulator='{em}' is not defined in [emulator.machines].")
        s_boards = _require_str_list(s_tbl.get("boards", []), f"[[comp.symmetric]][{idx}].boards")
        s_locs = _require_str_list(s_tbl.get("locations", []), f"[[comp.symmetric]][{idx}].locations")
        adv = _require_str(s_tbl.get("advanced_placements", ""), f"[[comp.symmetric]][{idx}].advanced_placements")
        if adv and not s_boards:
            raise ConfigError(
                f"[[comp.symmetric]][{idx}].advanced_placements requires non-empty 'boards' (emulator.pdf P28)."
            )
        file_resolved = resolve_path(file_raw, emu_root, env_map, f"[[comp.symmetric]][{idx}].file")
        sym_list.append(CompSymmetricConfig(
            emulator=em,
            host=host,
            file=file_resolved,
            boards=s_boards,
            locations=s_locs,
            advanced_placements=adv,
        ))

    target_scripts = [
        resolve_path(p, emu_root, env_map, f"[comp].target_compile_scripts[{i}]")
        for i, p in enumerate(_require_str_list(tbl.get("target_compile_scripts", []), "[comp].target_compile_scripts"))
    ]
    ice_prepare_explicit = "ice_prepare" in tbl
    ice_prepare = _require_bool(tbl["ice_prepare"], "[comp].ice_prepare") if ice_prepare_explicit else bool(target_scripts)

    return CompConfig(
        flow=flow,
        compiler_options=compiler_options,
        boards=_require_str(tbl.get("boards", ""), "[comp].boards"),
        symmetric_boards=symmetric_boards,
        target_compile_scripts=target_scripts,
        ice_prepare=ice_prepare,
        ice_prepare_explicit=ice_prepare_explicit,
        compile_cmd=_require_str(tbl.get("compile_cmd", "compile"), "[comp].compile_cmd"),
        opts=_require_str_list(tbl.get("opts", []), "[comp].opts"),
        user_command_pre_comp=_require_str_list(tbl.get("user_command_pre_comp", []), "[comp].user_command_pre_comp"),
        user_command_post_comp=_require_str_list(tbl.get("user_command_post_comp", []), "[comp].user_command_post_comp"),
        symmetric=sym_list,
    )


def _parse_ixcom(raw: dict[str, Any], default_queues: list[str]) -> IxcomConfig:
    if "ixcom" not in raw:
        return IxcomConfig(queues=list(default_queues))
    tbl = _require_table(raw["ixcom"], "ixcom")
    _check_keys(tbl, "ixcom", "ixcom")
    c_mode = _require_str(tbl.get("compile_mode", "multi"), "[ixcom].compile_mode")
    _check_enum(c_mode, VALID_IXCOM_COMPILE_MODES, "[ixcom].compile_mode")
    d_mode = _require_str(tbl.get("dump_mode", "online"), "[ixcom].dump_mode")
    _check_enum(d_mode, VALID_IXCOM_DUMP_MODES, "[ixcom].dump_mode")
    par = _require_int(tbl.get("parallel_hdlice", 4), "[ixcom].parallel_hdlice")
    if par < 0:
        raise ConfigError("[ixcom].parallel_hdlice must be >= 0.")
    return IxcomConfig(
        compile_mode=c_mode,
        hw_mode=_require_bool(tbl.get("hw_mode", True), "[ixcom].hw_mode"),
        parallel_hdlice=par,
        dump_mode=d_mode,
        vaelab_opts=_require_str_list(tbl.get("vaelab_opts", []), "[ixcom].vaelab_opts"),
        xecompile_opts=_require_str_list(tbl.get("xecompile_opts", []), "[ixcom].xecompile_opts"),
        use_custom_impt_qel=_require_bool(tbl.get("use_custom_impt_qel", False), "[ixcom].use_custom_impt_qel"),
        use_custom_comp_qel=_require_bool(tbl.get("use_custom_comp_qel", False), "[ixcom].use_custom_comp_qel"),
        opts=_require_str_list(tbl.get("opts", []), "[ixcom].opts"),
        bsub_opts=_require_str_list(tbl.get("bsub_opts", []), "[ixcom].bsub_opts"),
        queues=_require_str_list(tbl.get("queues", default_queues), "[ixcom].queues"),
    )


def _parse_sim(raw: dict[str, Any], emu_root: Path, env_map: dict[str, str], default_queues: list[str]) -> SimConfig:
    if "sim" not in raw:
        return SimConfig(queues=list(default_queues))
    tbl = _require_table(raw["sim"], "sim")
    _check_keys(tbl, "sim", "sim")

    pm_mode = _require_str(tbl.get("pm_mode", ""), "[sim].pm_mode")
    _check_enum(pm_mode, VALID_PM_MODES, "[sim].pm_mode")

    wave_tbl = _require_table(tbl.get("wave", {}), "sim.wave")
    _check_keys(wave_tbl, "sim.wave", "sim.wave")
    w_mode = _require_str(wave_tbl.get("mode", "offline"), "[sim.wave].mode")
    _check_enum(w_mode, VALID_WAVE_MODES, "[sim.wave].mode")
    num_files = _require_int(wave_tbl.get("num_files", 0), "[sim.wave].num_files")
    if num_files < 0:
        raise ConfigError("[sim.wave].num_files must be >= 0.")
    w_trig_pos = _require_int(wave_tbl.get("trigger_pos", 50), "[sim.wave].trigger_pos")
    if not (0 <= w_trig_pos <= 100):
        raise ConfigError("[sim.wave].trigger_pos must be in 0..100.")
    wave = SimWaveConfig(
        enable=_require_bool(wave_tbl.get("enable", False), "[sim.wave].enable"),
        mode=w_mode,
        name=_require_str(wave_tbl.get("name", "wave"), "[sim.wave].name"),
        continuous_upload=_require_bool(wave_tbl.get("continuous_upload", False), "[sim.wave].continuous_upload"),
        num_files=num_files,
        time_unit=_require_str(wave_tbl.get("time_unit", "ns"), "[sim.wave].time_unit"),
        trigger_pos=w_trig_pos,
        trace_mem_size=_require_str(wave_tbl.get("trace_mem_size", ""), "[sim.wave].trace_mem_size"),
        probe_scripts=[
            resolve_path(p, emu_root, env_map, f"[sim.wave].probe_scripts[{i}]")
            for i, p in enumerate(_require_str_list(wave_tbl.get("probe_scripts", []), "[sim.wave].probe_scripts"))
        ],
        probes=_require_str_list(wave_tbl.get("probes", []), "[sim.wave].probes"),
    )

    tdf_present = "tdf" in tbl
    tdf_tbl = _require_table(tbl.get("tdf", {}), "sim.tdf")
    _check_keys(tdf_tbl, "sim.tdf", "sim.tdf")
    tdf_file_raw = _require_str(tdf_tbl.get("tdf_file", ""), "[sim.tdf].tdf_file")
    tdf_trig_pos = _require_int(tdf_tbl["trigger_pos"], "[sim.tdf].trigger_pos") if "trigger_pos" in tdf_tbl else None
    if tdf_trig_pos is not None and not (0 <= tdf_trig_pos <= 100):
        raise ConfigError("[sim.tdf].trigger_pos must be in 0..100.")
    post_samples = _require_int(tdf_tbl["post_trigger_samples"], "[sim.tdf].post_trigger_samples") if "post_trigger_samples" in tdf_tbl else None
    if post_samples is not None and post_samples < 0:
        raise ConfigError("[sim.tdf].post_trigger_samples must be >= 0.")
    if tdf_trig_pos is not None and post_samples is not None:
        raise ConfigError("[sim.tdf].trigger_pos and post_trigger_samples are mutually exclusive (SDL.pdf P137, P139).")

    aliases_tbl = _require_table(tdf_tbl.get("aliases", {}), "sim.tdf.aliases")
    aliases: dict[str, str] = {}
    for k, v in aliases_tbl.items():
        if not isinstance(v, str):
            raise ConfigError(f"[sim.tdf.aliases].{k} must be a string.")
        aliases[k] = v

    acquire = _require_str_list(tdf_tbl.get("acquire", []), "[sim.tdf].acquire")
    no_acquire = _require_str_list(tdf_tbl.get("no_acquire", []), "[sim.tdf].no_acquire")
    if acquire and no_acquire:
        raise ConfigError("[sim.tdf].acquire and no_acquire are mutually exclusive (SDL.pdf P147, P149).")

    triggers = _require_str_list(tdf_tbl.get("triggers", []), "[sim.tdf].triggers")
    extra_lines = _require_str_list(tdf_tbl.get("extra_lines", []), "[sim.tdf].extra_lines")
    scope = _require_str(tdf_tbl.get("scope", ""), "[sim.tdf].scope")
    if tdf_file_raw and any(bool(x) for x in (scope, triggers, acquire, no_acquire, aliases, extra_lines)):
        raise ConfigError(
            "[sim.tdf].tdf_file cannot be combined with inline render fields "
            f"({', '.join(INLINE_TDF_RENDER_FIELDS)})."
        )

    tdf = SimTdfConfig(
        name=_require_str(tdf_tbl.get("name", "trigger.tdf"), "[sim.tdf].name"),
        tdf_file=resolve_path(tdf_file_raw, emu_root, env_map, "[sim.tdf].tdf_file"),
        scope=scope,
        trigger_pos=tdf_trig_pos,
        post_trigger_samples=post_samples,
        enable1=_require_str(tdf_tbl.get("enable1", ""), "[sim.tdf].enable1"),
        enable2=_require_str(tdf_tbl.get("enable2", ""), "[sim.tdf].enable2"),
        counter1=_require_int(tdf_tbl["counter1"], "[sim.tdf].counter1") if "counter1" in tdf_tbl else None,
        counter2=_require_int(tdf_tbl["counter2"], "[sim.tdf].counter2") if "counter2" in tdf_tbl else None,
        aliases=aliases,
        triggers=triggers,
        acquire=acquire,
        no_acquire=no_acquire,
        extra_lines=extra_lines,
        halt_on_trigger=_require_bool(tdf_tbl.get("halt_on_trigger", False), "[sim.tdf].halt_on_trigger"),
        auto_probe=_require_bool(tdf_tbl.get("auto_probe", False), "[sim.tdf].auto_probe"),
        present=tdf_present,
    )

    return SimConfig(
        bsub_opts=_require_str_list(tbl.get("bsub_opts", []), "[sim].bsub_opts"),
        queues=_require_str_list(tbl.get("queues", default_queues), "[sim].queues"),
        tcl_file=resolve_path(_require_str(tbl.get("tcl_file", ""), "[sim].tcl_file"), emu_root, env_map, "[sim].tcl_file"),
        opts=_require_str_list(tbl.get("opts", []), "[sim].opts"),
        pm_mode=pm_mode,
        target_relocate_script=resolve_path(
            _require_str(tbl.get("target_relocate_script", ""), "[sim].target_relocate_script"),
            emu_root,
            env_map,
            "[sim].target_relocate_script",
        ),
        target_run_scripts=[
            resolve_path(p, emu_root, env_map, f"[sim].target_run_scripts[{i}]")
            for i, p in enumerate(_require_str_list(tbl.get("target_run_scripts", []), "[sim].target_run_scripts"))
        ],
        run_cmd=_require_str(tbl.get("run_cmd", ""), "[sim].run_cmd"),
        auto_exit=_require_bool(tbl.get("auto_exit", False), "[sim].auto_exit"),
        user_command_post_download=_require_str_list(tbl.get("user_command_post_download", []), "[sim].user_command_post_download"),
        user_command_pre_run=_require_str_list(tbl.get("user_command_pre_run", []), "[sim].user_command_pre_run"),
        user_command_post_run=_require_str_list(tbl.get("user_command_post_run", []), "[sim].user_command_post_run"),
        extra_lines=_require_str_list(tbl.get("extra_lines", []), "[sim].extra_lines"),
        wave=wave,
        tdf=tdf,
    )


def _parse_release(raw: dict[str, Any], emu_root: Path, env_map: dict[str, str]) -> ReleaseConfig:
    if "release" not in raw:
        return ReleaseConfig()
    tbl = _require_table(raw["release"], "release")
    _check_keys(tbl, "release", "release")
    db_prefix = _require_str(tbl.get("db_prefix", "database"), "[release].db_prefix")
    _check_ident(db_prefix, "[release].db_prefix")
    if not db_prefix:
        raise ConfigError("[release].db_prefix must not be empty.")
    dest_dir = resolve_path(_require_str(tbl.get("dest_dir", ""), "[release].dest_dir"), emu_root, env_map, "[release].dest_dir")
    return ReleaseConfig(
        dest_dir=dest_dir,
        db_prefix=db_prefix,
        include=_require_str_list(tbl.get("include", []), "[release].include"),
        exclude=_require_str_list(tbl.get("exclude", []), "[release].exclude"),
    )


def load_config(db_arg: str) -> KemuConfig:
    """Load, resolve, and strictly validate a ``database.toml`` configuration file."""
    path = resolve_db_path(db_arg)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Failed to parse TOML '{path}': {exc}") from exc

    unknown_top = sorted(set(raw.keys()) - TOP_SECTIONS)
    if unknown_top:
        valid_str = ", ".join(sorted(TOP_SECTIONS))
        raise ConfigError(
            f"Unknown top-level section(s) in '{path}': {', '.join(unknown_top)}. Valid sections: {valid_str}"
        )

    env_cfg, emu_root_path, env_map = _parse_env(raw)
    emulator_cfg = _parse_emulator(raw, emu_root_path, env_map)
    netlist_cfg = _parse_netlist(raw)
    database_cfg = _parse_database(raw, emu_root_path, env_map)
    filelist_cfg = _parse_filelist(raw)
    analysis_cfg = _parse_analysis(raw, emu_root_path, env_map, env_cfg.queues)
    elaborate_cfg = _parse_elaborate(raw, env_cfg.queues)
    impt_cfg = _parse_impt(raw, emu_root_path, env_map)
    precomp_cfg = _parse_precomp(raw, emu_root_path, env_map)
    comp_cfg = _parse_comp(raw, emu_root_path, env_map, emulator_cfg.machines)
    ixcom_cfg = _parse_ixcom(raw, env_cfg.queues)
    sim_cfg = _parse_sim(raw, emu_root_path, env_map, env_cfg.queues)
    release_cfg = _parse_release(raw, emu_root_path, env_map)

    return KemuConfig(
        source_path=path,
        emu_root_path=emu_root_path,
        env_map=env_map,
        netlist=netlist_cfg,
        database=database_cfg,
        env=env_cfg,
        emulator=emulator_cfg,
        filelist=filelist_cfg,
        analysis=analysis_cfg,
        elaborate=elaborate_cfg,
        impt=impt_cfg,
        precomp=precomp_cfg,
        comp=comp_cfg,
        ixcom=ixcom_cfg,
        sim=sim_cfg,
        release=release_cfg,
    )
