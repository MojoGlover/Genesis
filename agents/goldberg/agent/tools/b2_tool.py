"""
b2_tool.py — Backblaze B2 cloud storage integration for Goldberg.

Three actions:
  list_files(prefix)               — list files in the bucket (optional prefix filter)
  upload_file(local_path, dest)    — upload a local file to B2
  download_file(remote_name, dest) — download a file from B2 to a local path

Credentials: reads B2_KEY_ID, B2_APPLICATION_KEY, B2_BUCKET_NAME from env.
Uses the Backblaze B2 native HTTP API (no b2sdk dependency).
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

_B2_AUTH_URL = "https://api.backblazeb2.com/b2api/v3/b2_authorize_account"
_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=300.0, pool=5.0)


def _creds() -> tuple[str, str, str]:
    key_id = os.environ.get("B2_KEY_ID", "").strip()
    app_key = os.environ.get("B2_APPLICATION_KEY", "").strip()
    bucket = os.environ.get("B2_BUCKET_NAME", "").strip()
    if not (key_id and app_key and bucket):
        raise RuntimeError("B2_KEY_ID, B2_APPLICATION_KEY, B2_BUCKET_NAME must all be set")
    return key_id, app_key, bucket


def _authorize() -> dict:
    key_id, app_key, _ = _creds()
    resp = httpx.get(_B2_AUTH_URL, auth=(key_id, app_key), timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ── Public functions ──────────────────────────────────────────────────────────

def list_files(prefix: str = "", limit: int = 100) -> dict:
    """
    List files in the configured B2 bucket.

    prefix: optional filename prefix to filter results
    limit: max files to return (default 100)
    """
    try:
        _, _, bucket_name = _creds()
        auth = _authorize()
        api_url = auth["apiInfo"]["storageApi"]["apiUrl"]
        token = auth["authorizationToken"]

        # Resolve bucket_id from bucket name
        resp = httpx.post(
            f"{api_url}/b2api/v3/b2_list_buckets",
            headers={"Authorization": token},
            json={"accountId": auth["accountId"], "bucketName": bucket_name},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        buckets = resp.json().get("buckets", [])
        if not buckets:
            return {"ok": False, "error": f"Bucket '{bucket_name}' not found"}
        bucket_id = buckets[0]["bucketId"]

        # List files
        payload: dict = {"bucketId": bucket_id, "maxFileCount": limit}
        if prefix:
            payload["prefix"] = prefix

        resp = httpx.post(
            f"{api_url}/b2api/v3/b2_list_file_names",
            headers={"Authorization": token},
            json=payload,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        files = [
            {
                "name": f["fileName"],
                "size_kb": round(f["contentLength"] / 1024, 1),
                "file_id": f["fileId"],
                "uploaded": f.get("uploadTimestamp", 0),
            }
            for f in data.get("files", [])
        ]
        return {"ok": True, "files": files, "count": len(files), "bucket": bucket_name}
    except Exception as e:
        logger.error("[b2] list_files error: %s", e)
        return {"ok": False, "error": str(e)}


def upload_file(local_path: str, dest: str = "") -> dict:
    """
    Upload a local file to B2.

    local_path: absolute path to the file to upload
    dest: remote filename/path in the bucket (defaults to the file's basename)
    """
    try:
        src = Path(local_path)
        if not src.exists():
            return {"ok": False, "error": f"File not found: {local_path}"}

        _, _, bucket_name = _creds()
        remote_name = dest or src.name
        auth = _authorize()
        api_url = auth["apiInfo"]["storageApi"]["apiUrl"]
        token = auth["authorizationToken"]

        # Resolve bucket_id
        resp = httpx.post(
            f"{api_url}/b2api/v3/b2_list_buckets",
            headers={"Authorization": token},
            json={"accountId": auth["accountId"], "bucketName": bucket_name},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        bucket_id = resp.json()["buckets"][0]["bucketId"]

        # Get upload URL
        resp = httpx.post(
            f"{api_url}/b2api/v3/b2_get_upload_url",
            headers={"Authorization": token},
            json={"bucketId": bucket_id},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        upload_data = resp.json()
        upload_url = upload_data["uploadUrl"]
        upload_token = upload_data["authorizationToken"]

        # Upload
        content = src.read_bytes()
        sha1 = hashlib.sha1(content).hexdigest()
        size_bytes = len(content)

        resp = httpx.post(
            upload_url,
            content=content,
            headers={
                "Authorization": upload_token,
                "X-Bz-File-Name": remote_name,
                "Content-Type": "b2/x-auto",
                "Content-Length": str(size_bytes),
                "X-Bz-Content-Sha1": sha1,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        result = resp.json()
        return {
            "ok": True,
            "file_id": result["fileId"],
            "name": result["fileName"],
            "size_kb": round(size_bytes / 1024, 1),
            "bucket": bucket_name,
        }
    except Exception as e:
        logger.error("[b2] upload_file error: %s", e)
        return {"ok": False, "error": str(e)}


def download_file(remote_name: str, dest: str = "") -> dict:
    """
    Download a file from B2 to a local path.

    remote_name: filename in the bucket (as shown by list_files)
    dest: local path to save to (defaults to ~/Downloads/{remote_name})
    """
    try:
        _, _, bucket_name = _creds()
        auth = _authorize()
        download_url = auth["apiInfo"]["storageApi"]["downloadUrl"]
        token = auth["authorizationToken"]

        url = f"{download_url}/file/{bucket_name}/{remote_name}"
        resp = httpx.get(
            url,
            headers={"Authorization": token},
            follow_redirects=True,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()

        local_path = Path(dest) if dest else Path.home() / "Downloads" / Path(remote_name).name
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(resp.content)

        return {
            "ok": True,
            "path": str(local_path),
            "name": remote_name,
            "size_kb": round(len(resp.content) / 1024, 1),
        }
    except Exception as e:
        logger.error("[b2] download_file error: %s", e)
        return {"ok": False, "error": str(e)}
