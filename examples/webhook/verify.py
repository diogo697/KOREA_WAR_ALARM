"""수신 원본 bytes의 HMAC 확인. event ID는 수신측 DB에 유일 키로 저장한다."""
import hashlib
import hmac
import os


def verify(body: bytes, signature: str) -> bool:
    expected = "sha256=" + hmac.new(
        os.environ["KWA_WEBHOOK_SECRET"].encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
