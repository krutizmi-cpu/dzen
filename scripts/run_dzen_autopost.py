"""Run the local queue on loopback. No live publication transport is enabled."""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn

from product_kb_api.dzen_autopost_service import create_app, runtime_directory

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=runtime_directory())
    parser.add_argument("--root-path", default="")
    parser.add_argument("--allowed-host", action="append", default=[])
    args = parser.parse_args()
    app = create_app(directory=args.data_dir, root_path=args.root_path,
                     allowed_hosts=["127.0.0.1", "localhost"] + args.allowed_host if args.allowed_host else None)
    (args.data_dir / "service-info.json").write_text(json.dumps({
        "url": f"http://127.0.0.1:{args.port}", "pid": os.getpid(),
        "token_file": str(args.data_dir / "api-token.txt"), "live_ready": False,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")
