import {toRaw} from 'vue';
export type SF={code:string,value:string};
export type MF={tag:string,value?:string,ind1?:string,ind2?:string,subfields?:SF[]};
export type Spec={local?:boolean,tag:string,label:string,repeatable:boolean,obsolete:boolean,documentation:string,indicators:{position:number,label:string,values:{code:string,label:string}[]}[],subfields:{code:string,label:string,repeatable:boolean}[]};
export type Config={vocabularies?:Record<string,{auto_add:boolean,allow_edit?:boolean}>,local?:boolean,tag:string,label:string,required:boolean,subfields:string[]};
export type DT={id:number,name:string,config:Config[]};
export type RecordData={id?:number,type_id:number,version?:number,marc:{leader:string,fields:MF[]}};
// UI-only empty rows never overwrite a stored MARC field or enter the saved record.
const generated=new WeakSet<object>(), generatedSubfields=new WeakSet<object>();
export const common:Record<string,string[]>={
 '020':['a','q','c'],'022':['a'],'024':['a','2'],'041':['a'],'080':['a'], '084':['a','2'],
 '100':['a','d','e'],'110':['a','b'],'111':['a','d','c'],'245':['a','b','c','n','p'],
 '246':['a','b'],'250':['a'],'260':['a','b','c'],'264':['a','b','c'],'300':['a','b','c','e'],
 '490':['a','v'],'500':['a'],'504':['a'],'520':['a'],'650':['a','x','y','z'],'653':['a'],
 '700':['a','d','e'],'710':['a','b'],'773':['t','g','x','w'],'856':['u','y','z']
};
export function codesFor(spec:Spec,cfg:Config){return cfg.subfields.length?cfg.subfields:(common[spec.tag]||spec.subfields.filter(s=>!/[Oo][Bb][Ss][Oo][Ll][Ee][Tt][Ee]/.test(s.label)).map(s=>s.code));}
export function makeSubfield(code:string,value=''){const s={code,value};generatedSubfields.add(s);return s;}
export function makeField(spec:Spec,cfg:Config):MF{
 const f:MF=Number(spec.tag)<10?{tag:spec.tag,value:''}:{tag:spec.tag,ind1:spec.indicators.find(i=>i.position===1)?.values[0]?.code||' ',ind2:spec.indicators.find(i=>i.position===2)?.values[0]?.code||' ',subfields:codesFor(spec,cfg).map(code=>makeSubfield(code,spec.tag==='084'&&code==='2'?'rubbk':''))};
 if(['100','700'].includes(f.tag))f.ind1='1';if(f.tag==='245'){f.ind1='1';f.ind2='0';}if(f.tag==='653')f.ind1='1';
 if(spec.local){const indicators:Record<string,[string,string]>={'041':['0',' '],'246':['0','1'],'440':[' ','0'],'520':['0',' '],'541':['1',' '],'650':['1','4'],'856':['0',' ']};if(indicators[f.tag])[f.ind1,f.ind2]=indicators[f.tag];} if(f.tag==='264')f.ind2='1';if(f.tag==='650')f.ind2='4';generated.add(f);return f;
}
export function prepareRecord(record:RecordData,type:DT|undefined,specs:Record<string,Spec>){
 for(const cfg of type?.config||[]){
  if(cfg.tag==='000'||!specs[cfg.tag])continue;
  if(!record.marc.fields.some(f=>f.tag===cfg.tag))record.marc.fields.push(makeField(specs[cfg.tag],cfg));
  else for(const f of record.marc.fields.filter(f=>f.tag===cfg.tag)){
   if(Number(f.tag)<10)continue;
   f.subfields??=[];
   const wanted=codesFor(specs[cfg.tag],cfg);for(const code of new Set(wanted)){const count=wanted.filter(c=>c===code).length;while(f.subfields.filter(s=>s.code===code).length<count)f.subfields.push(makeSubfield(code));}
  }
 }
}
export function cleanRecord(record:RecordData):RecordData{
 return {...record,marc:{leader:record.marc.leader,fields:record.marc.fields.filter(f=>{
  if(!generated.has(toRaw(f)))return true;
  return f.value?.trim()||(f.subfields||[]).some(s=>s.value.trim()&&!(f.tag==='084'&&s.code==='2'&&s.value==='rubbk'));
 }).map(f=>f.subfields?{...f,subfields:f.subfields.filter(s=>!generatedSubfields.has(toRaw(s))||s.value!=='').map(s=>({...s}))}:{...f})}};
}
export function cloneField(f:MF):MF{const copy:MF=JSON.parse(JSON.stringify(f));generated.add(copy);for(const s of copy.subfields||[])generatedSubfields.add(s);return copy;}
export function move<T>(list:T[],i:number,d:number){if(i+d>=0&&i+d<list.length)[list[i],list[i+d]]=[list[i+d],list[i]];}
