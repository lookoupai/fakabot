import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet

from app.config import Settings


class TokenCrypto:
    def __init__(self, settings: Settings) -> None:
        if settings.token_encryption_key is None:
            raise RuntimeError("缺少 TOKEN_ENCRYPTION_KEY，无法处理 Bot Token")
        self._key = settings.token_encryption_key.get_secret_value()
        self._fernet = Fernet(self._key.encode())

    def encrypt_token(self, token: str) -> str:
        return self._fernet.encrypt(token.encode()).decode()

    def decrypt_token(self, encrypted_token: str) -> str:
        return self._fernet.decrypt(encrypted_token.encode()).decode()

    def token_hash(self, token: str) -> str:
        return hmac.new(self._key.encode(), token.encode(), hashlib.sha256).hexdigest()


def generate_webhook_secret() -> str:
    return secrets.token_urlsafe(32)


def mask_token(token: str) -> str:
    if ":" not in token:
        return "***"
    prefix, suffix = token.split(":", 1)
    return f"{prefix[:4]}***:{suffix[:4]}***{suffix[-4:]}"

