import { ApiError, agentPath, ownerHeaders } from "./base";

// 持仓 (personal finance assistant, Task 6): the owner's manual ledger.  Money comes as plain decimal strings.
export type PortfolioPlan = { plan_text:string; add_price:string|null; stop_price:string|null; target_price:string|null; updated_at?:string|null };
export type PortfolioPosition = { symbol:string; shares:string; cost:string; avg_cost:string|null; diluted_cost:string|null; realized_pnl:string;
  price:string|null; price_date:string|null; market_value:string|null; floating_pnl:string|null; floating_pnl_pct:string|null;
  today_pnl:string|null; today_pnl_reference_only:boolean; weight_pct:string|null; plan:PortfolioPlan };
export type PortfolioTransaction = { id:string; symbol:string; kind:string; quantity:string|null; price:string|null; fee:string|null; amount:string|null; ratio:string|null; occurred_on:string; note:string; created_at:string|null };
export type PortfolioSummary = { available_funds:string; positions_value:string; total_assets:string|null; total_assets_complete:boolean;
  floating_pnl:string; today_pnl:string; today_pnl_reference_only:boolean; realized_pnl:string; price_date:string|null; unpriced:string[]; warnings:string[];
  positions:PortfolioPosition[]; plans_without_position:string[]; transactions:PortfolioTransaction[] };
export type PortfolioWriteResult = { ok:boolean; status:string; id?:string; warnings?:string[]; warning_text?:string[]; available_funds?:string };
async function portfolioJson<T>(path:string,init:{method?:string;body?:unknown;signal?:AbortSignal},failure:string):Promise<T>{
  const response=await fetch(agentPath(`portfolio${path}`),{method:init.method??"GET",signal:init.signal,cache:"no-store",headers:ownerHeaders(init.body!==undefined),
    ...(init.body!==undefined?{body:JSON.stringify(init.body)}:{})});
  if(!response.ok){
    const detail=(await response.json().catch(()=>null) as {detail?:unknown}|null)?.detail;
    const reason=detail&&typeof detail==="object"&&typeof (detail as {reason?:unknown}).reason==="string"?(detail as {reason:string}).reason:"";
    throw new ApiError(response.status===403||response.status===401?"登录个人聊天后才能使用持仓。":reason||failure,response.status);
  }
  return await response.json() as T;
}
export async function getPortfolio(signal?:AbortSignal):Promise<PortfolioSummary>{ return await portfolioJson("",{signal},"持仓暂时无法读取。"); }
export async function addPortfolioTransaction(body:Record<string,string>):Promise<PortfolioWriteResult>{ return await portfolioJson("/transactions",{method:"POST",body},"记录失败，请检查后重试。"); }
export async function deletePortfolioTransaction(id:string):Promise<PortfolioWriteResult>{ return await portfolioJson(`/transactions/${encodeURIComponent(id)}`,{method:"DELETE"},"删除失败，请重试。"); }
export async function putPortfolioPlan(symbol:string,body:Record<string,string|null>):Promise<PortfolioWriteResult>{ return await portfolioJson(`/plans/${encodeURIComponent(symbol)}`,{method:"PUT",body},"保存失败，请重试。"); }
export async function putPortfolioCash(availableFunds:string):Promise<PortfolioWriteResult>{ return await portfolioJson("/cash",{method:"PUT",body:{available_funds:availableFunds}},"保存失败，请重试。"); }
