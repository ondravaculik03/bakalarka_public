import json
import logging
from unittest.mock import MagicMock, patch

import pytest
from src.lib.system_info import get_system_info  # Import to patch it

from ..src.lib.system_info_reporter import SystemInfoReporter


@pytest.fixture
def system_info_reporter_instance():
    return SystemInfoReporter()


@pytest.fixture
def mock_system_info():
    return {
        "hostname": "test-host",
        "user": "test-user",
        "os": "TestOS",
        "os_version": "1.0",
        "architecture": "x86_64",
        "processor": "Intel(R) Core(TM) i9-9900K CPU @ 3.60GHz",
    }


def test_report_system_info_calls_get_system_info(
    system_info_reporter_instance, mock_system_info
):
    with patch(
        "lib.system_info_reporter.get_system_info", return_value=mock_system_info
    ) as mock_get_info:
        system_info = system_info_reporter_instance.report_system_info()
        mock_get_info.assert_called_once()
        assert system_info == mock_system_info


def test_report_system_info_logs_correctly(
    system_info_reporter_instance, mock_system_info, caplog
):
    with caplog.at_level(logging.INFO):
        with patch(
            "lib.system_info_reporter.get_system_info", return_value=mock_system_info
        ):
            system_info_reporter_instance.report_system_info()

            assert "--- Informace o systému ---" in caplog.text
            assert "hostname: test-host" in caplog.text
            assert "user: test-user" in caplog.text
            assert "os: TestOS" in caplog.text
            assert "os_version: 1.0" in caplog.text
            assert "architecture: x86_64" in caplog.text
            assert "processor: Intel(R) Core(TM) i9-9900K CPU @ 3.60GHz" in caplog.text
            assert "---------------------------" in caplog.text

            # Check for debug log as well


def test_report_system_info_returns_info(
    system_info_reporter_instance, mock_system_info
):
    with patch(
        "lib.system_info_reporter.get_system_info", return_value=mock_system_info
    ):
        returned_info = system_info_reporter_instance.report_system_info()
        assert returned_info == mock_system_info
