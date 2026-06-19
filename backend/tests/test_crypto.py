"""빌링키 at-rest 암호화(crypto) 단위 테스트."""
from cryptography.fernet import Fernet

from app.core import crypto


def _with_key(monkeypatch, key: str):
    monkeypatch.setattr(crypto.settings, "BILLING_ENC_KEY", key)
    crypto._fernet.cache_clear()  # lru_cache 무효화


def test_no_key_passthrough(monkeypatch):
    """키 미설정 시 평문 그대로(기존 동작)."""
    _with_key(monkeypatch, "")
    assert crypto.encrypt_secret("billingkey_abc") == "billingkey_abc"
    assert crypto.decrypt_secret("billingkey_abc") == "billingkey_abc"
    crypto._fernet.cache_clear()


def test_roundtrip_with_key(monkeypatch):
    """키 설정 시 암호화→복호화 왕복 일치, 저장값은 평문과 다름."""
    _with_key(monkeypatch, Fernet.generate_key().decode())
    enc = crypto.encrypt_secret("billingkey_abc")
    assert enc != "billingkey_abc"
    assert enc.startswith("enc::")
    assert crypto.decrypt_secret(enc) == "billingkey_abc"
    crypto._fernet.cache_clear()


def test_legacy_plaintext_fallback(monkeypatch):
    """키가 설정돼도 접두사 없는 레거시 평문은 그대로 반환(점진 마이그레이션)."""
    _with_key(monkeypatch, Fernet.generate_key().decode())
    assert crypto.decrypt_secret("legacy_plain_key") == "legacy_plain_key"
    crypto._fernet.cache_clear()


def test_none_handling(monkeypatch):
    _with_key(monkeypatch, Fernet.generate_key().decode())
    assert crypto.encrypt_secret(None) is None
    assert crypto.decrypt_secret(None) is None
    crypto._fernet.cache_clear()
