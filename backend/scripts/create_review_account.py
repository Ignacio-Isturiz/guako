"""Create the account that Google Play and App Store reviewers use to log in to Guako.

The stores ask for working credentials in the review notes (the app is behind a login). The account is created
through the public API, exactly like a learner signing up (terms accepted, same rules), so no database access
is needed. The password is generated here and printed ONCE: copy it into Play Console and App Store Connect,
never into the repository.

    python -m scripts.create_review_account --email revision@your-domain.com
    python -m scripts.create_review_account --email revision@your-domain.com --api http://127.0.0.1:8000

Then log in once with it and try a short conversation, so the reviewer starts from a working account.
"""

import argparse
import secrets
import string
import sys

import httpx

from app.config import settings

DEFAULT_API = "https://guako.onrender.com"


def _password() -> str:
    """16 characters with letters and digits (meets the sign-up rules)."""
    alphabet = string.ascii_letters + string.digits
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(16))
        if any(c.isdigit() for c in value) and any(c.isupper() for c in value) and any(c.islower() for c in value):
            return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--email", required=True, help="Mailbox you control (reviewers may need to contact it)")
    parser.add_argument("--username", default="store_review", help="3-30 letters, digits, _ . -")
    parser.add_argument("--api", default=DEFAULT_API, help=f"Backend base URL (default {DEFAULT_API})")
    args = parser.parse_args()

    password = _password()
    body = {
        "username": args.username,
        "email": args.email,
        "password": password,
        "accept_terms": True,
        "terms_version": settings.legal_version,
    }
    with httpx.Client(base_url=args.api.rstrip("/"), timeout=60) as client:
        created = client.post("/api/auth/register", json=body)
        if created.status_code != 201:
            print(f"Could not create the account ({created.status_code}): {created.text}", file=sys.stderr)
            return 1
        login = client.post("/api/auth/login", data={"username": args.email, "password": password})
        if login.status_code != 204:
            print(f"Account created but the login failed ({login.status_code}): {login.text}", file=sys.stderr)
            return 1

    print("Review account ready. Copy these into Play Console (App access) and App Store Connect (App Review):")
    print(f"  email:    {args.email}")
    print(f"  password: {password}")
    print("This password is not stored anywhere else.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
