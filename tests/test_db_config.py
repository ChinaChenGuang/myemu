"""Unit tests for kemu_src.db_config."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from kemu_src.db_config import ConfigError, load_config, resolve_cli_path, resolve_db_path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"


def _write_toml(tmp_dir: Path, name: str, content: str) -> Path:
    path = tmp_dir / name
    path.write_text(content, encoding="utf-8")
    return path


_MIN_ENV = """
[env]
emu_root = '/proj/soc/emu'
"""


class TestDbConfigExamples(unittest.TestCase):
    def test_ice_single_example_validates_all_stages(self) -> None:
        cfg = load_config(str(EXAMPLES_DIR / "ice_database"))
        self.assertEqual(cfg.source_path, EXAMPLES_DIR / "ice_database.toml")
        for act in ("analysis", "elaborate", "syn", "impt", "precomp", "comp"):
            cfg.validate_for("build", mode="ice", act=act)
        cfg.validate_for("sim", mode="ice")
        cfg.validate_for("release")

        comdir = Path("/proj/soc/emu/work_2607")
        self.assertEqual(cfg.netlist_workdir(comdir), comdir / "netlist" / "soc_rtl_v1")
        self.assertEqual(cfg.database_workdir(comdir), comdir / "database" / "base")
        self.assertEqual(cfg.resolve_netlist_dir(comdir), comdir / "netlist" / "soc_rtl_v1")

    def test_ice_decoupled_examples(self) -> None:
        nl_cfg = load_config(str(EXAMPLES_DIR / "ice_netlist.toml"))
        for act in ("analysis", "elaborate", "syn"):
            nl_cfg.validate_for("build", mode="ice", act=act)
        self.assertEqual(nl_cfg.effective_platform(), "Z2")

        db_cfg = load_config(str(EXAMPLES_DIR / "ice_db_fv"))
        for act in ("impt", "precomp", "comp"):
            db_cfg.validate_for("build", mode="ice", act=act)
        db_cfg.validate_for("sim", mode="ice")
        db_cfg.validate_for("release")
        self.assertEqual(db_cfg.active_machine().alias, "horizon_z2")
        self.assertEqual(db_cfg.active_machine().et3confg, "/match3/scd.et3confg")
        self.assertTrue(db_cfg.sim.wave.enable)
        self.assertTrue(db_cfg.sim.tdf.present)

    def test_ixcom_single_example(self) -> None:
        cfg = load_config(str(EXAMPLES_DIR / "ixcom_database"))
        for act in ("analysis", "comp", "all"):
            cfg.validate_for("build", mode="ixcom", act=act)
        cfg.validate_for("sim", mode="ixcom")
        cfg.validate_for("release")
        self.assertEqual(cfg.netlist.name, "")


class TestDbResolutionAndEnvIsolation(unittest.TestCase):
    def test_resolve_db_path_with_and_without_suffix(self) -> None:
        p1 = resolve_db_path(str(EXAMPLES_DIR / "ice_db_fv"))
        p2 = resolve_db_path(str(EXAMPLES_DIR / "ice_db_fv.toml"))
        self.assertEqual(p1, p2)

        with self.assertRaises(ConfigError):
            resolve_db_path(str(EXAMPLES_DIR / "nonexistent_cfg"))

    def test_strict_env_isolation_ignores_os_environ(self) -> None:
        os.environ["KEMU_EXTERNAL_SENTINEL"] = "/should/not/be/read"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                p = _write_toml(
                    Path(tmp),
                    "iso.toml",
                    """
[env]
emu_root = '/proj/soc/emu'
setup_scripts = ['$KEMU_EXTERNAL_SENTINEL/setup.csh']
""",
                )
                with self.assertRaisesRegex(ConfigError, "KEMU_EXTERNAL_SENTINEL"):
                    load_config(str(p))
        finally:
            os.environ.pop("KEMU_EXTERNAL_SENTINEL", None)

    def test_path_expansion_and_relative_anchoring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = _write_toml(
                Path(tmp),
                "paths.toml",
                """
[env]
emu_root = '/proj/soc/emu'
setup_scripts = ['env/local.csh', '$EMU_ROOT/env/global.csh']

[env.vars]
MY_DIR = '$EMU_ROOT/custom'

[emulator]
active = 'm1'

[emulator.machines]
m1 = { host = 'h1', et3confg = 'match3/scd.et3confg.m1' }

