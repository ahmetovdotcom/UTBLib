// Pending writes belong to the authenticated user, never another user's session.
let scope:number|null=null;
export function setUserScope(id:number|null){scope=id;}
export const authStorage={
 getItem(key:string){return scope===null?null:sessionStorage.getItem(`user:${scope}:${key}`);},
 setItem(key:string,value:string){if(scope!==null)sessionStorage.setItem(`user:${scope}:${key}`,value);},
 removeItem(key:string){if(scope!==null)sessionStorage.removeItem(`user:${scope}:${key}`);}
};
