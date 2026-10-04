import base64
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from product_kb.dzen_autopost import ArticleQueue
from product_kb_api.dzen_autopost_service import create_app

REGISTRY = Path(__file__).resolve().parents[1] / 'config' / 'dzen-channels.json'
HEADERS = {'Authorization': 'Bearer test-token', 'Idempotency-Key': 'test-key'}


def test_integration_is_read_only_and_not_verified(client):
    for path in ('/api/v1/integration', '/api/v1/integration/contract'):
        assert client.get(path).status_code == 401
        assert client.post(path, headers=HEADERS, json={'status': 'READY'}).status_code == 405
    data = client.get('/api/v1/integration', headers=HEADERS).json()
    assert data['session'] == {'status': 'NOT_CONFIGURED', 'checked_at': None}
    assert not data['live_ready'] and not data['adapter']['installed']
    assert not any(data['capabilities'].values())
    assert len(data['channels']) == 5
    assert all(not c['access_verified'] for c in data['channels'])
    contract = client.get('/api/v1/integration/contract', headers=HEADERS).json()
    assert not contract['implemented'] and 'UNCERTAIN' in contract['receipt_states']


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path, REGISTRY, token='test-token', worker=False)
    with TestClient(app) as client:
        yield client


def article(**updates):
    return {'project_key': 'galvanize', 'title': 'Заголовок',
            'blocks': [{'type': 'paragraph', 'text': 'Текст статьи'}], 'mode': 'draft', **updates}


def png():
    out = io.BytesIO()
    Image.new('RGB', (30, 20), 'blue').save(out, format='PNG')
    return base64.b64encode(out.getvalue()).decode()


def test_auth_and_channels(client):
    assert client.get('/health').json()['live_ready'] is False
    assert client.get('/api/v1/channels').status_code == 401
    channels = client.get('/api/v1/channels', headers=HEADERS).json()
    assert len(channels['items']) == 5
    assert channels['account_key'] == 'shared-dzen-account'
    for ch in channels['items']:
        data = article(project_key=ch['project_key'])
        job = client.post('/api/v1/jobs', headers=HEADERS, json=data).json()
        assert job['channel_id'] == ch['channel_id']
        assert job['account_key'] == channels['account_key']


def test_idempotency_and_spoofed_channel(client):
    first = client.post('/api/v1/jobs', headers=HEADERS, json=article())
    second = client.post('/api/v1/jobs', headers=HEADERS, json=article())
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()['id'] == second.json()['id']
    assert client.post('/api/v1/jobs', headers=HEADERS, json=article(title='Другой')).status_code == 409
    assert client.post('/api/v1/jobs', headers=HEADERS, json=article(channel_id='wrong')).status_code == 422
    assert client.post('/api/v1/jobs', headers=HEADERS, json=article(project_key='unknown')).status_code == 422
    assert client.get('/api/v1/jobs', headers=HEADERS).json()['total'] == 1


def test_images_order_escape_and_preview(client):
    result = client.post('/api/v1/media', headers=HEADERS, json={'data_base64': png()})
    assert result.status_code == 201
    mid = result.json()['media_id']
    assert client.post('/api/v1/media', headers=HEADERS, json={'data_base64': png()}).json()['media_id'] == mid
    data = article(title='<script>alert(1)</script>', cover_media_id=mid, blocks=[
        {'type': 'heading', 'text': 'Первый'},
        {'type': 'image', 'media_id': mid, 'caption': '<img onerror=x>'},
        {'type': 'list', 'items': ['Второй', 'Третий']},
        {'type': 'quote', 'text': 'Четвёртый'}])
    job = client.post('/api/v1/jobs', headers=HEADERS, json=data).json()
    preview = client.get('/api/v1/jobs/'+job['id']+'/preview', headers=HEADERS).text
    assert '<script>' not in preview and '&lt;script&gt;' in preview
    assert '<img onerror=x>' not in preview
    assert preview.index('Первый') < preview.index('&lt;img') < preview.index('Второй') < preview.index('Четвёртый')
    assert preview.count('data:image/png;base64,') == 2
    assert client.get('/api/v1/media/'+mid, headers=HEADERS).content.startswith(b'\x89PNG')


@pytest.mark.parametrize('data', ['not base64', base64.b64encode(b'not image').decode()])
def test_invalid_image(client, data):
    result = client.post('/api/v1/media', headers=HEADERS, json={'data_base64': data})
    assert result.status_code == 422
    assert result.json()['error']['code'] == 'INVALID_IMAGE'


