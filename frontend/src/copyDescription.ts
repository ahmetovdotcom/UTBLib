import type {RecordData} from './catalog';
export type DescriptionSource={recordId?:number;marc?:RecordData['marc'];kind?:'single'|'component'};
export type DescriptionApi=(path:string,method?:string,body?:unknown)=>Promise<any>;
export async function descriptionForCopy(api:DescriptionApi,source:DescriptionSource):Promise<string>{
 // Snapshot the current form at the click. Copying never saves the record.
 const request=source.marc
  ? api('/gost/preview','POST',{marc:JSON.parse(JSON.stringify(source.marc)),kind:source.kind||'single'})
  : source.recordId ? api(`/records/${source.recordId}/description`) : Promise.reject(Error('Откройте карточку или заполните сведения о книге.'));
 const result=await request;
 const text=String(result.record_text??result.text??'').trim();
 if(!text)throw Error('В записи ещё нет данных для библиографического описания.');
 return text;
}
