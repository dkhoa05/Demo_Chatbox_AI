// ================== STATE ==================
let fileContext = "";       // text lấy từ upload để nhét vào prompt
let fileContextName = "";   // tên file hiện tại
let botTypingEl = null;     // bubble 3 chấm của bot

const $ = (id) => document.getElementById(id);

const chatBody  = $("chatBody");
const msg       = $("msg");
const sendBtn   = $("sendBtn");
const fileInput = $("fileInput");
const uploadBtn = $("uploadBtn");
const attachBtn = $("attachBtn");
const filesBox  = $("files");
const themeBtn  = $("themeBtn");
const themeText = $("themeText");

// ================== UTIL ==================
function scrollToBottom(){
  chatBody.scrollTop = chatBody.scrollHeight;
}

function escapeHtml(s){
  return (s || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function addMsg(text, who = "bot"){
  const wrap = document.createElement("div");
  wrap.className = `msg ${who}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;

  wrap.appendChild(bubble);
  chatBody.appendChild(wrap);
  scrollToBottom();
  return wrap;
}

function createTypingBubble(who = "bot"){
  const wrap = document.createElement("div");
  wrap.className = `msg ${who}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble typing";
  bubble.innerHTML = `
    <span class="typing-dots" aria-label="typing">
      <span class="dot"></span><span class="dot"></span><span class="dot"></span>
    </span>
  `;

  wrap.appendChild(bubble);
  chatBody.appendChild(wrap);
  scrollToBottom();
  return wrap;
}

function removeEl(el){
  if (el && el.parentNode) el.parentNode.removeChild(el);
}

function setButtonsDisabled(disabled){
  sendBtn.disabled = disabled;
  uploadBtn.disabled = disabled;

  // attach chỉ bật khi có context
  if (disabled) attachBtn.disabled = true;
  else attachBtn.disabled = !fileContext.trim();
}

function truncateContext(text, limit = 12000){
  const t = (text || "").trim();
  if (!t) return "";
  if (t.length <= limit) return t;
  return t.slice(0, limit) + "\n...[TRUNCATED]";
}

// ================== THEME ==================
const root = document.documentElement;

function applyTheme(next){
  root.dataset.theme = next; // <html data-theme="dark">
  localStorage.setItem("theme", next);
  if (themeText) themeText.textContent = next === "dark" ? "Dark" : "Light";
}

function getPreferredTheme(){
  const saved = localStorage.getItem("theme");
  if (saved === "dark" || saved === "light") return saved;

  if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches){
    return "dark";
  }
  return "light";
}

// init theme
applyTheme(getPreferredTheme());

// toggle
if (themeBtn){
  themeBtn.addEventListener("click", () => {
    const cur = root.dataset.theme || "light";
    applyTheme(cur === "dark" ? "light" : "dark");
  });
}

// auto update theme if user chưa chọn theme thủ công
if (!localStorage.getItem("theme") && window.matchMedia){
  window.matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", (e) => applyTheme(e.matches ? "dark" : "light"));
}

// ================== TEXTAREA AUTO-GROW ==================
function autoGrow(el){
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 140) + "px";
}

if (msg){
  msg.addEventListener("input", () => autoGrow(msg));

  msg.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey){
      e.preventDefault();
      sendBtn.click();
    }
  });
}

// ================== SEND MESSAGE ==================
async function sendMessage(){
  const text = (msg.value || "").trim();
  if (!text) return;

  addMsg(text, "you");
  msg.value = "";
  autoGrow(msg);

  const payload = {
    message: text,
    context: truncateContext(fileContext, 12000),
    context_name: fileContextName
  };

  // show typing...
  if (botTypingEl) removeEl(botTypingEl);
  botTypingEl = createTypingBubble("bot");

  setButtonsDisabled(true);

  try{
    const res = await fetch("/send_message", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(payload)
    });

    const data = await res.json().catch(() => ({}));

    removeEl(botTypingEl);
    botTypingEl = null;

    if (!res.ok){
      addMsg("❌ Server trả lỗi: " + (data.error || res.status), "bot");
      return;
    }

    addMsg(data.message || "(no response)", "bot");
  }catch(err){
    removeEl(botTypingEl);
    botTypingEl = null;
    addMsg("❌ Lỗi gọi server: " + err, "bot");
  }finally{
    setButtonsDisabled(false);
  }
}

