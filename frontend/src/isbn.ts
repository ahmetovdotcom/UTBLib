import type {MF} from './catalog';
export type IsbnRow={tag:string,code:string,label:string,value:string};
export function targets(rows:IsbnRow[],fields:MF[]){
 const counts:Record<string,number>={};
 return rows.map(row=>{const key=row.tag+'$'+row.code;const index=counts[key]||0;counts[key]=index+1;
 const field=fields.filter(f=>f.tag===row.tag)[index];
 return {row,index,field,existing:field?.subfields?.find(s=>s.code===row.code)?.value||''};});
}
export function insertIsbn(rows:IsbnRow[],fields:MF[],selected:boolean[],create:(tag:string)=>MF){
 for(const [i,target] of targets(rows,fields).entries()){
  if(!selected[i])continue;
  let f=fields.filter(f=>f.tag===target.row.tag)[target.index];
  if(!f){f=create(target.row.tag);fields.push(f);}
  f.subfields??=[];
  const s=f.subfields.find(s=>s.code===target.row.code);
  if(s)s.value=target.row.value;else f.subfields.push({code:target.row.code,value:target.row.value});
 }
}
