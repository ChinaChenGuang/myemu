"""Unit tests for kemu_src.cli and the ./kemu executable entrypoint."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import subprocess
import tempfile
import unittest

from kemu_src.cli import build_parser, main

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestCli(unittest.TestCase):
    def test_executable_help(self) -> None:
        proc = subprocess.run(
            [str(REPO_ROOT / "kemu"), "help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("kemu build ice", proc.stdout)
        self.assertIn("--db <db_name>", proc.stdout)
        self.assertNotRegex(proc.stdout, r"(?<!-)-db\b")

        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(main([]), 0)
        self.assertIn("kemu build ice", out.getvalue())

    def test_db_flag_and_subcommands(self) -> None:
        parser = build_parser()
        a1 = parser.parse_args(["build", "ice", "--db", "examples/ice_db_fv", "--comdir", "work", "--act", "impt"])
        a2 = parser.parse_args(["build", "ice", "--db", "examples/ice_db_fv.toml", "--comdir", "work", "--act", "impt", "--gen-only"])
        self.assertEqual(a1.db, "examples/ice_db_fv")
        self.assertFalse(a1.gen_only)
        self.assertEqual(a2.db, "examples/ice_db_fv.toml")
        self.assertTrue(a2.gen_only)

        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            parser.parse_args(["build", "ice", "-db", "examples/ice_db_fv", "--comdir", "work", "--act", "impt"])
        self.assertEqual(ctx.exception.code, 2)

        a_ix = parser.parse_args(["build", "ixcom", "--db", "examples/ixcom_database", "--comdir", "work", "--act", "all"])
        self.assertEqual(a_ix.act, "all")
        a_ix_comp = parser.parse_args(["build", "ixcom", "--db", "examples/ixcom_database", "--comdir", "work", "--act", "comp"])
        self.assertEqual(a_ix_comp.act, "comp")

        for bad_ix_argv in (
            ["build", "ixcom", "--db", "examples/ixcom_database", "--comdir", "work"],
            ["build", "ixcom", "--db", "examples/ixcom_database", "--comdir", "work", "--act", "swmodel"],
        ):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx_ix:
                parser.parse_args(bad_ix_argv)
            self.assertEqual(ctx_ix.exception.code, 2)

        a_sim = parser.parse_args([
            "sim", "ice", "--db", "examples/ice_db_fv",
            "--db-path", "work/database/base_fv", "--simdir", "sim/s1", "--session", "s1", "--gen-only",
        ])
        self.assertEqual(a_sim.mode, "ice")
        self.assertEqual(a_sim.session, "s1")
        self.assertTrue(a_sim.gen_only)

        a_rel = parser.parse_args(["release", "--db", "examples/ice_db_fv", "--comdir", "work", "--type", "tar"])
        self.assertEqual(a_rel.release_type, "tar")

    def test_cli_validates_config_and_session_without_traceback(self) -> None:
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(["build", "ice", "--db", str(REPO_ROOT / "examples/ice_netlist"), "--comdir", "work", "--act", "impt"])
        self.assertEqual(rc, 1)
        self.assertIn("ERROR:", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

        err_sess = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err_sess):
            rc_sess = main([
                "sim", "ice", "--db", str(REPO_ROOT / "examples/ice_db_fv"),
                "--db-path", "work/database/base_fv", "--simdir", "sim/s1", "--session", "bad/sess",
            ])
        self.assertEqual(rc_sess, 1)
        self.assertIn("--session", err_sess.getvalue())
        self.assertNotIn("Traceback", err_sess.getvalue())

        with tempfile.TemporaryDirectory() as tmp:
            bad_toml = Path(tmp) / "broken.toml"
            bad_toml.write_text("[env\nbroken =", encoding="utf-8")
            err_toml = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err_toml):
                rc_toml = main(["release", "--db", str(bad_toml), "--comdir", "work", "--type", "DB"])
            self.assertEqual(rc_toml, 1)
            self.assertIn("ERROR:", err_toml.getvalue())
            self.assertNotIn("Traceback", err_toml.getvalue())

        err_ok = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err_ok):
            rc_ok = main(["build", "ice", "--db", str(REPO_ROOT / "examples/ice_netlist"), "--comdir", "work", "--act", "syn"])
        self.assertEqual(rc_ok, 2)
        self.assertIn("Config validated", err_ok.getvalue())


if __name__ == "__main__":
    unittest.main()