@pytest.mark.parametrize('updates', [
    {'title': '   '}, {'blocks': []},
    {'blocks': [{'type': 'image'}]},
    {'blocks': [{'type': 'paragraph', 'text': 'Hi', 'media_id': 'a'*64}]},
    {'publish_at': '2027-01-01T00:00:00'},
    {'cover_media_id': 'a'*64},
])
def test_reject_invalid_articles(client, updates):
    assert client.post('/api/v1/jobs', headers=HEADERS, json=article(**updates)).status_code in (404, 422)


def test_blocked_retry_never_claims_publication(client):
    job = client.post('/api/v1/jobs', headers=HEADERS, json=article(mode='publish')).json()
    queue = client.app.state.queue
    assert queue.process_one()
    blocked = client.get('/api/v1/jobs/'+job['id'], headers=HEADERS).json()
    assert blocked['status'] == 'BLOCKED'
    assert blocked['error_code'] == 'DZEN_TRANSPORT_UNAVAILABLE'
    assert blocked['published_url'] is None and blocked['draft_url'] is None
    assert blocked['verified'] is False
    retried = client.post('/api/v1/jobs/'+job['id']+'/retry', headers=HEADERS).json()
    assert retried['id'] == job['id'] and retried['status'] == 'QUEUED'
    assert client.get('/api/v1/jobs', headers=HEADERS).json()['total'] == 1
    queue.process_one()
    assert queue.get(job['id'])['attempts'] == 2


def test_schedule_restart_and_atomic_claim(tmp_path):
    queue = ArticleQueue(tmp_path, REGISTRY)
    due, _ = queue.create(article(), 'due')
    later = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    future, _ = queue.create(article(publish_at=later), 'future')
    with ThreadPoolExecutor(max_workers=4) as executor:
        claims = list(executor.map(lambda _: queue.claim(), range(4)))
    assert sum(x is not None for x in claims) == 1
    restarted = ArticleQueue(tmp_path, REGISTRY)
    restarted.recover()
    assert restarted.get(due['id'])['status'] == 'QUEUED'
    assert restarted.process_one()
    assert restarted.process_one() is False
    assert restarted.get(future['id'])['status'] == 'QUEUED'


def test_timezone_and_pagination(client):
    data = article(publish_at='2027-01-01T12:00:00+03:00')
    job = client.post('/api/v1/jobs', headers=HEADERS, json=data).json()
    assert job['publish_at'] == '2027-01-01T09:00:00+00:00'
    assert client.get('/api/v1/jobs?limit=0', headers=HEADERS).status_code == 422
    assert client.get('/api/v1/jobs/missing', headers=HEADERS).status_code == 404
    assert client.post('/api/v1/jobs/'+job['id']+'/retry', headers=HEADERS).status_code == 409


def test_dashboard_and_validation_do_not_expose_input(client):
    assert 'пять каналов' in client.get('/').text
    secret_input = 'sensitive-value'
    result = client.post('/api/v1/jobs', headers=HEADERS, json=article(mode=secret_input))
    assert secret_input not in result.text
    assert client.get('/api/v1/openapi.json', headers=HEADERS).status_code == 200


def test_reverse_proxy_prefix_and_host(tmp_path):
    app = create_app(tmp_path, REGISTRY, token='test-token', worker=False,
                     root_path='/dz', allowed_hosts=['galvanize.ru'])
    with TestClient(app, base_url='https://galvanize.ru') as client:
        response = client.get('/dz/')
        assert response.status_code == 200
        assert 'const apiBase="/dz/api/v1/";' in response.text
        assert client.get('/dz/api/v1/channels', headers=HEADERS).json()['account_key'] == 'shared-dzen-account'
        assert client.get('/dz/health').json()['live_ready'] is False
        assert client.get('/dz/health', headers={'Host': 'evil.example'}).status_code == 400
    with pytest.raises(ValueError):
        create_app(tmp_path, REGISTRY, token='test-token', root_path='/dz/../')


def test_client_accepts_https_service_but_rejects_remote_plaintext():
    from product_kb.dzen_autopost_client import DzenQueueClient
    client = DzenQueueClient('test-token', 'https://galvanize.ru/dz/')
    assert client.base_url == 'https://galvanize.ru/dz'
    for url in ['http://galvanize.ru/dz', 'https://user:pass@galvanize.ru/dz', 'https://galvanize.ru/dz?token=x', 'https://galvanize.ru/dz/../']:
        with pytest.raises(ValueError):
            DzenQueueClient('test-token', url)
