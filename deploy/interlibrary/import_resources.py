"""Publish the interlibrary cooperation cards under an existing staff account."""
import argparse
import json
from io import BytesIO
from pathlib import Path

from PIL import Image
from sqlalchemy import select

from app.db import Session, User, utcnow
from app.security import has
from app.site_content import ContentInput, SiteAsset, SiteContent, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('username', help='Active UTBLib account with site.manage')
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    rows = json.loads((directory / 'items.json').read_text(encoding='utf-8'))
    created = []
    skipped = []

    with Session.begin() as session:
        actor = session.scalar(select(User).where(User.username == args.username))
        if actor is None or actor.deleted or not actor.active or not has(actor, 'site.manage'):
            parser.error('Нужен действующий пользователь UTBLib с правом site.manage.')

        for row in rows:
            body = ContentInput.model_validate({
                key: row[key] for key in ('kind', 'slug', 'status', 'data')
            })
            existing = session.scalar(select(SiteContent.id).where(
                SiteContent.kind == body.kind, SiteContent.slug == body.slug,
            ))
            if existing is not None:
                skipped.append(body.slug)
                continue

            image_path = directory / row['image']
            logo = image_path.read_bytes()
            with Image.open(BytesIO(logo)) as image:
                if image.format != 'PNG':
                    raise ValueError(f'{image_path.name}: expected a PNG logo')
                image.verify()

            item = SiteContent(
                kind=body.kind, slug=body.slug, status=body.status,
                published_at=utcnow(), data=body.data.model_dump(mode='json'),
            )
            session.add(item)
            session.flush()
            session.add(SiteAsset(
                item_id=item.id, slot='image', name=image_path.name,
                mime='image/png', size=len(logo), content=logo,
            ))
            audit(session, item, actor, 'create')
            created.append(body.slug)

    print(json.dumps({'created': created, 'skipped': skipped}, ensure_ascii=False))


if __name__ == '__main__':
    main()
