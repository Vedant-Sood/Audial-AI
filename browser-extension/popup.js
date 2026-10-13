const portInput=document.querySelector("#port"),button=document.querySelector("#translate"),status=document.querySelector("#status");
const saved=await chrome.storage.local.get("companionPort");
if(saved.companionPort)portInput.value=saved.companionPort;
button.addEventListener("click",async()=>{
  const port=Number(portInput.value);
  if(!Number.isInteger(port)||port<1||port>65535){status.textContent="Enter a port between 1 and 65535.";return;}
  button.disabled=true;
  try{
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    if(!tab?.id)throw new Error("Open a normal browser page first.");
    const [result]=await chrome.scripting.executeScript({target:{tabId:tab.id},func:()=>{
      const selected=globalThis.getSelection()?.toString().trim();
      return selected||document.querySelector("main")?.innerText||document.body?.innerText||"";
    }});
    const text=result?.result?.trim();
    if(!text)throw new Error("No readable page text was found. Select some text and try again.");
    if(text.length>20000)throw new Error("Select an extract up to 20,000 characters. The page is too long to open in one playback request.");
    await chrome.storage.local.set({companionPort:port});
    await chrome.tabs.create({url:`http://127.0.0.1:${port}/#text=${encodeURIComponent(text)}`});
    window.close();
  }catch(error){status.textContent=error.message.includes("Cannot access")?"This browser page cannot be read by extensions. Copy its text into AccessibilityAI instead.":error.message;button.disabled=false;}
});
