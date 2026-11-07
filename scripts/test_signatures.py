"""Plan-name declarations against the live v6 tree shape (a temp git repo)."""
import subprocess
import tempfile
import unittest
from pathlib import Path

import signatures


class SignaturesTest(unittest.TestCase):
    def repo(self):
        d = tempfile.mkdtemp()
        Path(d, "config.ts").write_text(
            "export function parseListen (s: string): { host: string; port: number } {\n  return x\n}\n"
            "export async function loadHubConfig (): Promise<HubConfig> {\n}\n"
            "export const PRINCIPAL_RE = /^[a-z]$/\n")
        Path(d, "dup.ts").write_text("export function twice () {}\n")
        Path(d, "dup2.ts").write_text("export function twice () {}\n")
        subprocess.run(["git", "-C", d, "init", "-q"], check=True)
        subprocess.run(["git", "-C", d, "add", "."], check=True)
        return d

    def test_plan_names_get_their_declaration_lines(self):
        d = self.repo()
        plan = "port from loadHubConfig() via parseListen, matching `PRINCIPAL_RE`; also twice() and nothing()"
        out = signatures.section(d, plan)
        self.assertIn("config.ts:1: export function parseListen (s: string): { host: string; port: number }", out)
        self.assertIn("config.ts:4: export async function loadHubConfig (): Promise<HubConfig>", out)
        self.assertIn("config.ts:6: export const PRINCIPAL_RE = /^[a-z]$/", out)
        self.assertNotIn("twice", out)  # ambiguous: two declarations
        self.assertNotIn("nothing", out)

    def test_no_names_no_section(self):
        self.assertEqual(signatures.section(self.repo(), "just prose here"), "")


if __name__ == "__main__":
    unittest.main()
