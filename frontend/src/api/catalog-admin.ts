import { type CatalogModel, botJson } from "./bots";

export type CatalogEntryInput = { name?: string; display_name?: string; provider?: string; model?: string; base_url?: string | null; api_key?: string; key_env?: string; is_default?: boolean };
export async function addCatalogModel(value:CatalogEntryInput):Promise<CatalogModel>{ return (await botJson<{model:CatalogModel}>("model-catalog",{method:"POST",body:value},"保存失败。")).model; }
export async function updateCatalogModel(name:string,value:CatalogEntryInput):Promise<CatalogModel>{ return (await botJson<{model:CatalogModel}>(`model-catalog/${encodeURIComponent(name)}`,{method:"PATCH",body:value},"保存失败。")).model; }
export async function deleteCatalogModel(name:string):Promise<void>{ await botJson(`model-catalog/${encodeURIComponent(name)}`,{method:"DELETE"},"删除失败。"); }
/** 测试并保存 / 服务商可用模型 of the catalog form: the typed key, an environment variable, or (``name``, same
 *  provider and endpoint) the entry's stored key.  Nothing is saved; nothing returned carries a key. */
export type CatalogProbe = { name?: string; provider: string; model?: string; base_url?: string | null; api_key?: string; key_env?: string };
export async function testCatalogModel(value:CatalogProbe,signal?:AbortSignal):Promise<void>{ await botJson("model-catalog/test",{method:"POST",body:value,signal},"连接失败，请检查服务、Model ID 和 key。"); }
export async function discoverCatalogModels(value:CatalogProbe,signal?:AbortSignal):Promise<{status:string;ordering:string;models:Array<{id:string;name:string}>}>{ return await botJson("model-catalog/models",{method:"POST",body:value,signal},"暂时无法获取服务商模型列表。"); }
export type ModelRoles = { roles: Record<string, string | null> };
export async function getModelRoles(signal?:AbortSignal):Promise<ModelRoles>{ return await botJson("model-roles",{signal},"模型目录暂时无法读取。"); }
export async function setModelRole(role:string,model:string|null):Promise<void>{ await botJson(`model-roles/${encodeURIComponent(role)}`,{method:"PUT",body:{model}},"保存失败。"); }
export async function setDefaultCatalogModel(name:string):Promise<CatalogModel>{ return (await botJson<{model:CatalogModel}>("model-catalog/default",{method:"PUT",body:{name}},"保存失败。")).model; }
