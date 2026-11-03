"""Assisted draft output, not a complete GOST conformance validator.
Based on the user-supplied GOST R 7.0.100-2018, clauses cited in each issue.
No invented values, no transformation of author headings into responsibility.
"""
import re


def element(left, right, separator):
    """Add prescribed punctuation once when it is already present in MARC text."""
    left, right = left.strip(), right.strip()
    if not right:
        return left
    if not left:
        return right
    mark = separator.strip()
    # Only an exact boundary delimiter is redundant. Internal punctuation,
    # abbreviations, question marks, brackets and source spelling stay intact.
    if mark and left.endswith(mark):
        if mark != '.' or not left.endswith('...'):
            left = left[:-len(mark)].rstrip()
    if mark in (':', ';', '/', ',') and right.startswith(mark):
        right = right[len(mark):].lstrip()
    if mark == '.' and left.endswith(('.', '…')):
        return left + ' ' + right
    return left + separator + right


def identifier(prefix, value):
    return prefix + ' ' + re.sub(r'^' + prefix + r'\s*:?\s*', '', value.strip(), flags=re.I)


def describe(marc,kind='single'):
    fields=marc['fields']
    def fs(tag): return [f for f in fields if f['tag']==tag]
    def values(tag,code): return [s['value'].strip() for f in fs(tag) for s in f.get('subfields',[]) if s['code']==code and s['value'].strip()]
    def value(tag,code): return ' ; '.join(values(tag,code))
    def sub(f,code): return [s['value'].strip() for s in f.get('subfields',[]) if s['code']==code and s['value'].strip()]
    def area_join(parts):
        result=''
        for text in filter(None,parts):
            text=text.strip()
            if result: result+=(' — ' if result.endswith(('.', '…')) else '. — ')
            result+=text
        return result+('' if not result or result.endswith('.') else '.')
    issues=[]
    def issue(code,clause,message): issues.append({'code':code,'clause':clause,'message':message})
    title=value('245','a')
    for s in values('245','b'): title=element(title,s,' : ')
    for c in ('n','p'):
        for s in values('245',c): title=element(title,s,'. ')
    responsibility=value('245','c')
    if responsibility: title=element(title,responsibility,' / ')
    if not value('245','a'): issue('title','5.2.3','Не заполнено основное заглавие (245$a).')
    if not responsibility: issue('responsibility','5.2.6','Проверьте первые сведения об ответственности (245$c) по источнику. Поле «Автор» 100$a не заменяет эту строку.')
    edition=value('250','a')
    if value('250','b'): edition=element(edition,value('250','b'),' / ')
    publications=fs('260')
    if not any(sub(f,c) for f in publications for c in ('a','b','c')):
        publications=[f for f in fs('264') if f.get('ind2')=='1']
    pub_parts=[]
    for f in publications:
        part=''
        for s in f.get('subfields',[]):
            v=s['value'].strip();code=s['code']
            if not v or code not in ('a','b','c'): continue
            part=element(part,v,{'a':' ; ','b':' : ','c':', '}[code])
        if part: pub_parts.append(part)
    if kind=='single':
        for c,clause,label in [('a','5.5.3','место издания'),('b','5.5.4','издательство'),('c','5.5.5','дату издания')]:
            if not any(sub(f,c) for f in publications): issue('publication-'+c,clause,f'Уточните {label}. При отсутствии сведений примените соответствующее правило ГОСТ; программа не подставляет вымышленные значения.')
    physical=[]
    for f in fs('300'):
        part=''
        for c,sep in [('a',''),('b',' : '),('c',' ; '),('e',' + ')]:
            for v in sub(f,c): part=element(part,v,sep or ', ')
        if part: physical.append(part)
    if kind=='single' and not value('300','a'): issue('extent','5.6','Уточните объём и специфическое обозначение материала (300$a).')
    if value('300','a').isdigit(): issue('extent-unit','5.6','У объёма не указана единица. Например, «120 с.» — только если документ действительно имеет такую пагинацию.')
    series=[]
    for f in [f for f in fs('490') if sub(f,'a')] or fs('440'):
        a=' ; '.join(sub(f,'a'))
        for code in ('n','p'):
            for v in sub(f,code): a=element(a,v,'. ')
        if not a: continue
        for v in sub(f,'x'): a=element(a,identifier('ISSN',v),', ')
        for v in sub(f,'v'): a=element(a,v,' ; ')
        series.append('('+a+')')
    notes=values('500','a')
    identifiers=[]
    for tag,prefix in [('020','ISBN'),('022','ISSN')]:
        for f in fs(tag):
            for v in sub(f,'a'):
                item=identifier(prefix,v)
                for qualifier in sub(f,'q'):
                    item+=' '+(qualifier if qualifier.startswith('(') and qualifier.endswith(')') else '('+qualifier+')')
                identifiers.append(item)
    if not identifiers: issue('identifier','5.9.3','Если ресурсу присвоен международный стандартный номер, укажите его. Отсутствующий в ресурсе номер придумывать не нужно.')
    content=value('245','z')
    if not content:
        content=value('336','a')
        if value('337','a'): content=element(content,value('337','a'),' : ')
    if not content: issue('content-access','5.10','Уточните вид содержания и средство доступа. Коды 336/337 не расшифровываются автоматически без проверенного кодового справочника.')
    electronic=[]
    for f in fs('856'):
        urls=sub(f,'u');access=sub(f,'z')
        for u in urls: electronic.append('URL: '+u+(' ('+'; '.join(access)+')' if access else ''))
        if urls and not access: issue('electronic-access','5.8; 7.6.2','Уточните режим доступа и дату обращения для электронного ресурса (856$z).')
    if kind=='component':
        hosts=[]
        for f in fs('773'):
            t='; '.join(sub(f,'t'));d='; '.join(sub(f,'d'));g='; '.join(sub(f,'g'))
            if t: hosts.append(area_join([t,d,g]).removesuffix('.'))
        if not hosts: issue('host','7.1–7.4','Для статьи необходимы сведения об идентифицирующем ресурсе: журнале, сборнике или другом источнике (773$t).')
        if not value('773','g'): issue('host-location','7.4; 7.6','Проверьте год, том, выпуск и местоположение составной части (773$g); исключения зависят от вида ресурса.')
        leading=area_join([title,edition,content]).removesuffix('.')
        text=area_join([leading+(' // '+' ; '.join(hosts) if hosts else ''),*notes,*electronic])
    else:
        text=area_join([title,edition,*pub_parts,*physical,' '.join(series),*notes,*electronic,*identifiers,content])
    # The appendix examples prepend a heading to the description (4.1, appendix A).
    # Use an existing personal-name heading; never derive initials or substitute
    # it for the transcription of responsibility in 245$c.
    main_author=next((f for f in fs('100') if sub(f,'a')),None)
    heading=' '.join(s['value'].strip() for s in (main_author or {}).get('subfields',[])
                     if s['code'] in ('a','b','c','d','q') and s['value'].strip()).rstrip(' ,;/')
    record_text=(heading+('' if heading.endswith('.') else '.')+' '+text) if heading and text else text
    return {'standard':'ГОСТ Р 7.0.100–2018','kind':kind,'text':text,'heading':heading,'record_text':record_text,'issues':issues,'requires_review':True,
            'scope':'Черновик одноуровневого описания или описания составной части. Нужна сверка с ресурсом; многоуровневое описание и все специальные случаи не автоматизированы.'}
