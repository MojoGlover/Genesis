"""
credentials.py — Signed credential storage for agent modules.

Cerberus issues credentials signed with a shared HMAC key.
Agents verify the signature before trusting any credential.
The shared key is established during the initial register_ack exchange.

Storage: data_dir/credentials/{module_name}.json (one file per module)
Key storage: data_dir/cerberus.key (written on first register_ack)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class CredentialStore:
    """
    Persistent storage for module credentials issued by Cerberus.

    Credentials are HMAC-signed by Cerberus using a shared key established
    during the register_ack handshake. The store verifies signatures before
    writing and before returning credentials to callers.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir).expanduser().resolve()
        self._creds_dir = self._data_dir / "credentials"
        self._key_file = self._data_dir / "cerberus.key"
        self._creds_dir.mkdir(parents=True, exist_ok=True)

    # ── Key management ────────────────────────────────────────────────────────

    def store_cerberus_key(self, key_bytes: bytes) -> None:
        """Persist the shared HMAC key received from Cerberus on register_ack."""
        self._key_file.write_bytes(key_bytes)
        logger.info("CredentialStore: Cerberus key written")

    def has_cerberus_key(self) -> bool:
        """Return True if a Cerberus key has been stored."""
        return self._key_file.exists() and self._key_file.stat().st_size > 0

    def _load_cerberus_key(self) -> bytes | None:
        if not self.has_cerberus_key():
            return None
        return self._key_file.read_bytes()

    # ── Signature verification ─────────────────────────────────────────────────

    def _verify_signature(self, payload: dict) -> bool:
        """
        Verify the HMAC signature in payload.

        The HMAC covers: module + agent + issued_at + nonce + sorted(credentials.keys())
        using the stored Cerberus key and SHA-256.
        """
        key = self._load_cerberus_key()
        if key is None:
            # Dev mode: no key stored yet — accept but warn
            logger.warning(
                "CredentialStore: no Cerberus key available — accepting payload without verification (dev mode)"
            )
            return True

        expected_hmac = payload.get("hmac", "")
        module = payload.get("module", "")
        agent = payload.get("agent", "")
        issued_at = str(payload.get("issued_at", ""))
        nonce = payload.get("nonce", "")
        cred_keys = sorted((payload.get("credentials") or {}).keys())

        message = (module + agent + issued_at + nonce + "".join(cred_keys)).encode("utf-8")
        computed = hmac.new(key, message, hashlib.sha256).hexdigest()

        if not hmac.compare_digest(computed, expected_hmac):
            logger.warning(
                f"CredentialStore: HMAC mismatch for module '{module}' — credential rejected"
            )
            return False
        return True

    # ── Store / load / revoke ─────────────────────────────────────────────────

    def store(self, module_name: str, payload: dict) -> bool:
        """
        Verify the HMAC signature and persist the credential payload.

        Payload format:
            {
              "module": "...",
              "agent": "...",
              "credentials": {"KEY": "value", ...},
              "issued_by": "Cerberus",
              "issued_at": <unix_timestamp>,
              "expires_at": <unix_timestamp>,
              "nonce": "...",
              "hmac": "<hex_digest>"
            }

        Returns True if stored, False if signature is invalid.
        """
        if not self._verify_signature(payload):
            return False

        dest = self._creds_dir / f"{module_name}.json"
        dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info(f"CredentialStore: credentials stored for '{module_name}'")
        return True

    def load(self, module_name: str) -> dict | None:
        """
        Return the credentials dict for module_name if the file exists,
        the credentials have not expired, and the signature is still valid.

        Returns None if expired, tampered, or not found.
        """
        path = self._creds_dir / f"{module_name}.json"
        if not path.exists():
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"CredentialStore: failed to read '{module_name}': {exc}")
            return None

        # Expiry check
        expires_at = payload.get("expires_at", 0)
        if expires_at and time.time() > expires_at:
            logger.info(f"CredentialStore: credentials for '{module_name}' are expired")
            return None

        # Signature re-verification (tamper detection)
        if not self._verify_signature(payload):
            logger.warning(
                f"CredentialStore: stored credentials for '{module_name}' failed re-verification — discarding"
            )
            return None

        return payload.get("credentials")

    def revoke(self, module_name: str) -> None:
        """Delete the credential file for module_name."""
        path = self._creds_dir / f"{module_name}.json"
        if path.exists():
            path.unlink()
            logger.info(f"CredentialStore: credentials revoked for '{module_name}'")

    def list_active(self) -> list[str]:
        """
        Return the names of all modules with valid (non-expired, verified)
        stored credentials.
        """
        active = []
        for path in sorted(self._creds_dir.glob("*.json")):
            module_name = path.stem
            if self.load(module_name) is not None:
                active.append(module_name)
        return active
