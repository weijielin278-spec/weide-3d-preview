const $ = (selector) => document.querySelector(selector);

let mode = "register";

function setStatus(message) {
  $("#accountStatus").textContent = message;
}

function setMode(nextMode) {
  mode = nextMode === "login" ? "login" : "register";
  $("#showLoginBtn").classList.toggle("active", mode === "login");
  $("#showRegisterBtn").classList.toggle("active", mode === "register");
  $("#inviteRow").hidden = mode !== "register";
  $("#submitAccountBtn").textContent = mode === "register" ? "Create Account and Continue" : "Sign In and Continue";
  setStatus(
    mode === "register"
      ? "New accounts receive 100 free credits. If you do not have an invite code, please contact us."
      : "Enter your registered email to continue.",
  );
}

async function checkExistingLogin() {
  try {
    const response = await fetch("/api/me");
    const result = await response.json();
    if (result.user) location.href = nextUrl();
  } catch {
    // Stay on login page.
  }
}

function nextUrl() {
  const params = new URLSearchParams(location.search);
  const next = params.get("next") || "./client-preview.html";
  if (/^https?:\/\//i.test(next)) return "./client-preview.html";
  return next.startsWith("./") || next.startsWith("/") ? next : `./${next}`;
}

async function submitAccount() {
  const email = $("#accountEmail").value.trim();
  const inviteCode = $("#inviteCode").value.trim();
  setStatus(mode === "register" ? "Creating account..." : "Signing in...");
  try {
    const response = await fetch(mode === "register" ? "/api/register" : "/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, inviteCode }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(formatAccountError(result.error || "Account request failed", mode));
    setStatus("Success. Opening your 3D preview tool...");
    location.href = nextUrl();
  } catch (error) {
    setStatus(formatAccountError(error.message, mode));
  }
}

function formatAccountError(message = "", currentMode = mode) {
  const text = String(message);
  if (/email/i.test(text)) return "Please enter a valid email address.";
  if (/already/i.test(text)) return "This email is already registered. Please sign in instead.";
  if (/invite/i.test(text)) return "The invite code is incorrect or inactive. Please contact us for a valid invite code.";
  if (/not found|registered/i.test(text)) return "No account was found for this email. Please create an account first.";
  if (currentMode === "register") return "Registration failed. Please check your email and invite code, or contact us for help.";
  if (currentMode === "login") return "Sign in failed. Please check your email or create an account first.";
  return text || "Account request failed.";
}

$("#showLoginBtn").addEventListener("click", () => setMode("login"));
$("#showRegisterBtn").addEventListener("click", () => setMode("register"));
$("#submitAccountBtn").addEventListener("click", submitAccount);
["accountEmail", "inviteCode"].forEach((id) => {
  $(`#${id}`).addEventListener("keydown", (event) => {
    if (event.key === "Enter") submitAccount();
  });
});

setMode("register");
checkExistingLogin();
