"""Rebuild a versioned dictionary from the official LOC field list, never guesses tags."""
import argparse, hashlib, json, re, urllib.request
from pathlib import Path
from bs4 import BeautifulSoup
URL = 'https://www.loc.gov/marc/bibliographic/ecbdlist.html'
def parse(raw):
    soup = BeautifulSoup(raw, 'html.parser')
    content = '\n'.join(p.get_text() for p in soup.find_all('pre'))
    starts = list(re.finditer(r'^(\d{3}) - (.+)$', content, re.M))
    fields = []
    for i, m in enumerate(starts):
        block = content[m.start():starts[i+1].start() if i+1<len(starts) else len(content)]
        title = m[2].strip()
        indicators, subfields = [], []
        indicator = None
        in_subfields = False
        for line in block.splitlines()[1:]:
            s=line.strip()
            if s == 'Subfield Codes': in_subfields=True; indicator=None
            h=re.match(r'(First|Second) - (.+)',s)
            if h and not in_subfields:
                indicator={'position':1 if h[1]=='First' else 2,'label':h[2],'values':[]}
                indicators.append(indicator); continue
            sub=re.match(r'\$(\S) - (.+)',s)
            if sub:
                subfields.append({'code':sub[1],'label':sub[2], 'repeatable': '(R)' in sub[2], 'obsolete':'[OBSOLETE' in sub[2]})
            elif indicator:
                v=re.match(r'([#\w|](?:-[\w])?) - (.+)',s)
                if v:
                    codes=list(str(n) for n in range(int(v[1][0]),int(v[1][2])+1)) if re.fullmatch(r'\d-\d',v[1]) else [v[1]]
                    indicator['values'].extend({'code':' ' if c=='#' else c,'label':v[2]} for c in codes)
        fields.append({'tag':m[1],'label':title,'repeatable':'(R)' in title,'obsolete':'[OBSOLETE' in title,
                       'indicators':indicators,'subfields':subfields,'documentation':block.strip()})
    if len(fields)<200 or not any(f['tag']=='245' and len(f['subfields'])>10 for f in fields):
        raise ValueError('Official page format changed: refusing incomplete import')
    merged={}
    for field in fields:
        if field['tag'] not in merged: merged[field['tag']]=field; continue
        old=merged[field['tag']]
        if not (old['obsolete'] and field['obsolete']): raise ValueError('Unexpected duplicate active tag')
        old['documentation']+='\n\n'+field['documentation']
        old.setdefault('historical_variants',[]).append(field)
        old['label']+=' / '+field['label']
        old['subfields'].extend(s for s in field['subfields'] if s['code'] not in {x['code'] for x in old['subfields']})
    fields=list(merged.values())
    return {'source':URL,'edition':soup.select_one('.edition').get_text(' ',strip=True),
            'sha256':hashlib.sha256(raw).hexdigest(),'leader_and_directory':content[:starts[0].start()], 'fields':fields}
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--source',type=Path); p.add_argument('--output',type=Path,default=Path('/data/marc21.json')); a=p.parse_args()
    raw=a.source.read_bytes() if a.source else urllib.request.urlopen(URL,timeout=60).read()
    result=parse(raw); a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    a.output.with_suffix('.source.html').write_bytes(raw)
    print(f"Imported {len(result['fields'])} fields; SHA256 {result['sha256']}")
