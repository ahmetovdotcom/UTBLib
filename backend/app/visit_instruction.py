"""The approved, one-page A4 reader instructions, with a service point's live QR."""
from io import BytesIO
from pathlib import Path
import re
from threading import Lock
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

ASSETS = Path(__file__).with_name('assets') / 'visit-instruction'
FONT = 'VisitNoto'
BOLD = 'VisitNoto-Bold'
FONT_LOCK = Lock()
NAVY, TEAL, INK, MUTED = '#16384F', '#087F80', '#233F50', '#526976'

COPY = {
    'ru': {
        'title': 'Отметка посещения Научной библиотеки по QR-коду',
        'library': 'НАУЧНАЯ БИБЛИОТЕКА',
        'university': 'Казахский университет технологии и бизнеса<br/>имени К. Кулажанова',
        'greeting': 'Уважаемый читатель,',
        'intro': 'просим отметить своё посещение<br/>в Научной библиотеке.',
        'scan': 'Отсканируйте QR-код',
        'scan_text': 'Откройте камеру телефона и наведите её на QR-код<br/>справа вверху. Нажмите на появившуюся ссылку.',
        'login': 'Войдите через Платонус',
        'login_text': 'Нажмите <b>«Войти с логином Platonus»</b>.<br/>Введите свой <b>логин и пароль от Платонуса</b>.<br/>После входа нажмите <b>«Отметить посещение»</b>.',
        'signed_in': 'Уже вошли? Сразу нажмите «Отметить посещение».',
        'forgot_heading': 'ЕСЛИ НЕ ЗНАЕТЕ ИЛИ НЕ ПОМНИТЕ ДАННЫЕ',
        'forgot': 'Нажмите<br/><b>«Не помню логин или пароль»</b>.',
        'manual': 'Укажите <b>ФИО полностью, группу и курс</b>.<br/>Нажмите <b>«Отметить посещение»</b>.',
        'confirmation': 'Дождитесь подтверждения',
        'success': '<b>«Посещение засчитано»</b><br/>Ваша отметка сохранена.',
        'help': 'Нужна помощь? Обратитесь к библиотекарю.',
    },
    'kk': {
        'title': 'Ғылыми кітапханаға келуді QR-код арқылы тіркеу',
        'library': 'ҒЫЛЫМИ КІТАПХАНА',
        'university': 'Қ. Құлажанов атындағы<br/>Қазақ технология және бизнес университеті',
        'greeting': 'Құрметті оқырман,',
        'intro': 'Ғылыми кітапханаға келгеніңізді<br/>тіркеуіңізді сұраймыз.',
        'scan': 'QR-кодты сканерлеңіз',
        'scan_text': 'Телефон камерасын жоғарғы оң жақтағы QR-кодқа<br/>бағыттап, пайда болған сілтемені ашыңыз.',
        'login': 'Платонус арқылы кіріңіз',
        'login_text': '<b>«Platonus логинімен кіру»</b> түймесін басыңыз.<br/><b>Платонус логині мен құпиясөзін</b> енгізіңіз.<br/>Кіргеннен кейін <b>«Келуді тіркеу»</b> түймесін басыңыз.',
        'signed_in': 'Кіріп қойған болсаңыз, бірден «Келуді тіркеу» түймесін басыңыз.',
        'forgot_heading': 'ЛОГИНДІ НЕМЕСЕ ҚҰПИЯСӨЗДІ БІЛМЕСЕҢІЗ',
        'forgot': '<b>«Логинімді немесе құпиясөзімді ұмыттым»</b><br/>түймесін басыңыз.',
        'manual': '<b>Аты-жөніңізді толық, тобыңызды және курсыңызды</b> көрсетіңіз.<br/><b>«Келуді тіркеу»</b> түймесін басыңыз.',
        'confirmation': 'Растауды күтіңіз',
        'success': '<b>«Келу тіркелді»</b><br/>Келуіңіз сәтті тіркелді.',
        'help': 'Көмек керек пе? Кітапханашыға хабарласыңыз.',
    },
}


def branch_label(name, language):
    """Expand the short labels used by the library; preserve all other names."""
    value = ' '.join(name.split())
    match = re.fullmatch(r'(?:аб|абонемент)\s*[№#]?\s*(\d+)', value, re.IGNORECASE)
    if match:
        return f'№ {match[1]} абонемент' if language == 'kk' else f'Абонемент № {match[1]}'
    if value.casefold() in ('чз', 'читальный зал', 'оқу залы'):
        return 'Оқу залы' if language == 'kk' else 'Читальный зал'
    return value


def register_fonts():
    with FONT_LOCK:
        if FONT not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(FONT, str(ASSETS / 'NotoSans-Regular.ttf')))
            pdfmetrics.registerFont(TTFont(BOLD, str(ASSETS / 'NotoSans-Bold.ttf')))
            pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=BOLD)


