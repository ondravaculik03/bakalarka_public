import json
import logging
import os
from unittest.mock import patch

import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from src.lib.message_encryptor import MessageEncryptor
from src.lib.message_sender import MessageSender
from src.lib.public_key_fetcher import PublicKeyFetcher
from src.lib.system_info_reporter import SystemInfoReporter
from src.main import Agent  # Import the Agent class


# Fixture for a dummy public key PEM
@pytest.fixture
def mock_public_key_pem():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


# Fixture for a dummy RSAPublicKey object
@pytest.fixture
def dummy_rsa_public_key(mock_public_key_pem):
    return serialization.load_pem_public_key(mock_public_key_pem.encode("utf-8"))


# Mock the external dependencies for TestAgent
@pytest.fixture
def mock_config_load():
    with patch("config.load") as mock_load:
        mock_load.return_value = {
            "server_url": "http://mock-server.com",
            "interval_seconds": 60,
            "log_level": "INFO",
            "auth_token": "mock_auth_token",
        }
        yield mock_load


@pytest.fixture
def mock_check_for_update():
    with patch("src.main.check_for_update") as mock_update:
        yield mock_update


@pytest.fixture
def mock_agent_id_env_var():
    with patch("os.getenv", return_value="mock-agent-id") as mock_getenv:
        yield mock_getenv


@pytest.fixture
def mock_get_system_info():
    with patch("lib.system_info.get_system_info") as mock_get_info:
        mock_get_info.return_value = {
            "hostname": "mock-hostname",
            "user": "mock-user",
            "os": "MockOS",
            "os_version": "0.1",
            "architecture": "mock_arch",
            "processor": "mock_processor",
        }
        yield mock_get_info


@pytest.fixture
def test_agent_instance(mock_config_load, mock_check_for_update, mock_agent_id_env_var):
    # TestAgent constructor calls config.load, so ensure it's mocked before instantiation
    agent = Agent()
    yield agent


# --- Tests for TestAgent orchestration ---


def test_test_agent_init(test_agent_instance, mock_config_load):
    mock_config_load.assert_called_once()
    assert test_agent_instance.server_url == "http://mock-server.com"
    assert test_agent_instance.auth_token == "mock_auth_token"
    assert test_agent_instance.message_count == 0


def test_test_agent_init_exits_without_auth_token(mock_check_for_update, caplog):
    with patch("config.load") as mock_load:
        mock_load.return_value = {
            "server_url": "http://mock-server.com",
            "auth_token": "NOT_CONFIGURED",
        }
        with pytest.raises(SystemExit) as pytest_wrapped_e:
            with caplog.at_level(logging.ERROR):
                Agent()
        assert pytest_wrapped_e.type is SystemExit
        assert pytest_wrapped_e.value.code == 1
        assert "Chyba: 'auth_token' není nastaven." in caplog.text


def test_start_agent_orchestrates_system_info_reporting(
    test_agent_instance, mock_get_system_info, caplog
):
    with patch.object(
        test_agent_instance._system_info_reporter, "report_system_info"
    ) as mock_report_info:
        mock_report_info.return_value = {"hostname": "orchestrated-host"}

        with caplog.at_level(logging.INFO):
            test_agent_instance.start_agent()
            mock_report_info.assert_called_once()
            assert test_agent_instance.message_count == 1
            assert "Agent mock-agent-id startuje..." in caplog.text
            assert "Cílová URL: http://mock-server.com" in caplog.text


# Test for send_message orchestration
def test_send_message_orchestrates_encryption_and_sending(
    test_agent_instance, dummy_rsa_public_key, mock_public_key_pem
):

    content = {"status": "alive"}
    hostname = "test-host"
    client_ip = "192.168.1.1"

    # Mock the internal dependencies of TestAgent
    with patch(
        "src.main.PublicKeyFetcher.fetch_public_key", return_value=dummy_rsa_public_key
    ) as mock_fetch_key, patch(
        "src.main.MessageEncryptor.encrypt_message"
    ) as mock_encrypt_message, patch(
        "src.main.MessageSender.send_message", return_value=True
    ) as mock_send_message:

        # Configure mock_encrypt_message to return dummy encrypted data
        mock_encrypt_message.return_value = ("enc_key_b64", "nonce_b64", "cipher_b64")

        # Call send_message on the TestAgent instance
        result = test_agent_instance.send_message(
            json.dumps(content), hostname, client_ip
        )

        # Assertions
        assert result is True
        mock_fetch_key.assert_called_once()
        mock_encrypt_message.assert_called_once_with(
            content, test_agent_instance.auth_token, dummy_rsa_public_key
        )
        mock_send_message.assert_called_once_with(
            "enc_key_b64",
            "nonce_b64",
            "cipher_b64",
            client_ip,
            test_agent_instance.message_count,
        )


def test_send_message_handles_connection_error(
    test_agent_instance, caplog, dummy_rsa_public_key, mock_public_key_pem
):
    content = {"status": "alive"}
    hostname = "test-host"
    client_ip = "192.168.1.1"

    with patch("src.main.PublicKeyFetcher.fetch_public_key") as mock_fetch_key, patch(
        "src.main.MessageEncryptor.encrypt_message"
    ) as mock_encrypt_message, patch(
        "src.main.MessageSender.send_message",
        side_effect=requests.exceptions.ConnectionError("Mocked Connection Error"),
    ) as _:

        mock_fetch_key.return_value = dummy_rsa_public_key
        mock_encrypt_message.return_value = ("enc_key_b64", "nonce_b64", "cipher_b64")

        with caplog.at_level(logging.ERROR):
            result = test_agent_instance.send_message(
                json.dumps(content), hostname, client_ip
            )

            assert result is False
            assert (
                f"{test_agent_instance.agent_id}: Chyba při odesílání nebo získávání klíče - Mocked Connection Error"
                in caplog.text
            )
