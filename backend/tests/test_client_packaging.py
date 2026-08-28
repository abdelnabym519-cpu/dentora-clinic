from __future__ import annotations

import base64
import hashlib
import os
import shutil
import subprocess
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "PREPARE_CLIENT_PACKAGE.sh"
OUT = ROOT / "dist" / "Dentora_Client"
ARCHIVE = ROOT / "dist" / "Dentora_Client.zip"
CHECKSUM = ROOT / "dist" / "Dentora_Client.zip.sha256"


def _parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


class ClientPackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.license_server_url = "https://license.test.invalid"
        cls.license_public_key = base64.b64encode(b"L" * 32).decode("ascii")
        cls.update_metadata_url = "https://updates.test.invalid/latest.json"
        cls.update_public_key = base64.b64encode(b"U" * 32).decode("ascii")
        cls.env = os.environ.copy()
        cls.env.update(
            {
                "DENTORA_LICENSE_SERVER_URL": cls.license_server_url,
                "DENTORA_LICENSE_PUBLIC_KEY_B64": cls.license_public_key,
                "DENTORA_UPDATE_METADATA_URL": cls.update_metadata_url,
                "DENTORA_UPDATE_PUBLIC_KEY_B64": cls.update_public_key,
            }
        )
        completed = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=ROOT,
            env=cls.env,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise AssertionError(
                "Client package build failed:\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        cls.output = completed.stdout

    @classmethod
    def tearDownClass(cls) -> None:
        if OUT.exists():
            shutil.rmtree(OUT)
        ARCHIVE.unlink(missing_ok=True)
        CHECKSUM.unlink(missing_ok=True)
        dist = ROOT / "dist"
        if dist.exists() and not any(dist.iterdir()):
            dist.rmdir()

    def test_package_contains_runtime_and_excludes_owner_internals(self) -> None:
        self.assertIn("READY", self.output)
        self.assertTrue(ARCHIVE.is_file())
        self.assertTrue(CHECKSUM.is_file())

        with zipfile.ZipFile(ARCHIVE) as archive:
            names = set(archive.namelist())

        expected = {
            ".env.client.example",
            "CLIENT_INSTALL_AR.md",
            "START_DENTORA.bat",
            "UPDATE_DENTORA.bat",
            "docker-compose.client.yml",
            "scripts/dentora_auto_update.ps1",
            "BUILD_INFO.txt",
        }
        self.assertTrue(expected <= names)
        self.assertNotIn(".env.client", names)
        self.assertNotIn("PREPARE_CLIENT_PACKAGE.sh", names)
        self.assertFalse(any(name.startswith(".github/") for name in names))
        self.assertFalse(any(name.startswith("license-server/") for name in names))
        self.assertFalse(any(name.startswith("license-worker/") for name in names))
        self.assertFalse(any(name.startswith(".license-dev/") for name in names))

    def test_package_pins_trust_and_keeps_per_install_secrets_empty(self) -> None:
        with zipfile.ZipFile(ARCHIVE) as archive:
            config = _parse_env(archive.read(".env.client.example").decode("utf-8"))
            build_info = archive.read("BUILD_INFO.txt").decode("utf-8")

        self.assertEqual(config["LICENSE_SERVER_URL"], self.license_server_url)
        self.assertEqual(config["LICENSE_PUBLIC_KEY_B64"], self.license_public_key)
        self.assertEqual(config["UPDATE_METADATA_URL"], self.update_metadata_url)
        self.assertEqual(config["UPDATE_PUBLIC_KEY_B64"], self.update_public_key)
        for key in (
            "POSTGRES_PASSWORD",
            "SECRET_KEY",
            "BUDGET_PUBLIC_SECRET_KEY",
            "LICENSE_MACHINE_FINGERPRINT",
        ):
            self.assertEqual(config[key], "")

        source_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        self.assertIn("Source ref: HEAD", build_info)
        self.assertIn(f"Source SHA: {source_sha}", build_info)
        self.assertIn(f"License server: {self.license_server_url}", build_info)
        self.assertIn(f"Auto Update metadata: {self.update_metadata_url}", build_info)

    def test_checksum_matches_archive(self) -> None:
        expected = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
        checksum_parts = CHECKSUM.read_text(encoding="ascii").strip().split()
        self.assertEqual(checksum_parts, [expected, ARCHIVE.name])

    def test_missing_auto_update_trust_is_rejected(self) -> None:
        env = self.env.copy()
        env.pop("DENTORA_UPDATE_PUBLIC_KEY_B64", None)
        completed = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("pinned Auto Update trust configuration", completed.stdout)


if __name__ == "__main__":
    unittest.main()