[precomp]
clocks_qel = '${MY_DIR}/clocks.qel'
""",
            )
            cfg = load_config(str(p))
            self.assertEqual(
                cfg.env.setup_scripts,
                ["/proj/soc/emu/env/local.csh", "/proj/soc/emu/env/global.csh"],
            )
            self.assertEqual(cfg.active_machine().et3confg, "/proj/soc/emu/match3/scd.et3confg.m1")
            self.assertEqual(cfg.precomp.clocks_qel, "/proj/soc/emu/custom/clocks.qel")
            self.assertEqual(
                resolve_cli_path("rel_dir", cfg.emu_root_path, cfg.env_map, "--comdir"),
                Path("/proj/soc/emu/rel_dir"),
            )
            self.assertEqual(
                resolve_cli_path("/abs/dir", cfg.emu_root_path, cfg.env_map, "--comdir"),
                Path("/abs/dir"),
            )

    def test_env_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            p_rel_root = _write_toml(td, "rel_root.toml", "[env]\nemu_root = 'relative/path'\n")
            with self.assertRaises(ConfigError):
                load_config(str(p_rel_root))

            p_conflict = _write_toml(
                td,
                "xe_conflict.toml",
                _MIN_ENV + "\n[env.vars]\nXE_HOST = 'h1'\nXE_HOST_FILE = '/f1'\n",
            )
            with self.assertRaisesRegex(ConfigError, "XE_HOST"):
                load_config(str(p_conflict))


class TestStrictSchemaAndRules(unittest.TestCase):
    def test_unknown_section_and_keys_rejected_with_hints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            p_sec = _write_toml(td, "bad_sec.toml", _MIN_ENV + "\n[unknown_sec]\nx = 1\n")
            with self.assertRaisesRegex(ConfigError, "Unknown top-level section"):
                load_config(str(p_sec))

            p_key = _write_toml(td, "bad_key.toml", _MIN_ENV + "\n[comp]\nbogus_opt = true\n")
            with self.assertRaisesRegex(ConfigError, "Valid keys:"):
                load_config(str(p_key))

    def test_identifier_enum_and_regex_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            p_bad_id = _write_toml(td, "bad_id.toml", _MIN_ENV + "\n[database]\nname = 'bad name!'\n")
            with self.assertRaises(ConfigError):
                load_config(str(p_bad_id))

            p_bad_flow = _write_toml(td, "bad_flow.toml", _MIN_ENV + "\n[comp]\nflow = 'mc'\n")
            with self.assertRaises(ConfigError):
                load_config(str(p_bad_flow))

            p_bad_def = _write_toml(
                td,
                "bad_def.toml",
                _MIN_ENV
                + """
[analysis]
define_list = ['+define+FOO']
""",
            )
            with self.assertRaisesRegex(ConfigError, r"\+define\+"):
                load_config(str(p_bad_def))

            p_bad_regex = _write_toml(td, "bad_re.toml", _MIN_ENV + "\n[filelist]\ndelete = ['[unclosed']\n")
            with self.assertRaises(ConfigError):
                load_config(str(p_bad_regex))

    def test_comp_helpers_and_mutual_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            p_ppc = _write_toml(
                td,
                "ppc.toml",
                _MIN_ENV
                + """
[emulator]
active = 'm1'

[emulator.machines]
m1 = { host = 'h1', et3confg = '/etc/m1.et3' }
m2 = { host = 'h2' }

[comp]
flow = 'ppc'
compiler_options = ['visionMode DYNP', 'symmetricRotationalFits ON']
target_compile_scripts = ['$EMU_ROOT/qel/t.qel']
boards = '0.0+0.1'

[[comp.symmetric]]
emulator = 'm2'
boards = ['0.0+0.1+0.2+0.3']
advanced_placements = 'MAX'
""",
            )
            cfg = load_config(str(p_ppc))
            self.assertEqual(
                cfg.effective_compiler_options(),
                ["mode ice", "visionMode DYNP", "symmetricRotationalFits ON", "distributedMulticore ON"],
            )
            self.assertTrue(cfg.effective_ice_prepare())
            sym = cfg.resolve_symmetric_configs()
            self.assertEqual(len(sym), 1)
            self.assertEqual(sym[0]["host"], "h2")
            self.assertEqual(sym[0]["file"], "")
            self.assertEqual(sym[0]["advanced_placements"], "MAX")

            p_bad_sym = _write_toml(
                td,
                "bad_sym.toml",
                _MIN_ENV
                + """
[emulator]
active = 'm1'

[emulator.machines]
m1 = { host = 'h1' }

[comp]
[[comp.symmetric]]
emulator = 'm1'
host = 'other'
""",
            )
            with self.assertRaisesRegex(ConfigError, "mutually exclusive"):
                load_config(str(p_bad_sym))

            p_bad_adv = _write_toml(
                td,
                "bad_adv.toml",
                _MIN_ENV
                + """
