export type Alphabet = 'cyrillic' | 'latin';
export type Separator = 'auto' | 'none' | 'space' | 'hyphen';
export type AuthorEntry = {term:string; review?:boolean; special?:boolean};
export type AuthorTable = {alphabet:Alphabet; letter:string; page:number; start:number; entries:AuthorEntry[]};
export type AuthorChoice = AuthorEntry & {alphabet:Alphabet; letter:string; number:number|null; page:number};
export type LookupResult = {alphabet:Alphabet|null; letter:string; choice:AuthorChoice|null; message:string; anchor:number|null};

// Sort by the alphabet, not by the browser's locale. I/J share a position in
// every syllable of the Latin table (source, pp. 15–16).
export function authorKey(value:string, alphabet:Alphabet):string {
  const lower=value.toLowerCase().normalize('NFC');
  return alphabet==='latin'
    ? lower.normalize('NFD').replace(/\p{M}/gu,'').replaceAll('j','i')
    : lower.replaceAll('ё','е').replaceAll('й','и');
}

export function tableRows(table:AuthorTable, initial=table.letter):AuthorChoice[] {
  return table.entries.map((e,i)=>({...e,alphabet:table.alphabet,letter:initial,number:table.start+i,page:table.page}));
}

export function formatAuthorMark(choice:AuthorChoice, separator:Separator='auto'):string {
  if(choice.number===null)return choice.letter;
  const sep=separator==='space'?' ':separator==='hyphen'?'-':separator==='none'?'':
    (choice.alphabet==='cyrillic'?'ЗОЧ':'OI').includes(choice.letter)?'-':'';
  return `${choice.letter}${sep}${choice.number}`;
}

export function lookupAuthorMark(tables:AuthorTable[], value:string):LookupResult {
  const text=value.normalize('NFC').trim().replace(/^[«»“”"'‘’(\s]+/u,'');
  const empty:LookupResult={alphabet:null,letter:'',choice:null,message:'Введите фамилию автора или первое слово заглавия.',anchor:null};
  if(!text)return empty;
  if(/^\d/u.test(text))return {...empty,message:'Запишите число в начале заглавия словами, затем найдите знак.'};
  const byCode=text.match(/^[\p{L}][ -]?(\d{2})$/u);
  if(/^[\p{L}][ -]?\d/u.test(text)&&!byCode)return {...empty,message:'В этих таблицах используются двузначные номера. Например, А17 или А-17.'};
  const token=text.match(/^\p{L}+/u)?.[0]||'';
  const initial=token[0]?.toUpperCase()||'';
  const alphabet:Alphabet|null=/^[А-ЯЁ]$/u.test(initial)?'cyrillic':/^[A-Z]$/u.test(authorKey(initial,'latin').toUpperCase())?'latin':null;
  if(!alphabet)return {...empty,message:'Для этой буквы в приложенных таблицах нет правила. Выберите знак вручную по принятой в библиотеке таблице.'};
  const letter=alphabet==='latin'?authorKey(initial,'latin').toUpperCase():initial;
  const result:LookupResult={...empty,alphabet,letter};
  if(byCode&&alphabet==='cyrillic'&&'ЁЙЪЫ'.includes(initial))return {...result,message:'Для этой буквы в таблице нет цифровых номеров.'};
  if(alphabet==='cyrillic'&&'ЁЙЪЫ'.includes(initial))return {...result,choice:{alphabet,letter:initial,number:null,term:initial,page:17},message:'По правилу 3 кириллической таблицы для этой начальной буквы используется знак без цифр.'};
  const key=authorKey(token,alphabet);
  if(!token||(alphabet==='cyrillic'?!/^[а-я]+$/u.test(key):!/^[a-z]+$/.test(key)))
    return {...result,message:'В слове есть буквы, не описанные в этих таблицах. Автоматическая транслитерация не применяется; уточните знак вручную.'};
  const table=tables.find(t=>t.alphabet===alphabet&&t.letter===letter);
  if(!table)return {...result,message:'Для этой начальной буквы таблицы нет. Знак можно ввести вручную.'};
  const rows=tableRows(table,alphabet==='latin'?initial.normalize('NFD').replace(/\p{M}/gu,''):initial);
  if(byCode){
    const row=rows.find(r=>r.number===Number(byCode[1]));
    return {...result,choice:row&&!row.review?row:null,anchor:row?.number??null,message:row?(row.review?'Строка исходного PDF неоднозначна. Сверьте её и выберите вручную.':'Найден знак в таблице.'):'Такого номера в этой таблице нет.'};
  }
  const full=authorKey(text,alphabet).replace(/[^\p{L}]/gu,'');
  const personal=rows.find(r=>r.special&&authorKey(r.term,alphabet).replace(/[^\p{L}]/gu,'')===full);
  if(personal)return {...result,choice:personal,anchor:personal.number,message:'Специальный знак из таблицы. Проверьте, что он относится к этому автору или организации.'};
  // The printed rules (Latin PDF, p. 16) explicitly resolve Lai/Laj to 17,
  // despite the duplicate 'Lai' typo in row L19 of the same PDF.
  if(alphabet==='latin'&&key==='lai'){
    const example=rows.find(r=>r.number===17)!;
    return {...result,choice:example,anchor:17,message:'Знак L17 подтверждён примером Lai/Laj в пояснениях к таблице (страница 16).'};
  }
  const ambiguous=rows.find(r=>r.review&&key.startsWith(authorKey(r.term,alphabet)));
  if(ambiguous)return {...result,anchor:ambiguous.number,message:'В исходном PDF это начало слова встречается в неоднозначной строке. Сверьте оригинал и выберите знак вручную.'};
  const good=rows.filter(r=>!r.review&&!r.special);
  // Each row is a lower alphabetical boundary. Longest-prefix matching is
  // incorrect: the source explicitly assigns Мосолов to М82, not М81.
  let candidate:AuthorChoice|null=null;
  for(const row of good){
    const boundary=table.letter==='I'&&row.number===10?'i':authorKey(row.term,alphabet);
    if(boundary<=key)candidate=row;
  }
  if(!candidate)return {...result,message:'Уточните начало слова или выберите строку таблицы вручную.'};
  const next=good.find(r=>r.number! > candidate!.number!);
  const between=rows.filter(r=>r.number! > candidate!.number!&&(!next||r.number! < next.number!));
  if(between.length){
    return {...result,anchor:candidate.number,message:between.some(r=>r.review)
      ?'В этом участке исходного PDF есть неоднозначные строки. Откройте оригинал и выберите знак вручную.'
      :'В этом участке таблицы есть специальный знак для конкретного автора или организации. Сверьте оригинал и выберите подходящую строку.'};
  }
  return {...result,choice:candidate,anchor:candidate.number,message:'Подобрано по алфавитному месту слова. Проверьте строку таблицы перед вставкой.'};
}

export function canInsertAuthorMark(value:string, current:string, settings?:{auto_add:boolean;allow_edit?:boolean}, entries:{value:string}[]=[]):boolean {
  return !settings||settings.auto_add||!!settings.allow_edit||value===current||entries.some(e=>e.value.normalize('NFC').trim()===value.normalize('NFC').trim());
}
