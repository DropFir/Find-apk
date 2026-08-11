from __future__ import annotations

from pathlib import Path
import sys
import unittest


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from cloudflare_faker_service import (  # noqa: E402
    JAR,
    JAVA,
    LABEL,
    service_configuration,
)


class CloudflareFakerServiceTests(unittest.TestCase):
    def test_configuration_is_persistent_and_loopback_only(self) -> None:
        configuration = service_configuration()

        self.assertEqual(configuration["Label"], LABEL)
        self.assertTrue(configuration["RunAtLoad"])
        self.assertTrue(configuration["KeepAlive"])
        self.assertEqual(
            configuration["ProgramArguments"],
            [
                str(JAVA),
                "--enable-native-access=ALL-UNNAMED",
                "-jar",
                str(JAR),
                "--server.address=127.0.0.1",
                "--server.port=8080",
            ],
        )


if __name__ == "__main__":
    unittest.main()
