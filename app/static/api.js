// ── Token ────────────────────────────────────────────────────────────────────
// On first load the token may arrive via ?t= (HTML navigation). Store it in
// sessionStorage immediately and clean the URL so it doesn't appear in history
// or server logs on subsequent requests.
(function () {
  const params = new URLSearchParams(window.location.search);
  const t = params.get("t");
  if (t) {
    sessionStorage.setItem("mt_token", t);
    params.delete("t");
    const clean = window.location.pathname + (params.toString() ? "?" + params.toString() : "");
    window.history.replaceState({}, "", clean);
  }
})();

const TOKEN = sessionStorage.getItem("mt_token") || "";

function navigate(path) {
  window.location.href = TOKEN ? path + "?t=" + encodeURIComponent(TOKEN) : path;
}

async function apiFetch(path, options = {}) {
  options.headers = { ...options.headers, "Authorization": `Bearer ${TOKEN}` };
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res;
}

function escHtml(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ── Markdown ─────────────────────────────────────────────────────────────────
// Uses the marked library (loaded via CDN in base.html) for correct parsing of
// nested constructs (code blocks with asterisks, links, nested lists, etc.)
function renderMarkdown(text) {
  if (!text) return "";
  return marked.parse(text, { breaks: true });
}
