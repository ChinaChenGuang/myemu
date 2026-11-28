"""Command-line interface entrypoint for KEMU."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import sys

from .db_config import ConfigError, load_config, resolve_cli_path, validate_session_name

HELP_TEXT = """kemu — Cadence Palladium Z2/Z3 (ICE & IXCOM/SA) 编排工具

用法 (Usage):
  kemu help
  kemu build ice   --db <db_name> --comdir <path> --act <action> [--gen-only]
  kemu build ixcom --db <db_name> --comdir <path> --act <action> [--gen-only]
  kemu sim   ice   --db <db_name> --db-path <path> --simdir <path> --session <name> [--gen-only]
  kemu sim   ixcom --db <db_name> --db-path <path> --simdir <path> --session <name> [--gen-only]
  kemu release     --db <db_name> --comdir <path> --type <tar|DB>

说明:
  --db <db_name> 无需加 .toml 后缀，工具自动补全；
  相对路径 (--comdir / --db-path / --simdir) 统一以 [env].emu_root 为基准解析。

常用示例:
  kemu build ice   --db examples/ice_netlist    --comdir work_2607 --act syn
  kemu build ice   --db examples/ice_db_fv      --comdir work_2607 --act impt
  kemu build ixcom --db examples/ixcom_database --comdir work_2607 --act all
  kemu sim   ice   --db examples/ice_db_fv      --db-path work_2607/database/base_fv --simdir sim/s1 --session s1
  kemu release     --db examples/ice_db_fv      --comdir work_2607 --type tar
"""


def _add_db_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        required=True,
        metavar="<db_name>",
        help="TOML 配置文件名或路径（无需 .toml 后缀）",
    )


def build_parser() -> argparse.ArgumentParser:
    """Create and return the root ``argparse`` parser."""
    parser = argparse.ArgumentParser(
        prog="kemu",
        description="Cadence Palladium Z2/Z3 (ICE & IXCOM/SA) compilation, simulation & release tool.",
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("help", help="显示帮助信息与常用命令示例")

    # kemu build {ice, ixcom}
    p_build = subparsers.add_parser("build", help="构建编译脚本并执行 ICE / IXCOM 编译", allow_abbrev=False)
    build_sub = p_build.add_subparsers(dest="mode", required=True)

    p_build_ice = build_sub.add_parser("ice", help="Palladium ICE 模式编译", allow_abbrev=False)
    _add_db_arg(p_build_ice)
    p_build_ice.add_argument("--comdir", required=True, metavar="<path>", help="编译工作根目录")
    p_build_ice.add_argument(
        "--act",
        required=True,
        choices=["analysis", "elaborate", "syn", "impt", "precomp", "comp"],
        help="执行阶段",
    )
    p_build_ice.add_argument("--gen-only", action="store_true", help="仅生成脚本，不实际执行")

    p_build_ixcom = build_sub.add_parser("ixcom", help="Palladium IXCOM (SA) 模式编译", allow_abbrev=False)
    _add_db_arg(p_build_ixcom)
    p_build_ixcom.add_argument("--comdir", required=True, metavar="<path>", help="编译工作根目录")
    p_build_ixcom.add_argument(
        "--act",
        required=True,
        choices=["analysis", "comp", "all"],
        help="执行阶段",
    )
    p_build_ixcom.add_argument("--gen-only", action="store_true", help="仅生成脚本，不实际执行")

    # kemu sim {ice, ixcom}
    p_sim = subparsers.add_parser("sim", help="生成并运行 ICE / IXCOM 仿真", allow_abbrev=False)
    sim_sub = p_sim.add_subparsers(dest="mode", required=True)

    for mode_name, desc in (("ice", "ICE 模式仿真 (xeDebug)"), ("ixcom", "IXCOM 模式仿真 (xrun -R)")):
        p_sim_mode = sim_sub.add_parser(mode_name, help=desc, allow_abbrev=False)
        _add_db_arg(p_sim_mode)
        p_sim_mode.add_argument("--db-path", required=True, metavar="<path>", help="已编译好的 database 路径")
        p_sim_mode.add_argument("--simdir", required=True, metavar="<path>", help="仿真运行目录")
        p_sim_mode.add_argument("--session", required=True, metavar="<name>", help="仿真 session 名称")
        p_sim_mode.add_argument("--gen-only", action="store_true", help="仅生成脚本，不实际执行")

    # kemu release
    p_rel = subparsers.add_parser("release", help="按规则打包或归档已编译 database", allow_abbrev=False)
    _add_db_arg(p_rel)
    p_rel.add_argument("--comdir", required=True, metavar="<path>", help="编译工作根目录")
    p_rel.add_argument("--type", dest="release_type", required=True, choices=["tar", "DB"], help="发布形态")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint returning process exit status."""
    arg_list = list(sys.argv[1:] if argv is None else argv)
    if not arg_list:
        print(HELP_TEXT, end="")
        return 0

    parser = build_parser()
    try:
        args = parser.parse_args(arg_list)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 1

    if args.command == "help":
        print(HELP_TEXT, end="")
        return 0

    try:
        cfg = load_config(args.db)
        mode = getattr(args, "mode", None)
        act = getattr(args, "act", None)
        cfg.validate_for(args.command, mode=mode, act=act)
        if hasattr(args, "comdir"):
            resolve_cli_path(args.comdir, cfg.emu_root_path, cfg.env_map, "--comdir")
        if hasattr(args, "db_path"):
            resolve_cli_path(args.db_path, cfg.emu_root_path, cfg.env_map, "--db-path")
        if hasattr(args, "simdir"):
            resolve_cli_path(args.simdir, cfg.emu_root_path, cfg.env_map, "--simdir")
        if hasattr(args, "session"):
            validate_session_name(args.session)
    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    target = f"{args.command} {mode}" if mode else args.command
    print(
        f"Config validated for '{target}' ({cfg.source_path}); "
        "execution handlers will be implemented in M3-M5.",
        file=sys.stderr,
    )
    return 2
