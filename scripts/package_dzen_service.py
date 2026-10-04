"""Build a source handoff package; never include runtime credentials or queue data."""
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    'product_kb/__init__.py', 'product_kb/dzen_autopost.py', 'product_kb/dzen_autopost_client.py',
    'product_kb/dzen_integration.py', 'docs/dzen-adapter-contract.md',
    'product_kb_api/__init__.py', 'product_kb_api/dzen_autopost_service.py',
    'product_kb_api/dzen_autopost_dashboard.html', 'config/dzen-channels.json',
    'scripts/run_dzen_autopost.py', 'scripts/demo_dzen_queue.py', 'scripts/package_dzen_service.py',
    'tests/test_dzen_autopost.py', 'requirements-dzen.txt', 'docs/dzen-autopost-service.md',
]

if __name__ == '__main__':
    output = ROOT / '.codex-artifacts/dzen-autopost-service'
    output.mkdir(parents=True, exist_ok=True)
    archive = output / 'dzen-autopost-service-local-v0.1.zip'
    manifest = {'version': '0.1.0', 'live_transport': 'disabled', 'files': {}}
    with ZipFile(archive, 'w', ZIP_DEFLATED) as package:
        for relative in FILES:
            data = (ROOT / relative).read_bytes()
            package.writestr(relative, data)
            manifest['files'][relative] = hashlib.sha256(data).hexdigest()
        fixture = ROOT / '.codex-artifacts/dzen-publisher-evaluation/fixture'
        if not fixture.exists():
            fixture = ROOT / 'sample'
        for name in ['article.html', 'cover.png', 'order-check.png', 'handoff.png']:
            data = (fixture / name).read_bytes()
            relative = 'sample/' + name
            package.writestr(relative, data)
            manifest['files'][relative] = hashlib.sha256(data).hexdigest()
        package.writestr('MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'archive': str(archive), 'files': len(manifest['files']), 'bytes': archive.stat().st_size, 'live_transport': 'disabled'}, ensure_ascii=False))
