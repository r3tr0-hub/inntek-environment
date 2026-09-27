"""Password hashing for local-user auth — stdlib only (no passlib/bcrypt dep).

Hashes use PBKDF2-HMAC-SHA256 with a per-password random salt, serialised as a
single self-describing string::

    pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>

This is the value stored in ``AUTH_USERS[].password_hash``. Generate one with the
``labeljetty-hash-password`` CLI (see :func:`hash_password_cli`).
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import secrets
import sys

ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 600_000
SALT_BYTES = 16


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def hash_password(password: str, *, iterations: int = DEFAULT_ITERATIONS) -> str:
    """Hash a plaintext password into a storable ``pbkdf2_sha256$…`` string."""
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{ALGORITHM}${iterations}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of ``password`` against a stored ``pbkdf2_sha256$…`` hash.

    Returns ``False`` (rather than raising) on any malformed stored value.
    """
    try:
        algorithm, iter_str, salt_b64, hash_b64 = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        iterations = int(iter_str)
        salt = _unb64(salt_b64)
        expected = _unb64(hash_b64)
    except (ValueError, TypeError):
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return secrets.compare_digest(candidate, expected)


def hash_password_cli() -> None:
    """Entry point for ``labeljetty-hash-password``.

    Usage::

        labeljetty-hash-password [password]

    With no argument it prompts twice (hidden input). Prints the hash string to
    paste into ``AUTH_USERS``.
    """
    if len(sys.argv) > 1:
        password = sys.argv[1]
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat: ") != password:
            print("Passwords do not match.", file=sys.stderr)
            sys.exit(1)
    if not password:
        print("Empty password.", file=sys.stderr)
        sys.exit(1)
    print(hash_password(password))


if __name__ == "__main__":
    hash_password_cli()
