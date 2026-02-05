import base64
import json
import os
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class MessageEncryptor:
    def encrypt_message(
        self, content: dict, auth_token: str, public_key: RSAPublicKey
    ) -> tuple[str, str, str]:
        """
        Encrypts a message using AES-GCM and encrypts the AES key with RSA-OAEP.

        Returns a tuple: (encrypted_key_b64, nonce_b64, ciphertext_b64)
        """
        # 2) Vygeneruj náhodný AES klíč a nonce
        aes_key = os.urandom(32)  # 256-bit
        nonce = os.urandom(12)  # 96-bit pro GCM

        # 3) Připrav plaintext s časem a obsahem, pak zašifruj přes AES-GCM
        plaintext_obj = {
            "content": content,
            "client_timestamp": int(time.time()),
            "auth_token": auth_token,
        }
        plaintext_bytes = json.dumps(plaintext_obj, ensure_ascii=False).encode("utf-8")
        aesgcm = AESGCM(aes_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, None)

        # 4) Zašifruj AES klíč veřejným RSA klíčem serveru
        enc_key = public_key.encrypt(
            aes_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )

        encrypted_key_b64 = base64.b64encode(enc_key).decode("utf-8")
        nonce_b64 = base64.b64encode(nonce).decode("utf-8")
        ciphertext_b64 = base64.b64encode(ciphertext).decode("utf-8")

        return encrypted_key_b64, nonce_b64, ciphertext_b64
