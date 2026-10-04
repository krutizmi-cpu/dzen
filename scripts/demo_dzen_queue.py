"""Submit the original local fixture to the LOCAL API, without publishing."""
import argparse
import json
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class FixtureParser(HTMLParser):
    def __init__(self, images):
        super().__init__()
        self.images, self.blocks, self.tag, self.text = images, [], None, []
        self.title = "Что проверить перед передачей посылки"

    def handle_starttag(self, tag, attrs):
        if tag in {"h1", "h2", "p", "li"}:
            self.tag, self.text = tag, []
        if tag == "img":
            source = Path(dict(attrs).get("src", "")).name
            if source in self.images:
                self.blocks.append({"type": "image", "media_id": self.images[source]})

    def handle_data(self, data):
        if self.tag:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == self.tag:
            text = "".join(self.text).strip()
            if text:
                if tag == "h1":
                    self.title = text
                else:
                    self.blocks.append({"type": "heading" if tag == "h2" else "paragraph", "text": text})
            self.tag = None


if __name__ == "__main__":
    from product_kb.dzen_autopost_client import DzenQueueClient
    from product_kb_api.dzen_autopost_service import runtime_directory

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=runtime_directory())
    args = parser.parse_args()
    fixture = ROOT / ".codex-artifacts/dzen-publisher-evaluation/fixture"
    if not fixture.exists():
        fixture = ROOT / "sample"
    token = (args.data_dir / "api-token.txt").read_text(encoding="utf-8").strip()
    client = DzenQueueClient(token, f"http://127.0.0.1:{args.port}")
    images = {name: client.upload_image(fixture / name) for name in ["cover.png", "order-check.png", "handoff.png"]}
    article = FixtureParser(images)
    article.feed((fixture / "article.html").read_text(encoding="utf-8"))
    job = client.submit({"project_key": "cdekarbat", "title": article.title,
                         "blocks": article.blocks, "cover_media_id": images['cover.png'], "mode": "draft"},
                        "original-fixture-local-v1")
    print(json.dumps({"job_id": job['id'], "status": job['status'], "blocks": len(article.blocks), "images": len(images), "live_upload": False}, ensure_ascii=False))
