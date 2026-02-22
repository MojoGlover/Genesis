"""Twilio base client - credentials and shared HTTP"""
from __future__ import annotations
import os
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TwilioConfig:
    account_sid: str
    auth_token: str
    from_number: str          # Your Twilio phone number e.g. +15551234567
    to_number: str            # Your personal number for alerts
    webhook_base_url: str = ""  # Public URL for voice webhooks (ngrok or VPS)


class TwilioClient:
    """Base Twilio client. Credentials loaded from config or env vars."""

    def __init__(self, config: Optional[TwilioConfig] = None):
        self.config = config or self._load_from_env()
        self._client = None

    def _load_from_env(self) -> TwilioConfig:
        return TwilioConfig(
            account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
            auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
            from_number=os.getenv("TWILIO_FROM_NUMBER", ""),
            to_number=os.getenv("TWILIO_TO_NUMBER", ""),
            webhook_base_url=os.getenv("TWILIO_WEBHOOK_URL", ""),
        )

    @property
    def client(self):
        if self._client is None:
            try:
                from twilio.rest import Client
                self._client = Client(self.config.account_sid, self.config.auth_token)
            except ImportError:
                raise RuntimeError("Run: pip install twilio")
        return self._client

    def is_configured(self) -> bool:
        return bool(self.config.account_sid and self.config.auth_token and self.config.from_number)

    def get_status(self) -> dict:
        return {
            "configured": self.is_configured(),
            "from_number": self.config.from_number or "not set",
            "to_number": self.config.to_number or "not set",
            "webhook_url": self.config.webhook_base_url or "not set",
        }
