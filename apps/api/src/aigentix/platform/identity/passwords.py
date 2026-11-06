from pwdlib import PasswordHash

# Argon2id with pwdlib's recommended parameters. No custom hashing.
_hasher = PasswordHash.recommended()
# Used to equalise timing when a login targets an unknown e-mail address.
_DUMMY_HASH = _hasher.hash("timing-equalisation-dummy-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if password_hash is None:
        _hasher.verify(password, _DUMMY_HASH)
        return False
    return _hasher.verify(password, password_hash)
