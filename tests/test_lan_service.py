from __future__ import annotations

from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from lan_service import (  # noqa: E402
    LABEL,
    PROJECT_ROOT,
    PYTHON_EXECUTABLE,
    VENV_SITE_PACKAGES,
    service_configuration,
)


class LanServiceTests(unittest.TestCase):
    def test_configuration_is_persistent_and_project_scoped(self) -> None:
        configuration = service_configuration(8765)

        self.assertEqual(configuration["Label"], LABEL)
        self.assertTrue(configuration["RunAtLoad"])
        self.assertEqual(
            configuration["KeepAlive"],
            {"SuccessfulExit": False},
        )
        self.assertNotIn("WorkingDirectory", configuration)
        self.assertEqual(
            configuration["ProgramArguments"],
            [
                str(PYTHON_EXECUTABLE),
                "-m",
                "uvicorn",
                "lan_share.app:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8765",
                "--app-dir",
                str(PROJECT_ROOT),
            ],
        )

    def test_configuration_keeps_logs_in_local_state_directory(self) -> None:
        configuration = service_configuration(9000)

        self.assertIn("Library/Logs/Find-APK", configuration["StandardOutPath"])
        self.assertIn("Library/Logs/Find-APK", configuration["StandardErrorPath"])
        self.assertEqual(
            configuration["EnvironmentVariables"]["FIND_APK_PORT"],
            "9000",
        )
        self.assertEqual(
            configuration["EnvironmentVariables"]["PYTHONPATH"],
            str(VENV_SITE_PACKAGES),
        )
        self.assertEqual(
            configuration["EnvironmentVariables"]["FIND_APK_BROWSER_PORT"],
            "9223",
        )


if __name__ == "__main__":
    unittest.main()
