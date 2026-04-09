"""
Discord webhook image uploader.

Posts a screenshot as a message attachment to a Discord channel webhook.
The attachment URL is a permanent Discord CDN link usable in Notion image blocks.

Setup:
  1. In Discord: open a server (or create a private one)
  2. Right-click a channel → Edit Channel → Integrations → Webhooks → New Webhook
  3. Copy the webhook URL
  4. Set env var: DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
     Or pass webhook_url= directly to DiscordClient()
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import httpx


class DiscordClient:
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL", "")
        if not self.webhook_url:
            raise ValueError(
                "DISCORD_WEBHOOK_URL not set. "
                "Create a webhook in Discord (channel → Integrations → Webhooks) "
                "then set env var or pass webhook_url="
            )

    def upload_file(self, path: Path, caption: str = "") -> str:
        """
        Upload a PNG/JPG file to Discord via webhook.
        Returns the permanent CDN URL of the attachment.
        """
        with open(path, "rb") as f:
            image_bytes = f.read()
        return self.upload_bytes(image_bytes, filename=path.name, caption=caption)

    def upload_bytes(self, image_bytes: bytes, filename: str = "trade.png", caption: str = "") -> str:
        """
        Upload raw image bytes to Discord via webhook.
        Returns the permanent CDN URL of the attachment.
        """
        resp = httpx.post(
            self.webhook_url,
            data={"content": caption} if caption else {},
            files={"file": (filename, image_bytes, "image/png")},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        attachments = data.get("attachments", [])
        if not attachments:
            raise RuntimeError(f"Discord returned no attachments: {data}")
        return attachments[0]["url"]
