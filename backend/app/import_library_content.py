"""One-time CLI import of the public library export; no overwrites or deletions."""
import argparse
import base64
from io import BytesIO
import json
import sys

from PIL import Image
from sqlalchemy import select

from .db import Session, User, utcnow
from .site_content import ContentInput, SiteAsset, SiteAudit, SiteContent, audit


ACTION = 'import_library_public'


def prepare(document):
    if document.get('format') not in ('library-public-v1', 'library-website-v1') or not isinstance(document.get('items'), list):
        raise ValueError('Expected library-public-v1 export')
    items, seen = [], set()
    for raw in document['items']:
        raw = dict(raw)
        assets = raw.pop('assets', {}) or {}
        if not isinstance(assets, dict):
            raise ValueError('Expected an asset object')
        payload = ContentInput.model_validate(raw)
        if payload.status != 'published' or not payload.published_at or payload.published_at > utcnow():
            raise ValueError('Only already published material can be migrated')
        allowed = ('pages', 'people') if document['format'] == 'library-website-v1' else ('news', 'events', 'resources')
        if payload.kind not in allowed:
            raise ValueError('Repository access policies require a separate migration')
        key = payload.kind, payload.slug
        if key in seen:
            raise ValueError('Duplicate publication in export')
        seen.add(key)
        if set(assets) - {'image'}:
            raise ValueError('Unexpected asset type')
        image_data = None
        if assets.get('image'):
            image_data = base64.b64decode(assets['image'], validate=True)
            if len(image_data) > 8 * 1024 * 1024:
                raise ValueError('Image exceeds 8 MB')
            with Image.open(BytesIO(image_data)) as image:
                if image.format not in ('JPEG', 'PNG', 'WEBP') or image.width * image.height > 25000000:
                    raise ValueError('Unsupported public image')
                image.load()
                image.thumbnail((2400, 2400))
                output = BytesIO()
                image.convert('RGB').save(output, 'JPEG', quality=90)
                image_data = output.getvalue()
        items.append((payload, image_data))
    return items


def import_content(s, document, apply=False):
    prepared = prepare(document)  # Validate every row and image BEFORE any write.
    actor = s.scalar(select(User).where(User.active.is_(True), User.role == 'admin').order_by(User.id))
    if actor is None:
        raise ValueError('An active UTBLib administrator is required for the import audit')
    existing, pending = 0, []
    for payload, image in prepared:
        row = s.scalar(select(SiteContent).where(SiteContent.kind == payload.kind, SiteContent.slug == payload.slug))
        if row is not None:
            if s.scalar(select(SiteAudit.id).where(SiteAudit.item_id == row.id, SiteAudit.action == ACTION).limit(1)) is None:
                raise ValueError(f'Existing UTBLib publication conflicts: {payload.kind}/{payload.slug}; nothing imported')
            existing += 1  # Keep all later staff edits, including draft/archive status.
        else:
            pending.append((payload, image))
    if apply:
        for payload, image in pending:
            row = SiteContent(kind=payload.kind, slug=payload.slug, status=payload.status,
                version=1, published_at=payload.published_at, data=payload.data.model_dump(mode='json'))
            s.add(row)
            s.flush()
            if image:
                s.add(SiteAsset(item_id=row.id, slot='image', name='image.jpg', mime='image/jpeg', size=len(image), content=image))
            audit(s, row, actor, ACTION)
        s.commit()
    return {'mode': 'applied' if apply else 'dry_run', 'new': len(pending), 'already_imported': existing}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    with Session() as s:
        print(json.dumps(import_content(s, json.load(sys.stdin), args.apply)))


if __name__ == '__main__':
    main()
