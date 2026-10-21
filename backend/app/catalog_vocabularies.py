"""Library-specific vocabulary supplied by the library, not MARC21 definitions."""
from copy import deepcopy
from sqlalchemy import select
from .db import User
from .vocabulary import add_entry

LITERATURE = [
('CD/ин.яз.','CD-Rom/иностр.яз.'),('CD/каз.яз.','CD-Rom/каз.яз.'),('CD/рус.яз.','CD-Rom/рус.яз.'),
('АДИС/ин.яз.','Автореф/Дисс иностр.яз.'),('АДИС/каз.яз.','Автореф/Дисс каз.яз.'),('АДИС/рус.яз.','Автореф/Дисс рус.яз.'),
('АУД/ин.яз.','Аудио иностр.яз.'),('АУД/каз.яз.','Аудио каз.яз.'),('АУД/рус.яз.','Аудио рус.яз.'),
('Бр./иностр.яз.','Брошюры на иностр.яз.'),('Бр./каз.яз.','Брошюры на каз.яз.'),('Бр./рус.яз.','Брошюры на рус.яз.'),
('ВИД/инос.яз.','Видео иностр.яз.'),('ВИД/каз.яз.','Видео каз.яз.'),('ВИД/рус.яз.','Видео рус.яз.'),
('ДКИ','Дискеты кассеты инос.яз.'),('ДКК','Дискеты кассеты каз.яз.'),('ДКР','Дискеты кассеты рус.яз.'),
('КНИ','Книги науч. инос. яз.'),('КНК','Книги науч. каз.яз.'),('КНР','Книги науч. рус.яз.'),
('КСИ','Книги справ.инос.яз.'),('КСК','Книги справ. каз.яз.'),('КСР','Книги справ. рус.яз.'),
('КУИ','Книги учеб. инос.яз.'),('КУК','Книги учеб. каз.яз.'),('КУМК','Книги учеб.мет. каз.яз'),('КУМР','Книги учеб.мет. рус.яз.'),('КУР','Книги учеб. рус.яз.'),
('КХИ','Книги худож. инос.яз.'),('КХК','Книги худож. каз.яз.'),('КХР','Книги худож. рус.яз.'),
('МИ/иностр.яз.','Метод. изд. на ин.яз'),('МИ/каз.яз.','Метод. изд. на каз.яз.'),('МИ/рус.яз.','Метод. изд. на рус.яз.')]

def configure(config):
    config=deepcopy(config)
    for field in config:
        code={'097':'b','952':'a'}.get(field['tag'])
        if code:
            field.setdefault('vocabularies',{}).setdefault(code,{'auto_add':False,'allow_edit':True})
    return config

def seed_literature(s,t):
    for value,label in LITERATURE:
        entry=add_entry(s,t.id,'952','a',value,label)
        if not entry.label: entry.label=label

def employee_entries(s):
    return [{'id':-u.id,'tag':'097','code':'b','value':u.display_name,'label':'','managed':True}
            for u in s.scalars(select(User).where(User.active.is_(True),User.deleted.is_(False)).order_by(User.display_name,User.id))]

def set_operator(marc,name):
    """Replace operator subfields, retaining all unrelated imported subfields."""
    found=False
    for field in marc['fields']:
        if field['tag']!='097': continue
        for sf in field.get('subfields',[]):
            if sf['code']=='b': sf['value']=name;found=True
    if not found:
        field=next((f for f in marc['fields'] if f['tag']=='097'),None)
        if field is None:
            field={'tag':'097','ind1':' ','ind2':' ','subfields':[]};marc['fields'].append(field)
        field.setdefault('subfields',[]).append({'code':'b','value':name})
