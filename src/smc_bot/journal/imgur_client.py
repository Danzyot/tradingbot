"""
Imgur image uploader.

Uses anonymous upload — only requires a Client-ID (free).

Setup:
  1. Go to https://api.imgur.com/oauth2/addclient
  2. Application name: anything (e.g. "SMC Trade Bot")
  3. Authorization type: "Anonymous usage without user authorization"
  4. Set env var: IMGUR_CLIENT_ID=your_client_id
     Or pass client_id= directly to ImgurClient()
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Optional

import httpx


class ImgurClient:
    def __init__(self, client_id: Optional[str] = None):
        self.client_id = client_id or os.environ.get("IMGUR_CLIENT_ID", "")
        if not self.client_id:
            raise ValueError(
                "IMGUR_CLIENT_ID not set. "
                "Register at https://api.imgur.com/oauth2/addclient "
                "then set env var or pass client_id="
            )

    def upload_file(self, path: Path) -> str:
        """Upload a PNG/JPG file. Returns the public image URL."""
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
        return self._upload_b64(data, title=path.stem)

    def upload_bytes(self, image_bytes: bytes, title: str = "trade") -> str:
        """Upload raw image bytes. Returns the public image URL."""
        data = base64.b64encode(image_bytes).decode()
        return self._upload_b64(data, title=title)

    def _upload_b64(self, b64_data: str, title: str = "trade") -> str:
        resp = httpx.post(
            "https://api.imgur.com/3/image",
            headers={"Authorization": f"Client-ID {self.client_id}"},
            data={"image": b64_data, "type": "base64", "title": title},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        if not result.get("success"):
            raise RuntimeError(f"Imgur upload failed: {result}")
        return result["data"]["link"]   # e.g. https://i.imgur.com/abc123.png
