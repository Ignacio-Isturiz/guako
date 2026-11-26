"""Generate the VAPID key pair for the Web Push reminder (app/push.py).

    python -m scripts.vapid_keys

Prints VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY (base64url, no padding) for the backend .env. Generate them once
per environment and keep them: changing the pair invalidates every browser subscription (each one subscribes
again the next time the app opens). The private key never goes to the frontend or the repository.
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def main() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    print(f"VAPID_PUBLIC_KEY={_b64(public)}")
    print(f"VAPID_PRIVATE_KEY={_b64(private)}")


if __name__ == "__main__":
    main()
