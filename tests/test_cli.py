"""Unit tests for kemu_src.cli and the ./kemu executable entrypoint."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import subprocess
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
        self.assertIn("-db <db_name>", proc.stdout)

    def test_db_short_and_long_flags(self) -> None:
        parser = build_parser()
        a1 = parser.parse_args(["build", "ice", "-db", "examples/ice_db_fv", "--comdir", "work", "--act", "impt"])
        a2 = parser.parse_args(["build", "ice", "--db", "examples/ice_db_fv.toml", "--comdir", "work", "--act", "impt", "--gen-only"])
        self.assertEqual(a1.db, "examples/ice_db_fv")
        self.assertFalse(a1.gen_only)
        self.assertEqual(a2.db, "examples/ice_db_fv.toml")
        self.assertTrue(a2.gen_only)

        a_ix = parser.parse_args(["build", "ixcom", "-db", "examples/ixcom_database", "--comdir", "work"])
        self.assertEqual(a_ix.act, "all")

    def test_cli_validates_config_without_traceback_on_error(self) -> None:
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(["build", "ice", "-db", str(REPO_ROOT / "examples/ice_netlist"), "--comdir", "work", "--act", "impt"])
        self.assertEqual(rc, 1)
        self.assertIn("ERROR:", err.getvalue())
        self.assertNotIn("Traceback", err.getvalue())

        err_ok = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err_ok):
            rc_ok = main(["build", "ice", "-db", str(REPO_ROOT / "examples/ice_netlist"), "--comdir", "work", "--act", "syn"])
        self.assertEqual(rc_ok, 2)
        self.assertIn("Config validated", err_ok.getvalue())


if __name__ == "__main__":
    unittest.main()
