"use strict";
const $ = id => document.getElementById(id);
const sessionToken = document.querySelector('meta[name="cra-session"]').content;
let configHash = null, busy = false, calls = 0, uncertain = false;
const fields = ["vendor","baseUrl","model","maxTokens","inputPrice","outputPrice","budget"];
function message(id, text, kind="") { $(id).textContent=text; $(id).className="status "+kind; }
function config() { return {base_url:$("baseUrl").value.trim(),model:$("model").value.trim(),max_tokens:Number($("maxTokens").value),input_price:Number($("inputPrice").value),output_price:Number($("outputPrice").value),budget:Number($("budget").value),deepseek_pricing:$("vendor").value==="deepseek"}; }
function buttons() {
  const ready=Boolean(configHash && $("apiKey").value.trim()) && !busy && !uncertain;
  $("btnTest").disabled=!ready || calls!==0;
  $("btnRun").disabled=!ready || calls!==1;
  $("btnModels").disabled=!ready;
  $("btnSave").disabled=busy;
  fields.forEach(id=>$(id).disabled=busy);
}
function status(value) {
  calls=value.calls; uncertain=value.uncertain;
  $("spent").textContent="$"+value.spent_usd.toFixed(6);
  $("remaining").textContent="$"+value.remaining_usd.toFixed(6);
  $("calls").textContent=calls+" / "+value.max_calls;
  $("billingState").textContent=uncertain?"待核对 · 已停止":"可核对";
  $("usage").textContent=value.ledger.length?JSON.stringify(value.ledger,null,2):"暂无记录。";
  buttons();
}
async function api(path, data) {
  const controller=new AbortController(); const timer=setTimeout(()=>controller.abort(),70000);
  try {
    const result=await fetch("/api/"+path,{method:"POST",headers:{"Content-Type":"application/json","X-CRA-Session":sessionToken},body:JSON.stringify(data),signal:controller.signal,cache:"no-store"});
    const value=await result.json(); if(!result.ok)throw new Error(value.error||"本机请求失败"); return value;
  } finally {clearTimeout(timer);}
}
async function refresh() {try{status(await api("status",{}));}catch{message("status","本机服务暂不可用，请重新打开应用。","err");}}
async function saveConfig() {
  if(!$("apiKey").value.trim()){message("status","请先填写 API Key。","err");return;}
  busy=true; buttons();
  try {
    const value=await api("configure",config()); configHash=value.config_hash; status(value);
    $("badge").textContent="配置已保存"; $("badge").className="badge on";
    message("status","配置已保存在当前本机进程；密钥留在页面内存。","ok");
  } catch(error){message("status",error.message,"err");}
  finally{busy=false;buttons();}
}
async function request(action) {
  if(busy || !configHash)return;
  const stateId=action==="run"?"runStatus":"status";
  busy=true;buttons();message(stateId,action==="models"?"正在读取模型列表…":"正在调用模型，请稍候…");
  try {
    const value=await api(action,{api_key:$("apiKey").value.trim(),config_hash:configHash,prompt:action==="run"?$("prompt").value:""});
    if(action==="models") {
      $("modelList").replaceChildren();$("chips").replaceChildren();
      value.models.forEach(id=>{
        const option=document.createElement("option");option.value=id;$("modelList").append(option);
        const button=document.createElement("button");button.className="chip";button.textContent=id;button.addEventListener("click",()=>{$("model").value=id;invalidate();});$("chips").append(button);
      });
      message(stateId,"读取到 "+value.models.length+" 个模型。选择后请重新保存配置。","ok");
    } else {
      $("out").textContent=value.content || "（空响应）";
      $("meta").textContent=value.observed_model+" · "+value.elapsed_ms+" ms";
      status(value.status);message(stateId,"调用完成；费用与 token 用量已记录。","ok");
      if(action==="test")message("runStatus","连接测试完成，可以执行一次小任务。");
    }
  } catch(error) {message(stateId,error.name==="AbortError"?"请求超时，请核对费用；不会自动重试。":error.message,"err");}
  finally {busy=false;await refresh();buttons();}
}
function invalidate(){configHash=null;$("badge").textContent="配置已修改";$("badge").className="badge";buttons();}
fields.forEach(id=>$(id).addEventListener("input",invalidate));
$("vendor").addEventListener("change",()=>{
  if($("vendor").value==="deepseek"){$("baseUrl").value="https://api.deepseek.com/v1";$("model").value="deepseek-flash";$("inputPrice").value="0.30";$("outputPrice").value="1.20";}
  else{$("baseUrl").value="";$("model").value="";$("advanced").open=true;}
  invalidate();
});
$("apiKey").addEventListener("input",buttons);
$("toggleKey").addEventListener("click",()=>{const show=$("apiKey").type==="password";$("apiKey").type=show?"text":"password";$("toggleKey").textContent=show?"隐藏":"显示";$("toggleKey").setAttribute("aria-label",show?"隐藏密钥":"显示密钥");});
$("btnClear").addEventListener("click",()=>{$("apiKey").value="";$("apiKey").type="password";$("toggleKey").textContent="显示";buttons();message("status","已清除页面内存中的密钥。");});
$("btnSave").addEventListener("click",saveConfig);
$("btnTest").addEventListener("click",()=>request("test"));
$("btnModels").addEventListener("click",()=>request("models"));
$("btnRun").addEventListener("click",()=>request("run"));
window.addEventListener("pagehide",()=>{$("apiKey").value="";});
refresh();
