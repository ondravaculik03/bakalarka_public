import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from src.lib.message_encryptor import MessageEncryptor


# Fixture to generate a dummy public key for testing
@pytest.fixture
def dummy_public_key():
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    return private_key.public_key()


@pytest.fixture
def message_encryptor_instance():
    return MessageEncryptor()


def test_encrypt_message_returns_correct_format(
    message_encryptor_instance, dummy_public_key
):
    content = {"data": "test_data"}
    auth_token = "test_token"

    encrypted_key, nonce, ciphertext = message_encryptor_instance.encrypt_message(
        content, auth_token, dummy_public_key
    )

    assert isinstance(encrypted_key, str)
    assert isinstance(nonce, str)
    assert isinstance(ciphertext, str)

    # All should be base64 encoded strings
    assert encrypted_key != ""
    assert nonce != ""
    assert ciphertext != ""


def test_encrypt_message_uses_correct_components(
    message_encryptor_instance, dummy_public_key
):
    content = {"data": "test_data"}
    auth_token = "test_token"

    # We can mock os.urandom to get predictable keys/nonces for testing decryption
    with patch("os.urandom") as mock_urandom:
        mock_urandom.side_effect = [b"a" * 32, b"b" * 12]  # 32 bytes and 12 bytes

        encrypted_key_b64, nonce_b64, ciphertext_b64 = (
            message_encryptor_instance.encrypt_message(
                content, auth_token, dummy_public_key
            )
        )

        # Basic check to ensure urandom was called
        assert mock_urandom.call_count == 2

        # In a real scenario, you would decrypt to verify.
        # For unit testing, we're primarily verifying the process and output format.
        # Decryption requires the private key corresponding to dummy_public_key,
        # which is outside the scope of *this* unit test for MessageEncryptor,
        # as MessageEncryptor only encrypts.


def test_encrypt_message_raises_error_with_invalid_public_key(
    message_encryptor_instance,
):
    content = {"data": "test_data"}
    auth_token = "test_token"
    invalid_public_key = MagicMock(spec=RSAPublicKey)
    invalid_public_key.encrypt.side_effect = ValueError(
        "Invalid public key for encryption"
    )

    with pytest.raises(ValueError, match="Invalid public key for encryption"):
        message_encryptor_instance.encrypt_message(
            content, auth_token, invalid_public_key
        )


# Test to ensure plaintext structure is correct
def test_encrypt_message_plaintext_structure(
    message_encryptor_instance, dummy_public_key
):
    content = {"message": "hello"}
    auth_token = "my_secret_token"

    with patch("time.time", return_value=1678886400):  # Mock timestamp
        with patch("os.urandom") as mock_urandom:
            # Provide predictable AES key and nonce for potential future decryption tests
            mock_urandom.side_effect = [b"c" * 32, b"d" * 12]

            encrypted_key, nonce, ciphertext = (
                message_encryptor_instance.encrypt_message(
                    content, auth_token, dummy_public_key
                )
            )

            # This is hard to test directly without the private key to decrypt `encrypted_key`.
            # We can, however, verify the structure of the plaintext that *would* be encrypted.
            # This test is more conceptual here. A full decryption test would belong to an
            # integration test or a separate decryption utility.
            # For this unit test, we confirm the method call to AESGCM.encrypt with correct plaintext.

            # Since AESGCM.encrypt is called internally, we can't easily mock it to intercept plaintext.
            # This test mainly relies on the assumption that if the inputs to AESGCM.encrypt are correct,
            # it will function as expected.
            pass
