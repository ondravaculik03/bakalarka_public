import logging
from unittest.mock import MagicMock, patch

import pytest
import requests
from src.lib.message_sender import MessageSender


@pytest.fixture
def message_sender_instance():
    return MessageSender(server_url="http://test-server.com", agent_id="test-agent-id")


@pytest.fixture
def mock_encrypted_data():
    return "mock_encrypted_key", "mock_nonce", "mock_ciphertext"


def test_send_message_success(message_sender_instance, mock_encrypted_data, caplog):
    encrypted_key, nonce, ciphertext = mock_encrypted_data
    message_count = 5

    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        with caplog.at_level(logging.INFO):
            result = message_sender_instance.send_message(
                encrypted_key, nonce, ciphertext, message_count
            )

            assert result is True
            mock_post.assert_called_once()

            # Verify payload structure (random fields are not checked for exact values)
            args, kwargs = mock_post.call_args
            assert args[0] == "http://test-server.com/api/message"
            assert kwargs["headers"] == {"Content-Type": "application/json"}
            payload = kwargs["json"]
            assert payload["agent_id"] == "test-agent-id"
            assert payload["encrypted_key"] == encrypted_key
            assert payload["nonce"] == nonce
            assert payload["ciphertext"] == ciphertext

            assert (
                f"test-agent-id: Check-in delivered - sent in total: {message_count}"
                in caplog.text
            )


def test_send_message_server_error(
    message_sender_instance, mock_encrypted_data, caplog
):
    encrypted_key, nonce, ciphertext = mock_encrypted_data
    message_count = 5

    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        with caplog.at_level(logging.ERROR):
            result = message_sender_instance.send_message(
                encrypted_key, nonce, ciphertext, message_count
            )

            assert result is False
            mock_post.assert_called_once()
            assert "test-agent-id: Sending failed - 500" in caplog.text


def test_send_message_connection_error(
    message_sender_instance, mock_encrypted_data, caplog
):
    encrypted_key, nonce, ciphertext = mock_encrypted_data
    message_count = 5

    with patch(
        "requests.post",
        side_effect=requests.exceptions.ConnectionError("Mocked Connection Error"),
    ) as mock_post:
        with caplog.at_level(logging.ERROR):
            result = message_sender_instance.send_message(
                encrypted_key, nonce, ciphertext, message_count
            )

            assert result is False
            mock_post.assert_called_once()
            assert (
                "test-agent-id: Can't connect to the server http://test-server.com"
                in caplog.text
            )
