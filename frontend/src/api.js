const BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';
export function getToken(){return localStorage.getItem('cc_access')}
export async function api(path, options={}){
 const token=getToken(); const isForm=typeof FormData!=='undefined' && options.body instanceof FormData;
 const headers={...(isForm?{}:{'Content-Type':'application/json'}),...(options.headers||{})};
 if(token) headers.Authorization=`Bearer ${token}`;
 let response;
 try {
  response = await fetch(`${BASE}${path}`,{...options,headers});
 } catch (error) {
  throw new Error(`Cannot reach the API at ${BASE}. Check that Django is running and that backend CORS allows the frontend origin. Original error: ${error?.message || 'Network request failed'}`);
 }
 const text=await response.text(); let data={}; try{data=text?JSON.parse(text):{}}catch{data={detail:(text&&text.length<300&&!text.trim().startsWith('<'))?text:`The server returned an unexpected response (HTTP ${response.status}). Please try again; if it keeps happening, contact support.`}}
 if(!response.ok){if(response.status===401){localStorage.removeItem('cc_access');localStorage.removeItem('cc_refresh')} const detail=data.detail||data.message||(typeof data==='object'?Object.entries(data).map(([k,v])=>`${k}: ${Array.isArray(v)?v.join(', '):v}`).join(' · '):'');throw new Error(detail||`Request failed (${response.status})`)}
 return data;
}
export async function login(username,password){const data=await api('/auth/token/',{method:'POST',body:JSON.stringify({username,password})});localStorage.setItem('cc_access',data.access);localStorage.setItem('cc_refresh',data.refresh);return data}
export function logout(){localStorage.removeItem('cc_access');localStorage.removeItem('cc_refresh')}
