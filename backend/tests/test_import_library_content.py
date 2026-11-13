import base64
from io import BytesIO
from pathlib import Path
import importlib.util

from PIL import Image
import pytest
from sqlalchemy import func, select

from test_catalog import client
from test_circulation import session
from app.db import utcnow
from app.import_library_content import import_content
from app.site_content import SiteAsset, SiteContent


def document():
    image = BytesIO()
    Image.new('RGB', (4, 4), 'blue').save(image, 'PNG')
    return {'format': 'library-public-v1', 'items': [{'kind': 'news', 'slug': 'public-news',
        'status': 'published', 'published_at': utcnow().isoformat(),
        'data': {'translations': {'kk': {'title': 'Жаңалық', 'body': 'Мәтін'}}},
        'assets': {'image': base64.b64encode(image.getvalue()).decode()}}]}


def test_dry_run_import_image_and_preserve_later_edits(client):
    data = document()
    with session() as s:
        assert import_content(s, data)['new'] == 1
        assert s.scalar(select(func.count()).select_from(SiteContent)) == 0
        assert import_content(s, data, True)['new'] == 1
        row = s.scalar(select(SiteContent))
        row.status = 'draft'
        row.data = {'translations': {'kk': {'title': 'Өзгертілді'}}}
        s.commit()
        assert import_content(s, data, True)['already_imported'] == 1
        assert row.status == 'draft'
        assert row.data['translations']['kk']['title'] == 'Өзгертілді'
        asset = s.scalar(select(SiteAsset))
        assert asset.mime == 'image/jpeg' and Image.open(BytesIO(asset.content)).format == 'JPEG'


def test_bad_image_or_draft_rejects_entire_batch(client):
    data = document()
    data['items'].append({**data['items'][0], 'slug': 'invalid', 'assets': {'image': 'not base64'}})
    with session() as s:
        with pytest.raises(ValueError):
            import_content(s, data, True)
        assert s.scalar(select(func.count()).select_from(SiteContent)) == 0
        data['items'] = data['items'][:1]
        data['items'][0]['status'] = 'draft'
        with pytest.raises(ValueError):
            import_content(s, data, True)


def test_php_empty_asset_array_is_supported(client):
    data = document()
    data['items'][0]['assets'] = []
    with session() as s:
        assert import_content(s, data, True)['new'] == 1
        assert s.scalar(select(func.count()).select_from(SiteAsset)) == 0


def test_does_not_overwrite_existing_staff_publication(client):
    data = document()
    with session() as s:
        s.add(SiteContent(kind='news', slug='public-news', status='draft', data={}))
        s.commit()
        with pytest.raises(ValueError, match='conflicts'):
            import_content(s, data, True)


def test_configuration_preserves_unrelated_secrets_and_reuses_key():
    path = Path(__file__).resolve().parents[2] / 'deploy/configure-student-frontend.py'
    spec = importlib.util.spec_from_file_location('frontend_config', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lib = '\n'.join(f'{k}=existing-value' for k in ['AD_HOST', 'AD_BIND_DN', 'AD_BIND_PASSWORD', 'AD_BASE_DN', 'AD_CA_CERT_PATH', 'APP_KEY'])
    lib += '\nAPP_URL=https://example.test\nDB_PASSWORD=unchanged-secret\n'
    utb, configured = module.plan('DB_PASSWORD=other-secret\n', lib)
    assert 'DB_PASSWORD=other-secret' in utb and 'DB_PASSWORD=unchanged-secret' in configured
    assert 'AD_BIND_PASSWORD=existing-value' in configured and 'SESSION_SECURE_COOKIE=true' in configured
    assert module.plan(utb, configured) == (utb, configured)
    with pytest.raises(ValueError, match='differs'):
        module.plan(utb, configured.replace(module.values(utb)['STUDENT_BRIDGE_KEY'], 'different'*8))


def test_website_import_keeps_edited_pages_and_deleted_people(client):
    from app.website_content import WEBSITE_SCHEMA, empty_node
    data = {'format': 'library-website-v1', 'items': [
        {'kind': 'pages', 'slug': 'contacts', 'status': 'published', 'published_at': utcnow().isoformat(),
         'data': {'translations': {'ru': {'title': 'Контакты'}}, 'page_content': empty_node(WEBSITE_SCHEMA['contacts']['schema'])}},
        {'kind': 'people', 'slug': 'staff-one', 'status': 'published', 'published_at': utcnow().isoformat(),
         'data': {'translations': {'ru': {'title': 'Тестовый сотрудник'}}, 'show_contacts': True}},
    ]}
    with session() as s:
        assert import_content(s, data)['new'] == 2
        assert s.scalar(select(func.count()).select_from(SiteContent)) == 0
        assert import_content(s, data, True)['new'] == 2
        person = s.scalar(select(SiteContent).where(SiteContent.kind == 'people'))
        person.status = 'deleted'
        page = s.scalar(select(SiteContent).where(SiteContent.kind == 'pages'))
        page.data = {**page.data, 'page_content': {'edited': True}}
        s.commit()
        assert import_content(s, data, True)['new'] == 0
        assert person.status == 'deleted' and page.data['page_content'] == {'edited': True}