if (sendBtn) sendBtn.addEventListener("click", sendMessage);

// ================== UPLOAD FILES ==================
async function uploadFiles(){
  const files = fileInput.files;
  if (!files || files.length === 0){
    addMsg("Chọn file trước đã Bro.", "bot");
    return;
  }

  const fd = new FormData();
  for (const f of files) fd.append("files", f);

  uploadBtn.disabled = true;
  filesBox.innerHTML = "";

  const uploading = addMsg("⏳ Đang upload và đọc nội dung file...", "bot");

  try{
    const res = await fetch("/upload", { method:"POST", body: fd });
    const data = await res.json().catch(() => ({}));

    removeEl(uploading);

    if (!res.ok){
      addMsg("❌ Upload lỗi: " + (data.error || "unknown"), "bot");
      fileContext = "";
      fileContextName = "";
      attachBtn.disabled = true;
      return;
    }

    const combined = [];
    const list = data.files || [];

    for (const item of list){
      const card = document.createElement("div");
      card.className = "file-card";

      const head = document.createElement("div");
      head.className = "file-head";

      const left = document.createElement("div");
      left.innerHTML = `
        <div class="file-name">${escapeHtml(item.filename || "")}</div>
        <div class="file-meta">${escapeHtml(item.mimetype || "")}</div>
      `;

      const open = document.createElement("a");
      open.className = "btn ghost";
      open.textContent = "Open";
      open.href = item.file_url || "#";
      open.target = "_blank";
      open.rel = "noreferrer";

      head.appendChild(left);
      head.appendChild(open);

      const body = document.createElement("div");
      body.className = "file-body";
      body.textContent = item.file_content || "";

      card.appendChild(head);
      card.appendChild(body);
      filesBox.appendChild(card);

      const content = (item.file_content || "").trim();
      if (content){
        const tag = (content.startsWith("⚠️") || content.startsWith("❌")) ? "[WARN]" : "[OK]";
        combined.push(`### FILE: ${item.filename} ${tag}\n${content}`);
      }
    }

    fileContext = combined.join("\n\n");
    fileContextName = (list[0] && list[0].filename) ? list[0].filename : "";

    attachBtn.disabled = !fileContext.trim();

    addMsg(
      fileContext.trim()
        ? "✓ Upload xong. Bấm **Attach to chat** rồi hỏi gì về file cũng được."
        : "⚠️ Upload xong nhưng không có nội dung để attach.",
      "bot"
    );

  }catch(err){
    removeEl(uploading);
    addMsg("❌ Upload lỗi: " + err, "bot");
  }finally{
    uploadBtn.disabled = false;
    fileInput.value = ""; // reset chọn file
  }
}

if (uploadBtn) uploadBtn.addEventListener("click", uploadFiles);

// tiện: click attach icon => mở picker file
const pickBtn = $("pickBtn"); // nếu HTML có nút pickBtn
if (pickBtn && fileInput){
  pickBtn.addEventListener("click", () => fileInput.click());
}

// ================== ATTACH BUTTON ==================
if (attachBtn){
  attachBtn.addEventListener("click", () => {
    if (!fileContext.trim()){
      addMsg("Không có nội dung để attach. PDF scan ảnh thì phải OCR (cài Tesseract).", "bot");
      return;
    }
    addMsg("📎 Đã attach file context. Giờ hỏi gì liên quan file cũng được.", "bot");
  });
}

// ================== INIT ==================
(function init(){
  if (attachBtn) attachBtn.disabled = true;

  // lời chào (bật nếu thích)
  // addMsg("Chào Bro. Upload file xong bấm Attach rồi hỏi.", "bot");
})();
