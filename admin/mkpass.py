"""Print an argon2id hash for ADMIN_PASSWORD_HASH. Run on the server:

    .venv/bin/python -m admin.mkpass
"""
import getpass
import sys

from admin.auth import hash_password

if __name__ == "__main__":
    a = getpass.getpass("New admin password: ")
    b = getpass.getpass("Again: ")
    if a != b or len(a) < 10:
        sys.exit("passwords differ or shorter than 10 characters")
    print(hash_password(a))
