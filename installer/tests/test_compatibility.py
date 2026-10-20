"""Read-only compatibility and diagnostic checks for the Windows installer."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
GAME = PROJECT.parent
INSTALLER = PROJECT / "installer/bin/Release/net8.0-windows/VoiceInstaller.dll"


class CompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=PROJECT / "local")
        self.addCleanup(self.temp.cleanup)
        self.game = Path(self.temp.name)
        shutil.copy2(GAME / "enshrouded.exe", self.game / "enshrouded.exe")
        shutil.copy2(GAME / "enshrouded.kfc", self.game / "enshrouded.kfc")
        (self.game / "enshrouded.kfc_resources").write_bytes(b"fixture")

    def diagnose(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["dotnet", str(INSTALLER), "--diagnose", str(self.game)],
            capture_output=True, text=True, timeout=30,
        )

    def test_known_build_creates_log(self) -> None:
        result = self.diagnose()
        self.assertEqual(result.returncode, 0, result.stderr)
        log = (self.game / "ru_voice_installer.log").read_text(encoding="utf-8")
        self.assertIn("Three unique runtime hook signatures confirmed", log)
        self.assertIn("OK cli diagnose", log)

    def test_changed_exe_hash_is_allowed_when_code_signatures_match(self) -> None:
        with (self.game / "enshrouded.exe").open("ab") as file:
            file.write(b"different package fingerprint")
        result = self.diagnose()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_build_below_floor_is_rejected(self) -> None:
        index = self.game / "enshrouded.kfc"
        data = index.read_bytes()
        self.assertEqual(data.count(b"1269579|^/game38/branches/release_1.0|"), 1)
        index.write_bytes(data.replace(b"1269579|^/game38/branches/release_1.0|",
                                       b"1269578|^/game38/branches/release_1.0|"))
        result = self.diagnose()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("старше минимальной", (self.game / "ru_voice_installer.log").read_text(encoding="utf-8"))

    def test_changed_hook_code_is_rejected(self) -> None:
        exe = self.game / "enshrouded.exe"
        data = exe.read_bytes()
        signature = bytes.fromhex(
            "48895C2410488974241848897C2420554154415541564157488D6C24C9"
            "4881ECC00000008B712833C04D8BE84C8BFA48"
        )
        offset = data.find(signature)
        self.assertGreater(offset, 0)
        data = data[:offset] + b"\x90" + data[offset + 1:]
        exe.write_bytes(data)
        result = self.diagnose()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Аудиофункция", (self.game / "ru_voice_installer.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
