"""Printable codes contain only the reader barcode, never personal details."""
import xml.etree.ElementTree as ET
from barcode import Code128
from barcode.writer import SVGWriter
import qrcode
from qrcode.image.svg import SvgPathImage


def ticket_codes(barcode):
    raw=Code128(barcode,writer=SVGWriter()).render({
        'module_width':0.53,'module_height':15,'quiet_zone':6,'write_text':False,
    })
    # python-barcode uses physical mm coordinates. A matching pixel viewBox
    # makes the whole symbol (including quiet zones) scale inside the card.
    svg=ET.fromstring(raw)
    width=float(svg.attrib['width'].removesuffix('mm'))*96/25.4
    height=float(svg.attrib['height'].removesuffix('mm'))*96/25.4
    svg.set('viewBox',f'0 0 {width} {height}')
    svg.set('preserveAspectRatio','none')
    ET.register_namespace('','http://www.w3.org/2000/svg')
    qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,border=4,box_size=10)
    qr.add_data(barcode);qr.make(fit=True)
    return ET.tostring(svg,encoding='unicode'),qr.make_image(image_factory=SvgPathImage).to_string(encoding='unicode')