[comp]
[[comp.symmetric]]
host = 'h1'
locations = ['0.0']
advanced_placements = 'MAX'
""",
            )
            with self.assertRaisesRegex(ConfigError, "boards"):
                load_config(str(p_bad_adv))

    def test_sim_tdf_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            p_acq = _write_toml(
                td,
                "acq_conflict.toml",
                _MIN_ENV + "\n[sim.tdf]\nacquire = ['a == 1']\nno_acquire = ['b == 1']\n",
            )
            with self.assertRaises(ConfigError):
                load_config(str(p_acq))

            for extra_inline in (
                "triggers = ['err == 1']",
                "trigger_pos = 50",
                "post_trigger_samples = 100",
                "enable1 = \"clk == 'bp\"",
                "counter1 = 10",
            ):
                p_tdf_file = _write_toml(
                    td,
                    "tdf_conflict.toml",
                    _MIN_ENV + f"\n[sim.tdf]\ntdf_file = 'sim/t.tdf'\n{extra_inline}\n",
                )
                with self.assertRaises(ConfigError):
                    load_config(str(p_tdf_file))

            p_trig_conflict = _write_toml(
                td,
                "trig_conflict.toml",
                _MIN_ENV + "\n[sim.tdf]\ntrigger_pos = 50\npost_trigger_samples = 100\n",
            )
            with self.assertRaises(ConfigError):
                load_config(str(p_trig_conflict))

            p_neg_cnt = _write_toml(
                td,
                "neg_cnt.toml",
                _MIN_ENV + "\n[sim.tdf]\ncounter1 = -1\n",
            )
            with self.assertRaises(ConfigError):
                load_config(str(p_neg_cnt))

            for bad_name in ("", "sub/trigger.tdf", "../trigger.tdf"):
                p_bad_name = _write_toml(
                    td,
                    "bad_tdf_name.toml",
                    _MIN_ENV + f"\n[sim.tdf]\nname = '{bad_name}'\n",
                )
                with self.assertRaises(ConfigError):
                    load_config(str(p_bad_name))

    def test_env_emulator_analysis_ixcom_sim_additional_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)

            # Invalid [env.vars] key & single quote in value & invalid farm_name
            for snippet in (
                "[env]\nemu_root = '/proj/soc/emu'\n[env.vars]\n'1BAD' = 'x'\n",
                "[env]\nemu_root = '/proj/soc/emu'\n[env.vars]\nGOOD_VAR = \"has'quote\"\n",
                "[env]\nemu_root = '/proj/soc/emu'\n[env.farm]\nfarm_name = 'SLURM'\n",
            ):
                p = _write_toml(td, "env_case.toml", snippet)
                with self.assertRaises(ConfigError):
                    load_config(str(p))

            # Emulator missing/bad active, empty host, and per-machine target_system override
            p_bad_emu = _write_toml(
                td,
                "bad_emu.toml",
                _MIN_ENV + "\n[emulator]\nactive = 'missing'\n[emulator.machines]\nm1 = { host = 'h1' }\n",
            )
            with self.assertRaises(ConfigError):
                load_config(str(p_bad_emu))

            p_empty_host = _write_toml(
                td,
                "empty_host.toml",
                _MIN_ENV + "\n[emulator]\nactive = 'm1'\n[emulator.machines]\nm1 = { host = '' }\n",
            )
            with self.assertRaises(ConfigError):
                load_config(str(p_empty_host))

            p_ts_override = _write_toml(
                td,
                "ts_override.toml",
                _MIN_ENV + "\n[emulator]\nactive = 'm1'\ntarget_system = 'Z2'\n[emulator.machines]\nm1 = { host = 'h1', target_system = 'Z3' }\n",
            )
            cfg_ts = load_config(str(p_ts_override))
            self.assertEqual(cfg_ts.effective_target_system(), "Z3")
            self.assertEqual(cfg_ts.effective_platform(), "Z3")

            # Filelist bad replace length & regex
            p_fl_len = _write_toml(td, "fl_len.toml", _MIN_ENV + "\n[filelist]\nreplace = [['only_one']]\n")
            with self.assertRaises(ConfigError):
                load_config(str(p_fl_len))

            # Analysis duplicate module, empty filelists, default worklib == name
            p_dup_mod = _write_toml(
                td,
                "dup_mod.toml",
                _MIN_ENV
                + "\n[[analysis.module]]\nname = 'm1'\nverilog_filelist = ['a.f']\n[[analysis.module]]\nname = 'm1'\nverilog_filelist = ['b.f']\n",
            )
            with self.assertRaises(ConfigError):
                load_config(str(p_dup_mod))

            p_empty_fl = _write_toml(td, "empty_fl.toml", _MIN_ENV + "\n[[analysis.module]]\nname = 'm1'\n")
            with self.assertRaises(ConfigError):
                load_config(str(p_empty_fl))

            p_def_wl = _write_toml(td, "def_wl.toml", _MIN_ENV + "\n[[analysis.module]]\nname = 'm1'\nvhdl_filelist = ['a.f']\n")
            self.assertEqual(load_config(str(p_def_wl)).analysis.modules[0].worklib, "m1")

            # Bare [impt].netlist_files requires design_top, and extra_netlists expands $EMU_ROOT
            p_bare_vg_no_top = _write_toml(
                td,
                "bare_vg_no_top.toml",
                _MIN_ENV
                + "\n[emulator]\nactive = 'm1'\n[emulator.machines]\nm1 = { host = 'h1' }\n[database]\nname = 'db1'\n[impt]\nnetlist_files = ['nl/top.vg']\n",
            )
            cfg_no_top = load_config(str(p_bare_vg_no_top))
            with self.assertRaisesRegex(ConfigError, "design_top"):
                cfg_no_top.validate_for("build", mode="ice", act="impt")

            p_bare_vg_ok = _write_toml(
                td,
                "bare_vg_ok.toml",
                _MIN_ENV
                + "\n[emulator]\nactive = 'm1'\n[emulator.machines]\nm1 = { host = 'h1' }\n[database]\nname = 'db1'\ndesign_top = 'dut_top'\n[impt]\nnetlist_files = ['nl/top.vg']\nextra_netlists = ['netlistFile {verilog $EMU_ROOT/nl/sub.vg}']\n",
            )
            cfg_bare_ok = load_config(str(p_bare_vg_ok))
            cfg_bare_ok.validate_for("build", mode="ice", act="impt")
            self.assertEqual(cfg_bare_ok.impt.extra_netlists, ["netlistFile {verilog /proj/soc/emu/nl/sub.vg}"])

            # Comp symmetric_boards = 'ALL', explicit ice_prepare = false, invalid advanced_placements
            p_comp_all = _write_toml(
                td,
                "comp_all.toml",
                _MIN_ENV
                + "\n[emulator]\nactive = 'm1'\n[emulator.machines]\nm1 = { host = 'h1', et3confg = '/e.et3' }\n[comp]\nsymmetric_boards = 'ALL'\ntarget_compile_scripts = ['qel/t.qel']\nice_prepare = false\n",
            )
            cfg_all = load_config(str(p_comp_all))
            self.assertFalse(cfg_all.effective_ice_prepare())
            self.assertEqual(cfg_all.resolve_symmetric_configs(), [{"file": "/e.et3", "host": "", "boards": [], "locations": [], "advanced_placements": ""}])

            for bad_adv in ("abc", "0", "-3"):
                p_adv = _write_toml(
                    td,
                    "bad_adv_val.toml",
                    _MIN_ENV + f"\n[comp]\n[[comp.symmetric]]\nhost = 'h1'\nboards = ['0.0']\nadvanced_placements = '{bad_adv}'\n",
                )
                with self.assertRaises(ConfigError):
                    load_config(str(p_adv))

            # IXCOM compile_mode removed & multi-step -target actions rejected
            p_ix_bad_key = _write_toml(
                td,
                "ix_bad_key.toml",
                _MIN_ENV
                + "\n[database]\nname = 'db_ix'\ndesign_top = 'dut'\n[[analysis.module]]\nname = 'dut'\nverilog_filelist = ['a.f']\n[emulator]\nactive = 'm1'\n[emulator.machines]\nm1 = { host = 'h1' }\n[ixcom]\ncompile_mode = 'single'\n",
            )
            with self.assertRaisesRegex(ConfigError, "compile_mode"):
                load_config(str(p_ix_bad_key))

            cfg_ix_ok = load_config(str(EXAMPLES_DIR / "ixcom_database"))
            with self.assertRaises(ConfigError):
                cfg_ix_ok.validate_for("build", mode="ixcom", act="swmodel")

            # Sim pm_mode & wave range checks
            for bad_sim in (
                "[sim]\npm_mode = 'invalid'\n",
                "[sim.wave]\ntrigger_pos = 101\n",
                "[sim.wave]\nnum_files = -1\n",
            ):
                p_sim = _write_toml(td, "bad_sim.toml", _MIN_ENV + "\n" + bad_sim)
                with self.assertRaises(ConfigError):
                    load_config(str(p_sim))

    def test_on_demand_stage_validation(self) -> None:
        nl_cfg = load_config(str(EXAMPLES_DIR / "ice_netlist"))
        nl_cfg.validate_for("build", mode="ice", act="syn")
        with self.assertRaises(ConfigError):
            nl_cfg.validate_for("build", mode="ice", act="impt")
        with self.assertRaises(ConfigError):
            nl_cfg.validate_for("release")


if __name__ == "__main__":
    unittest.main()
