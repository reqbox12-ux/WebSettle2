"""
shared/crypto.py — 개인정보 컬럼 암호화 (AES-GCM) + 검색용 blind index (HMAC)

- 마스터키: 환경변수 CRM_ENC_KEY 우선, 없으면 data/secret.key 자동생성(.gitignore 대상)
  → 키는 DB와 분리 보관. DB만 유출되면 복호화 불가.
- encrypt(): 'enc1:'+base64(nonce+ct). 이미 암호화된 값/빈값은 그대로 통과.
- decrypt(): 'enc1:' 접두 없으면 평문으로 간주하고 그대로 반환(마이그레이션 전 호환).
- blind_index()/blind_phone(): 같은 입력→같은 해시. 로그인·중복확인·검색용.
"""
from __future__ import annotations
import os
import base64
import hmac
import hashlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_PREFIX = "enc1:"


def _load_key() -> bytes:
    env = os.getenv("CRM_ENC_KEY")
    if env:
        try:
            raw = base64.urlsafe_b64decode(env + "=" * (-len(env) % 4))
            if len(raw) >= 32:
                return raw[:32]
        except Exception:
            pass
        return hashlib.sha256(env.encode()).digest()
    # 폴백: data/secret.key (없으면 1회 생성)
    p = Path(__file__).resolve().parent.parent / "data" / "secret.key"
    if p.exists():
        b = p.read_bytes()
        if len(b) >= 32:
            return b[:32]
    p.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(32)
    p.write_bytes(key)
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass
    return key


_KEY = _load_key()
_AES = AESGCM(_KEY)


def encrypt(plain) -> str:
    if plain is None or plain == "":
        return plain if plain is not None else ""
    s = str(plain)
    if s.startswith(_PREFIX):
        return s
    nonce = os.urandom(12)
    ct = _AES.encrypt(nonce, s.encode("utf-8"), None)
    return _PREFIX + base64.urlsafe_b64encode(nonce + ct).decode()


def decrypt(token):
    if not isinstance(token, str) or not token.startswith(_PREFIX):
        return token   # 평문(레거시) 그대로
    try:
        raw = base64.urlsafe_b64decode(token[len(_PREFIX):])
        return _AES.decrypt(raw[:12], raw[12:], None).decode("utf-8")
    except Exception:
        return token


def is_encrypted(v) -> bool:
    return isinstance(v, str) and v.startswith(_PREFIX)


def blind_index(value: str) -> str:
    if not value:
        return ""
    return hmac.new(_KEY, str(value).strip().encode("utf-8"), hashlib.sha256).hexdigest()


def blind_phone(value: str) -> str:
    digits = "".join(c for c in str(value or "") if c.isdigit())
    if not digits:
        return ""
    return hmac.new(_KEY, digits.encode("utf-8"), hashlib.sha256).hexdigest()
