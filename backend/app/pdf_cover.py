"""Isolated PDFium worker: no JavaScript/forms, bounded memory/time and image size."""
import json
import resource
import sys
from pathlib import Path

resource.setrlimit(resource.RLIMIT_CPU,(20,20))
if sys.platform=='linux': resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
resource.setrlimit(resource.RLIMIT_FSIZE,(4*1024*1024,4*1024*1024))
import pypdfium2 as pdfium

path=Path(sys.argv[1])
with pdfium.PdfDocument(path/'book.pdf') as pdf:
    count=len(pdf)
    if not 0<count<=20000: raise ValueError('Invalid page count')
    page=pdf[0]
    try:
        width,height=page.get_size()
        if not 1<=min(width,height)<=max(width,height)<=50000: raise ValueError('Invalid page dimensions')
        bitmap=page.render(scale=min(2,1400/max(width,height)),may_draw_forms=False)
        try:
            with bitmap.to_pil() as image:
                image.convert('RGB').save(path/'cover.jpg',format='JPEG',quality=85)
        finally: bitmap.close()
    finally: page.close()
    print(json.dumps({'pages':count}))
