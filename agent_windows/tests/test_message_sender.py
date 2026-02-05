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
    client_ip = "127.0.0.1"
    message_count = 5

    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        with caplog.at_level(logging.INFO):
            result = message_sender_instance.send_message(
                encrypted_key, nonce, ciphertext, client_ip, message_count
            )

            assert result is True
            mock_post.assert_called_once()

            # Verify payload structure (random fields are not checked for exact values)
            args, kwargs = mock_post.call_args
            assert args[0] == "http://test-server.com/api/message"
            assert kwargs["headers"] == {"Content-Type": "application/json"}
            payload = kwargs["json"]
            assert payload["agent_id"] == "test-agent-id"
            assert payload["client_ip"] == "127.0.0.1"
            assert "client_os" in payload
            assert "client_state" in payload
            assert "client_points" in payload
            assert payload["encrypted_key"] == encrypted_key
            assert payload["nonce"] == nonce
            assert payload["ciphertext"] == ciphertext

            assert (
                f"test-agent-id: Zpráva doručena - Celkem odesláno: {message_count}"
                in caplog.text
            )


def test_send_message_server_error(
    message_sender_instance, mock_encrypted_data, caplog
):
    encrypted_key, nonce, ciphertext = mock_encrypted_data
    client_ip = "127.0.0.1"
    message_count = 5

    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        with caplog.at_level(logging.ERROR):
            result = message_sender_instance.send_message(
                encrypted_key, nonce, ciphertext, client_ip, message_count
            )

            assert result is False
            mock_post.assert_called_once()
            assert "test-agent-id: Chyba při odesílání - 500" in caplog.text


def test_send_message_connection_error(
    message_sender_instance, mock_encrypted_data, caplog
):
    encrypted_key, nonce, ciphertext = mock_encrypted_data
    client_ip = "127.0.0.1"
    message_count = 5

    with patch(
        "requests.post",
        side_effect=requests.exceptions.ConnectionError("Mocked Connection Error"),
    ) as mock_post:
        with caplog.at_level(logging.ERROR):
            result = message_sender_instance.send_message(
                encrypted_key, nonce, ciphertext, client_ip, message_count
            )

            assert result is False
            mock_post.assert_called_once()
            assert (
                "test-agent-id: Nelze se připojit k serveru http://test-server.com"
                in caplog.text
            )


def test_send_message_payload_contents_randomness(
    message_sender_instance, mock_encrypted_data
):
    encrypted_key, nonce, ciphertext = mock_encrypted_data
    client_ip = "127.0.0.1"
    message_count = 1

    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        # Call twice and check if random fields are actually random
        with patch("random.choice") as mock_choice, patch(
            "random.randint"
        ) as mock_randint:

            mock_choice.side_effect = [
                "os1_val",
                "state1_val",
            ]  # First call for client_os, client_state
            mock_randint.side_effect = [10]  # First call for client_points

            message_sender_instance.send_message(
                encrypted_key, nonce, ciphertext, client_ip, message_count
            )
            args1, kwargs1 = mock_post.call_args_list[0]
            payload1 = kwargs1["json"]

            # Reset mocks for second call
            mock_post.reset_mock()
            mock_choice.reset_mock()
            mock_randint.reset_mock()

            mock_choice.side_effect = [
                "os2_val",
                "state2_val",
            ]  # Second call for client_os, client_state
            mock_randint.side_effect = [20]  # Second call for client_points

            message_sender_instance.send_message(
                encrypted_key, nonce, ciphertext, client_ip, message_count
            )
            args2, kwargs2 = mock_post.call_args_list[0]
            payload2 = kwargs2["json"]

            assert payload1["client_os"] == "os1_val"
            assert payload1["client_state"] == "state1_val"
            assert payload1["client_points"] == 10

            assert payload2["client_os"] == "os2_val"
            assert payload2["client_state"] == "state2_val"
            assert payload2["client_points"] == 20

            assert mock_choice.call_count == 2  # 2 for each call
            assert mock_randint.call_count == 1  # 1 for each call
