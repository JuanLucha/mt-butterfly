// ── Token ────────────────────────────────────────────────────────────────────
const TOKEN = new URLSearchParams(window.location.search).get("t") || "";

function navigate(path) {
  window.location.href = path + (TOKEN ? `?t=${encodeURIComponent(TOKEN)}` : "");
}

async function apiFetch(path, options = {}) {
  const sep = path.includes("?") ? "&" : "?";
  const url = path + sep + `t=${encodeURIComponent(TOKEN)}`;
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res;
}

// ── Markdown (minimal) ───────────────────────────────────────────────────────
function renderMarkdown(text) {
  return text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/```([\s\S]*?)```/g, "<pre><code>$1</code></pre>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/\n/g, "<br>");
}

// ── Chat page ────────────────────────────────────────────────────────────────
if (document.getElementById("channel-list")) {
  let channels = [];
  let activeChannelId = null;
  let ws = null;
  let streamingEl = null;
  let streamingContent = "";

  const channelList   = document.getElementById("channel-list");
  const messagesEl    = document.getElementById("messages");
  const inputEl       = document.getElementById("msg-input");
  const sendBtn       = document.getElementById("send-btn");
  const chatHeader    = document.getElementById("chat-header-name");
  const statusDot     = document.getElementById("status-dot");
  const noChannel     = document.getElementById("no-channel");
  const chatArea      = document.getElementById("chat-area");
  const modal         = document.getElementById("channel-modal");
  const modalName     = document.getElementById("modal-channel-name");
  const modalDir      = document.getElementById("modal-working-dir");

  // Load channels on start
  async function loadChannels() {
    try {
      const res = await apiFetch("/api/channels");
      channels = await res.json();
      renderChannelList();
    } catch (e) {
      console.error("Failed to load channels", e);
    }
  }

  function renderChannelList() {
    channelList.innerHTML = "";
    channels.forEach(ch => {
      const item = document.createElement("div");
      item.className = "channel-item" + (ch.id === activeChannelId ? " active" : "");
      item.dataset.id = ch.id;
      item.innerHTML = `
        <span class="ch-name"># ${escHtml(ch.name)}</span>
        <button class="ch-del" title="Delete" onclick="deleteChannel(event,'${ch.id}')">✕</button>
      `;
      item.addEventListener("click", () => openChannel(ch.id));
      channelList.appendChild(item);
    });
  }

  function escHtml(s) {
    return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
  }

  async function openChannel(id) {
    intentionalClose = true;
    clearTimeout(reconnectTimer);
    if (ws) { ws.close(); ws = null; }
    intentionalClose = false;
    activeChannelId = id;
    const ch = channels.find(c => c.id === id);
    chatHeader.textContent = "# " + ch.name;
    noChannel.style.display = "none";
    chatArea.style.display  = "flex";
    messagesEl.innerHTML = "";
    setConnected(false);
    renderChannelList();
    connectWS(id);
  }

  let reconnectTimer = null;
  let reconnectDelay = 1000;
  let intentionalClose = false;

  function connectWS(channelId) {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/chat/${channelId}?t=${encodeURIComponent(TOKEN)}`);

    ws.onopen = () => {
      setConnected(true);
      reconnectDelay = 1000;
    };

    ws.onclose = () => {
      setConnected(false);
      ws = null;
      if (!intentionalClose && activeChannelId === channelId) {
        setReconnecting(true);
        reconnectTimer = setTimeout(() => {
          if (activeChannelId === channelId) connectWS(channelId);
        }, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, 30000);
      }
    };

    ws.onerror = () => setConnected(false);

    ws.onmessage = ({ data }) => {
      const msg = JSON.parse(data);
      handleWsMessage(msg);
    };
  }

  function setReconnecting(on) {
    statusDot.className = "ch-status" + (on ? " reconnecting" : "");
  }

  function handleWsMessage(msg) {
    if (msg.type === "history") {
      appendMessage(msg.role, msg.content);
    } else if (msg.type === "user") {
      // already shown optimistically — skip duplicate
    } else if (msg.type === "assistant_start") {
      streamingContent = "";
      streamingEl = appendMessage("assistant", "", true);
      setWaiting(true);
    } else if (msg.type === "chunk") {
      streamingContent += msg.content;
      if (streamingEl) {
        streamingEl.querySelector(".msg-body").innerHTML = renderMarkdown(streamingContent);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }
    } else if (msg.type === "assistant_end") {
      setWaiting(false);
      if (streamingEl) {
        streamingEl.classList.remove("streaming");
        streamingEl = null;
        streamingContent = "";
      }
    } else if (msg.type === "error") {
      setWaiting(false);
      appendError(msg.message);
    }
  }

  function appendMessage(role, content, streaming = false) {
    const div = document.createElement("div");
    div.className = `msg ${role}` + (streaming ? " streaming" : "");
    div.innerHTML = `
      <div class="role-label">${role === "user" ? "You" : "OpenCode"}</div>
      <div class="msg-body">${renderMarkdown(content)}</div>
    `;
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    return div;
  }

  function appendError(text) {
    const div = document.createElement("div");
    div.style.cssText = "color:#f85149;font-size:0.8rem;align-self:center;padding:0.5rem;";
    div.textContent = "⚠ " + text;
    messagesEl.appendChild(div);
  }

  let waiting = false;
  let typingEl = null;

  function setConnected(ok) {
    statusDot.className = "ch-status" + (ok ? " connected" : "");
    inputEl.disabled  = !ok || waiting;
    sendBtn.disabled  = !ok || waiting;
  }

  function setWaiting(on) {
    waiting = on;
    sendBtn.disabled = on;
    inputEl.disabled = on;
    if (on && !typingEl) {
      typingEl = document.createElement("div");
      typingEl.className = "msg assistant";
      typingEl.innerHTML = '<div class="role-label">OpenCode</div><div class="typing-indicator"><span></span><span></span><span></span></div>';
      messagesEl.appendChild(typingEl);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    } else if (!on && typingEl) {
      typingEl.remove();
      typingEl = null;
    }
  }

  function sendMessage() {
    const text = inputEl.value.trim();
    if (!text || !ws || ws.readyState !== WebSocket.OPEN) return;
    appendMessage("user", text);
    ws.send(JSON.stringify({ message: text }));
    inputEl.value = "";
    inputEl.style.height = "42px";
  }

  sendBtn.addEventListener("click", sendMessage);
  inputEl.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  inputEl.addEventListener("input", () => {
    inputEl.style.height = "42px";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
  });

  // ── Modal ──
  window.openChannelModal = () => {
    modalName.value = ""; modalDir.value = "";
    modal.classList.add("open");
    modalName.focus();
  };
  window.closeChannelModal = () => modal.classList.remove("open");
  window.createChannel = async () => {
    const name = modalName.value.trim();
    if (!name) { modalName.focus(); return; }
    try {
      await apiFetch("/api/channels", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, working_dir: modalDir.value.trim() || null }),
      });
      modal.classList.remove("open");
      await loadChannels();
    } catch (e) {
      alert("Error creating channel: " + e.message);
    }
  };
  modal.addEventListener("click", e => { if (e.target === modal) closeChannelModal(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeChannelModal(); });

  window.deleteChannel = async (e, id) => {
    e.stopPropagation();
    if (!confirm("Delete this channel and all its messages?")) return;
    try {
      await apiFetch(`/api/channels/${id}`, { method: "DELETE" });
      if (activeChannelId === id) {
        intentionalClose = true;
        clearTimeout(reconnectTimer);
        if (ws) { ws.close(); ws = null; }
        intentionalClose = false;
        activeChannelId = null;
        noChannel.style.display = "flex";
        chatArea.style.display  = "none";
      }
      await loadChannels();
    } catch (e2) {
      alert("Error deleting channel: " + e2.message);
    }
  };

  loadChannels();
}
