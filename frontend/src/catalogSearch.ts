export type SearchCondition={field:string;operator:'contains'|'equals'|'starts_with';value:string};
export type CatalogSearch={q:string;type_id:number;udc:string;conditions:SearchCondition[];match:'all'|'any'};
export const emptyCatalogSearch=():CatalogSearch=>({q:'',type_id:0,udc:'',conditions:[],match:'all'});
export function normalizeCatalogSearch(search:CatalogSearch):CatalogSearch{
 if(search.conditions.length>8)throw new Error('Можно добавить до 8 условий поиска.');
 const conditions=search.conditions.map(c=>{
  if(!/^\d{3}(\$[a-z0-9])?$/.test(c.field))throw new Error('Выберите поле для каждого условия.');
  if(!c.value.trim())throw new Error('Введите значение для каждого условия или удалите пустое условие.');
  if(c.value.length>20000)throw new Error('Значение условия должно быть не длиннее 20 000 символов.');
  return {...c,value:c.value.trim()};
 });
 return {...search,q:search.q.trim(),udc:search.udc.trim(),conditions};
}
export function catalogSearchPath(search:CatalogSearch,offset=0){
 const params=new URLSearchParams({q:search.q,udc:search.udc,offset:String(offset)});
 if(search.type_id)params.set('type_id',String(search.type_id));
 if(search.conditions.length){params.set('conditions',JSON.stringify(search.conditions));params.set('match',search.match);}
 return '/records?'+params.toString();
}

export async function fetchCatalogRecords(api:(path:string,method?:string,body?:unknown)=>Promise<any>,search:CatalogSearch,offset=0){
 if(search.conditions.length)return api('/catalog-search/records','POST',{...search,type_id:search.type_id||null,offset});
 return api(catalogSearchPath(search,offset));
}
