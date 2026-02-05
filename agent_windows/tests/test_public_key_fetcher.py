from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from src.lib.public_key_fetcher import PublicKeyFetcher


@pytest.fixture
def mock_public_key_pem():
    # Generate a dummy RSA private key and then extract the public key PEM
    # for testing purposes. This ensures a valid PEM format.
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    public_key = private_key.public_key()
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


@pytest.fixture
def public_key_fetcher_instance():
    return PublicKeyFetcher("http://test-server.com")


def test_fetch_public_key_success(public_key_fetcher_instance, mock_public_key_pem):
    with patch("requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"public_key_pem": mock_public_key_pem}
        mock_get.return_value = mock_response

        public_key = public_key_fetcher_instance.fetch_public_key()

        assert isinstance(public_key, RSAPublicKey)
        mock_get.assert_called_once_with("http://test-server.com/api/public_key")
        # Ensure the fetched key is correctly loaded
        assert (
            public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("utf-8")
            == mock_public_key_pem
        )


def test_fetch_public_key_caching(public_key_fetcher_instance, mock_public_key_pem):
    with patch("requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"public_key_pem": mock_public_key_pem}
        mock_get.return_value = mock_response

        # First call, should make a request
        key1 = public_key_fetcher_instance.fetch_public_key()
        # Second call, should use cached key
        key2 = public_key_fetcher_instance.fetch_public_key()

        assert key1 is key2  # Verify same object instance due to caching
        mock_get.assert_called_once()  # Verify request was only made once


def test_fetch_public_key_connection_error(public_key_fetcher_instance):
    from requests.exceptions import ConnectionError

    with patch(
        "requests.get", side_effect=ConnectionError("Mocked Connection Error")
    ) as mock_get:
        with pytest.raises(ConnectionError):
            public_key_fetcher_instance.fetch_public_key()
        mock_get.assert_called_once()


def test_fetch_public_key_http_error(public_key_fetcher_instance):
    from requests.exceptions import HTTPError

    with patch("requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = HTTPError("Mocked HTTP Error")
        mock_get.return_value = mock_response

        with pytest.raises(HTTPError):
            public_key_fetcher_instance.fetch_public_key()
        mock_get.assert_called_once()
        mock_response.raise_for_status.assert_called_once()
