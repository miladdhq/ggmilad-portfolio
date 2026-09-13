from admin.auth import Lockout, Sessions, hash_password, verify_password


def test_password_roundtrip():
    h = hash_password("gg-secret")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "gg-secret")
    assert not verify_password(h, "nope")
    assert not verify_password("not-a-hash", "gg-secret")


def test_session_token_roundtrip():
    s = Sessions("k", 60)
    assert s.check(s.issue())
    assert not s.check("garbage")
    assert not s.check(None)
    assert not s.check("")


def test_session_expires():
    assert not Sessions("k", -1).check(Sessions("k", -1).issue())


def test_session_secret_bound():
    assert not Sessions("b", 60).check(Sessions("a", 60).issue())


def test_lockout_after_five_then_releases():
    t = [0.0]
    lk = Lockout(limit=5, window=900, clock=lambda: t[0])
    for _ in range(4):
        lk.record_failure("1.1.1.1")
    assert not lk.is_locked("1.1.1.1")
    lk.record_failure("1.1.1.1")
    assert lk.is_locked("1.1.1.1")
    assert not lk.is_locked("2.2.2.2")
    t[0] = 901
    assert not lk.is_locked("1.1.1.1")


def test_lockout_reset_on_success():
    lk = Lockout()
    for _ in range(4):
        lk.record_failure("x")
    lk.reset("x")
    for _ in range(4):
        lk.record_failure("x")
    assert not lk.is_locked("x")
