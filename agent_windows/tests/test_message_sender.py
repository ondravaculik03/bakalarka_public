import logging
from unittest.mock import MagicMock, patch

import pytest
import requests
from src.lib.message_sender import MessageSender


@pytest.fixture
def message_sender_instance():
    return MessageSender(server_url="http://test-server.com", agent_id="test-agent-id")


@pytest.fixture
def mock_content():
    return {"hostname": "test-host"}


def test_send_message_success(message_sender_instance, mock_content, caplog):
    message_count = 5

    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        with caplog.at_level(logging.INFO):
            result = message_sender_instance.send_message(
                mock_content, message_count
            )

            assert result is True
            mock_post.assert_called_once()

            # Verify payload structure (the timestamp is not checked for an exact value)
            args, kwargs = mock_post.call_args
            assert args[0] == "http://test-server.com/api/message"
            payload = kwargs["json"]
            assert payload["content"] == mock_content
            assert isinstance(payload["client_timestamp"], int)
            assert "agent_id" not in payload

            assert (
                f"test-agent-id: Check-in delivered - sent in total: {message_count}"
                in caplog.text
            )


def test_send_message_server_error(
    message_sender_instance, mock_content, caplog
):
    message_count = 5

    with patch("requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        with caplog.at_level(logging.ERROR):
            result = message_sender_instance.send_message(
                mock_content, message_count
            )

            assert result is False
            mock_post.assert_called_once()
            assert "test-agent-id: Sending failed - 500" in caplog.text


def test_send_message_connection_error(
    message_sender_instance, mock_content, caplog
):
    message_count = 5

    with patch(
        "requests.post",
        side_effect=requests.exceptions.ConnectionError("Mocked Connection Error"),
    ) as mock_post:
        with caplog.at_level(logging.ERROR):
            result = message_sender_instance.send_message(
                mock_content, message_count
            )

            assert result is False
            mock_post.assert_called_once()
            assert (
                "test-agent-id: Can't connect to the server http://test-server.com"
                in caplog.text
            )
