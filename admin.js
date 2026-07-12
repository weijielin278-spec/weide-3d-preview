const $ = (selector) => document.querySelector(selector);

function adminCode() {
  return $("#adminCode")?.value || localStorage.getItem("factoryAdminCode") || "";
}

function setStatus(message) {
  $("#adminStatus").textContent = message;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

async function adminFetch(url, options = {}) {
  const headers = { ...(options.headers || {}), "X-Admin-Code": adminCode() };
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const response = await fetch(url, { ...options, headers });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "后台请求失败");
  return result;
}

async function loadAdmin() {
  localStorage.setItem("factoryAdminCode", adminCode());
  const data = await adminFetch("/api/admin/summary");
  renderUsers(data.users || []);
  renderInvites(data.invites || []);
  renderRecords(data.records || []);
  setStatus(`后台已加载。新用户赠送 ${data.pricing?.startingCredits || 100} 积分，每次新生成扣 ${data.pricing?.generationCost || 20} 积分。`);
}

function renderUsers(users) {
  $("#userTable").innerHTML = users.length
    ? `<table><thead><tr><th>邮箱</th><th>积分</th><th>邀请码</th><th>注册时间</th><th>最后登录</th></tr></thead><tbody>${users
        .map((user) => `<tr><td>${esc(user.email)}</td><td>${esc(user.credits)}</td><td>${esc(user.inviteCode)}</td><td>${esc(user.createdAt)}</td><td>${esc(user.lastLoginAt)}</td></tr>`)
        .join("")}</tbody></table>`
    : `<p class="hint">暂无用户。</p>`;
}

function renderInvites(invites) {
  $("#inviteTable").innerHTML = invites.length
    ? `<table><thead><tr><th>邀请码</th><th>状态</th><th>使用者</th><th>使用时间</th></tr></thead><tbody>${invites
        .map((item) => `<tr><td>${esc(item.code)}</td><td>${item.active ? "可用" : "停用"}</td><td>${esc(item.usedBy)}</td><td>${esc(item.usedAt)}</td></tr>`)
        .join("")}</tbody></table>`
    : `<p class="hint">暂无邀请码。</p>`;
}

function renderRecords(records) {
  $("#recordTable").innerHTML = records.length
    ? `<table><thead><tr><th>时间</th><th>类型</th><th>邮箱</th><th>积分变化</th><th>余额</th><th>备注</th></tr></thead><tbody>${records
        .slice()
        .reverse()
        .map((item) => `<tr><td>${esc(item.createdAt)}</td><td>${esc(item.type)}</td><td>${esc(item.email)}</td><td>${esc(item.credits)}</td><td>${esc(item.balance)}</td><td>${esc(item.note || item.fileName || "")}</td></tr>`)
        .join("")}</tbody></table>`
    : `<p class="hint">暂无记录。</p>`;
}

async function addCredits() {
  const email = $("#creditEmail").value;
  const amount = Number($("#creditAmount").value);
  const note = $("#creditNote").value;
  await adminFetch("/api/admin/add-credits", {
    method: "POST",
    body: JSON.stringify({ email, amount, note }),
  });
  setStatus("积分已添加。");
  await loadAdmin();
}

async function createInvite() {
  const code = $("#newInviteCode").value;
  const result = await adminFetch("/api/admin/create-invite", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
  $("#newInviteCode").value = result.code || "";
  setStatus(`邀请码已生成：${result.code}`);
  await loadAdmin();
}

$("#loadAdminBtn").addEventListener("click", () => loadAdmin().catch((error) => setStatus(error.message)));
$("#addCreditsBtn").addEventListener("click", () => addCredits().catch((error) => setStatus(error.message)));
$("#createInviteBtn").addEventListener("click", () => createInvite().catch((error) => setStatus(error.message)));

const savedCode = localStorage.getItem("factoryAdminCode");
if (savedCode) $("#adminCode").value = savedCode;
