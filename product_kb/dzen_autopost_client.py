"""Client for the local article service. Never contacts Dzen."""
import base64
import json
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


class DzenQueueClient:
    def __init__(self, token: str, base_url: str = "http://127.0.0.1:8765"):
        parsed = urlsplit(base_url)
        loopback = parsed.hostname in {"127.0.0.1", "localhost"}
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or (not loopback and parsed.scheme != "https")
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or any(segment in {".", ".."} for segment in parsed.path.split("/"))):
            raise ValueError("Requires HTTPS service URL, or HTTP loopback, without credentials/query")
        self.base_url, self.token = base_url.rstrip("/"), token

    def request(self, path: str, data=None, key=None):
        headers = {"Authorization": "Bearer " + self.token}
        if key:
            headers["Idempotency-Key"] = key
        body = None
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + "/api/v1/" + path, data=body, headers=headers)
        # Ignore machine proxy settings for local communication.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            result = json.loads(exc.read())
            raise RuntimeError(result.get("error", {}).get("message", "Local API error")) from None

    def upload_image(self, path: Path):
        raw = Path(path).read_bytes()
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("Image exceeds 8 MB")
        return self.request("media", {"data_base64": base64.b64encode(raw).decode()})["media_id"]

    def submit(self, article: dict, idempotency_key: str):
        return self.request("jobs", article, idempotency_key)

    def job(self, job_id: str):
        return self.request("jobs/" + job_id)
