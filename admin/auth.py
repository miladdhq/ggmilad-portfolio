"""One password, signed sessions, and a per-IP lockout.

The lockout is in memory on purpose: the service runs one uvicorn worker,
and a restart clearing it is fine.
"""
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

_ph = PasswordHasher()


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(hash_: str, pw: str) -> bool:
    try:
        return _ph.verify(hash_, pw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


class Sessions:
    def __init__(self, secret: str, max_age: int):
        self._signer = TimestampSigner(secret, salt="gg-admin-session")
        self.max_age = max_age

    def issue(self) -> str:
        return self._signer.sign(b"admin").decode()

    def check(self, token) -> bool:
        if not token:
            return False
        try:
            return self._signer.unsign(token, max_age=self.max_age) == b"admin"
        except (BadSignature, SignatureExpired):
            return False


class Lockout:
    """`limit` failures lock that IP for `window` seconds."""

    def __init__(self, limit: int = 5, window: int = 15 * 60, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self._fails: dict[str, int] = {}
        self._until: dict[str, float] = {}

    def is_locked(self, ip: str) -> bool:
        until = self._until.get(ip)
        if until is None:
            return False
        if self.clock() >= until:
            self._until.pop(ip, None)
            self._fails.pop(ip, None)
            return False
        return True

    def record_failure(self, ip: str) -> None:
        n = self._fails.get(ip, 0) + 1
        self._fails[ip] = n
        if n >= self.limit:
            self._until[ip] = self.clock() + self.window
            self._fails[ip] = 0

    def reset(self, ip: str) -> None:
        self._fails.pop(ip, None)
        self._until.pop(ip, None)
