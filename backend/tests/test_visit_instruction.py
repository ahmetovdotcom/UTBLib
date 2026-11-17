from contextlib import closing

import pytest
import pypdfium2 as pdfium
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from test_catalog import client
from test_circulation import session
from test_visit_checkin import point
from app.main import app
from app.reader_models import LibraryVisit, ReaderAudit, VisitQrPoint
from app.visit_instruction import render_instruction


def pdf_text(data):
    with pdfium.PdfDocument(data) as doc:
        assert len(doc) == 1
        with closing(doc[0]) as page:
            assert page.get_width() == pytest.approx(595.276, abs=.01)
            assert page.get_height() == pytest.approx(841.89, abs=.01)
            with closing(page.get_textpage()) as text:
                return text.get_text_range()


@pytest.mark.parametrize('language,expected', [('ru', ['Уважаемый читатель,', 'Не помню логин или пароль', 'Читальный зал']),
                                              ('kk', ['Құрметті оқырман,', 'Логинімді немесе құпиясөзімді ұмыттым', 'Оқу залы'])])
def test_instruction_is_localized_a4_and_does_not_change_token_or_visits(client, point, language, expected):
    branch, token = point
    with session() as s:
        audits = s.scalar(select(func.count()).select_from(ReaderAudit))
    url = f'/api/visits/qr-points/{branch}/instruction.pdf'
    result = client.get(url, params={'base_url': 'https://library.test/', 'lang': language})
    assert result.status_code == 200, result.text[:200]
    assert result.headers['content-type'] == 'application/pdf'
    assert result.headers['content-disposition'].startswith('inline;')
    assert result.headers['cache-control'] == 'private, no-store'
    text = pdf_text(result.content)
    for phrase in expected:
        assert phrase in text
    assert f'https://library.test/visit/{token}?lang={language}'.encode() in result.content
    downloaded = client.get(url, params={'base_url': 'https://library.test', 'lang': language, 'download': 'true'})
    assert downloaded.status_code == 200
    assert downloaded.headers['content-disposition'].startswith('attachment;')
    with session() as s:
        assert s.get(VisitQrPoint, branch).token == token
        assert s.scalar(select(func.count()).select_from(LibraryVisit)) == 0
        assert s.scalar(select(func.count()).select_from(ReaderAudit)) == audits


def test_instruction_requires_active_existing_point_and_valid_origin(client, point):
    branch, _ = point
    url = f'/api/visits/qr-points/{branch}/instruction.pdf'
    for params in [{'base_url': 'javascript:alert(1)'}, {'base_url': 'https://user:pass@library.test'},
                   {'base_url': 'https://library.test/wrong'}, {'base_url': 'https://library.test', 'lang': 'en'}, {}]:
        assert client.get(url, params=params).status_code == 422
    assert client.get('/api/visits/qr-points/9999/instruction.pdf', params={'base_url': 'https://library.test'}).status_code == 404
    other = client.post('/api/reader-branches', json={'code': 'SECOND', 'name': 'аб2'}).json()['id']
    assert client.get(f'/api/visits/qr-points/{other}/instruction.pdf', params={'base_url': 'https://library.test'}).status_code == 404
    client.post(f'/api/visits/qr-points/{branch}', json={'base_url': 'https://library.test', 'enabled': False})
    assert client.get(url, params={'base_url': 'https://library.test'}).status_code == 404
    client.post(f'/api/visits/qr-points/{branch}', json={'base_url': 'https://library.test', 'enabled': True})
    client.put(f'/api/reader-branches/{branch}', json={'code': 'MAIN', 'name': 'Читальный зал', 'active': False})
    assert client.get(url, params={'base_url': 'https://library.test'}).status_code == 404


def test_instruction_permissions_match_qr_management(client, point):
    url = f'/api/visits/qr-points/{point[0]}/instruction.pdf?base_url=https%3A%2F%2Flibrary.test'
    with TestClient(app) as guest:
        assert guest.get(url).status_code == 401
    for name, permissions, status in [('observer', ['visits.view'], 403), ('scanner', ['visits.record'], 200)]:
        created = client.post('/api/users', json={'username': name, 'display_name': 'Тест', 'password': 'test-password-123', 'role': 'viewer', 'permissions': permissions})
        assert created.status_code == 201
        with TestClient(app) as user:
            assert user.post('/api/auth/login', json={'username': name, 'password': 'test-password-123'}).status_code == 200
            assert user.get(url).status_code == status


def test_branch_names_cannot_inject_markup_or_overflow_a4():
    for name in ['аб1', 'аб2', '<b>Тест & пункт</b>', 'W'*200]:
        for language in ['ru', 'kk']:
            pdf = render_instruction(name, 'https://library.test/visit/'+'A'*43+'?lang='+language, language)
            text = pdf_text(pdf)
            if name.startswith('<b>'):
                assert '<b>Тест & пункт</b>' in text
            if name == 'аб1':
                assert ('№ 1 абонемент' if language == 'kk' else 'Абонемент № 1') in text
