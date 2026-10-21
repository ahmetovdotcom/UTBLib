"""Read-only ISBN lookup. Results are proposals, never saved automatically."""
import asyncio
import os
import re
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query


def normalize(value):
    value=re.sub(r'[\s-]', '', value).upper()
    if re.fullmatch(r'\d{9}[\dX]',value):
        if sum((10-i)*(10 if c=='X' else int(c)) for i,c in enumerate(value))%11==0:
            stem='978'+value[:9]
            return stem+str((-sum(int(c)*(1 if i%2==0 else 3) for i,c in enumerate(stem)))%10)
    if re.fullmatch(r'97[89]\d{10}',value) and sum(int(c)*(1 if i%2==0 else 3) for i,c in enumerate(value))%10==0:
        return value
    raise ValueError('Введите корректный ISBN-10 или ISBN-13. Проверьте контрольную цифру.')


def candidate(source,url,isbn,title,authors,publisher,date,place='',pages='',subtitle=''):
    rows=[]
    def add(tag,code,label,value):
        if value is not None and str(value).strip():
            rows.append(dict(tag=tag,code=code,label=label,value=str(value).strip()[:4000]))
    add('020','a','ISBN',isbn)
    # Provider names are unstructured: do not guess surname inversion or responsibility statement.
    for i,author in enumerate(authors):
        add('100' if i==0 else '700','a','Автор' if i==0 else 'Другие авторы',author)
    add('245','a','Заглавие',title)
    add('245','b','Продолжение заглавия',subtitle)
    add('260','a','Место издания',place)
    add('260','b','Издательство',publisher)
    add('260','c','Дата издания',date)
    add('300','a','Объём',pages)
    return dict(source=source,url=url,title=title,rows=rows)


async def lookup(isbn):
    async with httpx.AsyncClient(timeout=12,headers={'User-Agent':'LibraryCatalog/0.1 (ISBN lookup)'}) as client:
        async def ol():
            r=await client.get('https://openlibrary.org/api/books',params={'bibkeys':'ISBN:'+isbn,'format':'json','jscmd':'data'})
            r.raise_for_status()
            v=r.json().get('ISBN:'+isbn)
            if not v or not v.get('title'): return []
            names=lambda key: '; '.join(x['name'] for x in v.get(key,[]) if x.get('name'))
            return [candidate('Open Library','https://openlibrary.org/isbn/'+isbn,isbn,v['title'],[x['name'] for x in v.get('authors',[]) if x.get('name')],names('publishers'),v.get('publish_date',''),names('publish_places'),v.get('number_of_pages',''),v.get('subtitle',''))]
        async def google():
            params={'q':'isbn:'+isbn,'maxResults':10}
            if os.getenv('GOOGLE_BOOKS_API_KEY'): params['key']=os.environ['GOOGLE_BOOKS_API_KEY']
            r=await client.get('https://www.googleapis.com/books/v1/volumes',params=params)
            r.raise_for_status()
            result=[]
            for item in r.json().get('items',[]):
                v=item.get('volumeInfo',{}); identifiers=[]
                for ident in v.get('industryIdentifiers',[]):
                    try: identifiers.append(normalize(ident.get('identifier','')))
                    except ValueError: pass
                if isbn not in identifiers or not v.get('title'): continue
                from urllib.parse import quote
                result.append(candidate('Google Books','https://books.google.com/books?id='+quote(item['id'],safe=''),isbn,v['title'],v.get('authors',[]),v.get('publisher',''),v.get('publishedDate',''),pages=v.get('pageCount',''),subtitle=v.get('subtitle','')))
            return result
        responses=await asyncio.gather(ol(),google(),return_exceptions=True)
    items=[];warnings=[]
    for name,response in zip(('Open Library','Google Books'),responses):
        if isinstance(response,BaseException): warnings.append(name+': источник временно недоступен или ограничил запросы. Попробуйте позже.')
        else: items.extend(response)
    return {'isbn':isbn,'items':items,'warnings':warnings}


def router(auth):
    api=APIRouter(dependencies=[Depends(auth)])
    @api.get('/api/isbn-lookup')
    async def search(isbn:str=Query(min_length=1,max_length=40)):
        try: canonical=normalize(isbn)
        except ValueError as e: raise HTTPException(422,str(e))
        return await lookup(canonical)
    return api