def render_instruction(name, link, language='ru'):
    """Return a PDF without fetching URLs or changing a point, token or visit."""
    copy = COPY[language]
    register_fonts()
    width, height = A4
    output = BytesIO()
    c = canvas.Canvas(output, pagesize=A4, pageCompression=1)
    label = branch_label(name, language)
    c.setTitle(copy['title'] + ' - ' + label)
    c.setAuthor('Научная библиотека КазУТБ')

    def rect(x, y, w, h, fill, radius=0, stroke=None):
        c.setFillColor(HexColor(fill))
        if stroke:
            c.setStrokeColor(HexColor(stroke))
            c.setLineWidth(.6)
        if radius:
            c.roundRect(x, height-y-h, w, h, radius, fill=1, stroke=bool(stroke))
        else:
            c.rect(x, height-y-h, w, h, fill=1, stroke=bool(stroke))

    def txt(text, x, y, size=12, font=FONT, color=INK):
        c.setFillColor(HexColor(color))
        c.setFont(font, size)
        c.drawString(x, height-y-size*.8, text)

    def para(text, x, y, w, size=12.4, leading=19, color=INK, font=FONT, max_h=None, align=0):
        style = ParagraphStyle('text', fontName=font, fontSize=size, leading=leading,
                               textColor=HexColor(color), alignment=align, spaceAfter=0)
        p = Paragraph(text, style)
        _, h = p.wrap(w, height)
        if max_h and h > max_h:
            raise ValueError('Instruction text exceeds its A4 layout')
        p.drawOn(c, x, height-y-h)

    def number(n, x, y):
        c.setFillColor(HexColor('#E3F1EE'))
        c.circle(x+17, height-y-17, 17, fill=1, stroke=0)
        c.setFont(BOLD, 15)
        c.setFillColor(HexColor(TEAL))
        c.drawCentredString(x+17, height-y-22, str(n)+')')

    rect(0, 0, width, height, '#F2F6F4')
    c.saveState()
    c.setStrokeColor(HexColor('#DFEAE5'))
    c.setLineWidth(.8)
    for radius in (60, 85, 110, 135, 160):
        c.circle(width+20, height-85, radius, fill=0, stroke=1)
    for radius in (80, 106, 132):
        c.circle(-50, 40, radius, fill=0, stroke=1)
    c.restoreState()

    rect(36, 32, 42, 42, '#FFFFFF', 21)
    c.drawImage(str(ASSETS / 'logo.png'), 37, height-73, 40, 40, mask='auto')
    txt(copy['library'], 89, 33, 10.5, BOLD, NAVY)
    para(copy['university'], 89, 51, 307, 8.6, 13, MUTED, max_h=30)

    rect(414, 24, 145, 175, '#FFFFFF', 11, '#DCE6E2')
    qr = QrCodeWidget(link, barLevel='M', barBorder=4)
    x0, y0, x1, y1 = qr.getBounds()
    side = 129
    drawing = Drawing(side, side, transform=[side/(x1-x0), 0, 0, side/(y1-y0), -x0*side/(x1-x0), -y0*side/(y1-y0)])
    drawing.add(qr)
    renderPDF.draw(drawing, c, 422, height-32-side)
    # The QR caption is compact; retain the complete service point in PDF metadata.
    caption = label
    caption_size = 9.5 if len(label)>22 else 10.6
    style = ParagraphStyle('caption', fontName=BOLD, fontSize=caption_size, leading=11)
    while Paragraph(escape(caption), style).wrap(131, height)[1] > 33:
        caption = caption.rstrip('…')[:-1].rstrip()+'…'
    para(escape(caption), 421, 166, 131, caption_size, 11, NAVY, BOLD, max_h=33, align=1)
    c.linkURL(link, (414, height-199, 559, height-24), relative=0, thickness=0)

    para(copy['greeting'], 36, 119, 370, 24, 31, NAVY, BOLD, max_h=40)
    para(copy['intro'], 38, 159, 368, 16, 23, NAVY, max_h=50)

    rect(36, 238, width-72, 99, '#FFFFFF', 13, '#DCE6E2')
    number(1, 51, 253)
    txt(copy['scan'], 98, 253, 17, BOLD, NAVY)
    para(copy['scan_text'], 98, 280, 440, 12.1, 18, max_h=40)

    rect(36, 352, width-72, 171, '#FFFFFF', 13, '#C9DED8')
    rect(36, 366, 4, 143, TEAL, 2)
    number(2, 51, 369)
    txt(copy['login'], 98, 369, 17, BOLD, NAVY)
    para(copy['login_text'], 98, 401, 435, 12.5, 22, max_h=70)
    rect(51, 481, width-102, 27, '#EDF5F2', 6)
    txt(copy['signed_in'], 65, 489, 10.5, FONT, TEAL)

    rect(36, 539, width-72, 140, '#E8F0F4', 13)
    txt(copy['forgot_heading'], 53, 554, 10.5, BOLD, MUTED)
    para(copy['forgot'], 53, 577, 480, 14.3, 20, NAVY, max_h=42)
    para(copy['manual'], 53, 628, 480, 12.5, 19, max_h=40)

    rect(36, 695, width-72, 78, '#DDEFE8', 13)
    number(3, 51, 711)
    txt(copy['confirmation'], 98, 710, 16.5, BOLD, NAVY)
    para(copy['success'], 98, 737, 440, 12.1, 16.5, max_h=34)

    txt(copy['help'], 38, 794, 10.8, FONT, NAVY)
    url = urlsplit(link)
    txt(url.netloc, 38, 813, 9.5, BOLD, TEAL)
    c.linkURL(f'{url.scheme}://{url.netloc}/', (38, height-825, 250, height-810), relative=0, thickness=0)
    c.showPage()
    c.save()
    return output.getvalue()
