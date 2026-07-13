import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "5173"))
HOST = os.environ.get("HOST", "0.0.0.0")
CACHE_DIR = Path(os.environ.get("CACHE_DIR", str(ROOT / "runtime-data" / "model-cache")))
MODEL_DIR = CACHE_DIR / "models"
CACHE_PATH = CACHE_DIR / "engine-cache.json"
LOG_PATH = CACHE_DIR / "engine-debug.log"
LEGACY_CACHE_PATH = Path(os.environ.get("LEGACY_CACHE_PATH", str(ROOT / "runtime-data" / "legacy-meshy-cache.json")))
LEGACY_MODEL_DIR = Path(os.environ.get("LEGACY_MODEL_DIR", str(ROOT / "runtime-data" / "legacy-models")))
ACCOUNT_DIR = Path(os.environ.get("FACTORY_ACCOUNT_DIR", str(ROOT / "runtime-data" / "factory-accounts")))
ACCOUNT_PATH = ACCOUNT_DIR / "accounts.json"
EXPORT_DIR = Path(os.environ.get("EXPORT_DIR", str(ROOT / "exports")))
GENERATION_COST = 20
STARTING_CREDITS = 50
ADMIN_CODE = os.environ.get("FACTORY_ADMIN_CODE", "KIKI-ADMIN-2026")
DEFAULT_INVITES = ["KIKI-FACTORY-001", "KIKI-FACTORY-002", "KIKI-FACTORY-003"]


def load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def image_hash(data_url):
    payload = str(data_url).split(",", 1)[-1]
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalize_dimensions(body):
    if body.get("sizeMode") != "custom" or not isinstance(body.get("dimensions"), dict):
        return None
    dims = body["dimensions"]
    try:
        width = max(20, min(300, float(dims.get("widthMm", 80))))
        height = max(20, min(300, float(dims.get("heightMm", 92))))
        thickness = max(1, min(30, float(dims.get("thicknessMm", 7))))
        length_in = max(0.8, min(12, float(dims.get("lengthIn", height / 25.4))))
        width_in = max(0.8, min(12, float(dims.get("widthIn", width / 25.4))))
        height_in = max(0.04, min(1.2, float(dims.get("heightIn", thickness / 25.4))))
    except Exception:
        return None
    return {"widthMm": width, "heightMm": height, "thicknessMm": thickness, "lengthIn": length_in, "widthIn": width_in, "heightIn": height_in}


def cache_key(base_hash, dimensions):
    if not dimensions:
        return base_hash
    size_text = f"{dimensions['widthMm']}x{dimensions['heightMm']}x{dimensions['thicknessMm']}"
    return hashlib.sha256(f"{base_hash}:{size_text}".encode("utf-8")).hexdigest()


def read_cache():
    for path in (CACHE_PATH, LEGACY_CACHE_PATH):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data.get("entries"), list):
                return {"version": 1, "entries": data["entries"]}
        except Exception:
            pass
    return {"version": 1, "entries": []}


def write_cache(cache):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def now_iso():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def normalize_email(email):
    return str(email or "").strip().lower()


def default_account_data():
    return {
        "version": 1,
        "users": [],
        "sessions": {},
        "invites": [{"code": code, "active": True, "usedBy": ""} for code in DEFAULT_INVITES],
        "records": [],
    }


def read_accounts():
    ACCOUNT_DIR.mkdir(parents=True, exist_ok=True)
    if not ACCOUNT_PATH.exists():
        data = default_account_data()
        write_accounts(data)
        return data
    try:
        data = json.loads(ACCOUNT_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = default_account_data()
    data.setdefault("users", [])
    data.setdefault("sessions", {})
    data.setdefault("invites", [])
    data.setdefault("records", [])
    existing = {item.get("code") for item in data["invites"]}
    for code in DEFAULT_INVITES:
        if code not in existing:
            data["invites"].append({"code": code, "active": True, "usedBy": ""})
    return data


def write_accounts(data):
    ACCOUNT_DIR.mkdir(parents=True, exist_ok=True)
    ACCOUNT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def find_user(data, email):
    email = normalize_email(email)
    return next((user for user in data["users"] if normalize_email(user.get("email")) == email), None)


def public_user(user):
    if not user:
        return None
    return {
        "email": user.get("email", ""),
        "credits": int(user.get("credits", 0)),
        "createdAt": user.get("createdAt", ""),
        "inviteCode": user.get("inviteCode", ""),
    }


def cookie_value(headers, name):
    raw = headers.get("Cookie", "")
    for part in raw.split(";"):
        if "=" not in part:
            continue
        key, value = part.strip().split("=", 1)
        if key == name:
            return value
    return ""


def current_user_from_headers(headers):
    data = read_accounts()
    token = cookie_value(headers, "factory_session")
    email = data["sessions"].get(token, "")
    return data, find_user(data, email)


def is_admin(headers):
    return headers.get("X-Admin-Code", "") == ADMIN_CODE


def log(message):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text((LOG_PATH.read_text(encoding="utf-8") if LOG_PATH.exists() else "") + f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n", encoding="utf-8")


def request_json(url, method="GET", body=None, headers=None, timeout=120):
    payload = None
    final_headers = dict(headers or {})
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        final_headers["Content-Type"] = "application/json"
        final_headers["Content-Length"] = str(len(payload))
    req = urllib.request.Request(url, data=payload, method=method, headers=final_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            text = res.read().decode("utf-8", errors="replace")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as err:
        text = err.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(text)
            msg = data.get("message") or data.get("error") or data.get("detail") or text
        except Exception:
            msg = text or str(err)
        log(f"HTTP {err.code} {url} {msg}")
        raise RuntimeError(msg or f"HTTP {err.code}")


def meshy_api_keys():
    keys = []
    for name in ("MESHY_API_KEY", "MESHY_API_KEY_BACKUP"):
        value = os.environ.get(name, "").strip()
        if value and value not in keys:
            keys.append(value)
    return keys


def is_quota_error(error):
    lowered = str(error or "").lower()
    return any(part in lowered for part in ("insufficient funds", "insufficient credits", "not enough credits", "balance"))


def download_to_file(url, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "model/gltf-binary,application/octet-stream,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as res:
        data = res.read()
    if len(data) < 1024:
        raise RuntimeError("Generated model file is invalid, please generate again.")
    path.write_bytes(data)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if self.path == "/api/config":
            self._json({"provider": "white-model-engine", "engineConfigured": bool(os.environ.get("MESHY_API_KEY"))})
            return

        if self.path == "/api/me":
            _, user = current_user_from_headers(self.headers)
            self._json({"user": public_user(user), "generationCost": GENERATION_COST})
            return

        if self.path == "/api/admin/summary":
            if not is_admin(self.headers):
                self._json({"error": "管理员口令不正确。"}, status=403)
                return
            data = read_accounts()
            self._json({
                "users": data["users"],
                "invites": data["invites"],
                "records": data["records"][-80:],
                "pricing": {"generationCost": GENERATION_COST, "startingCredits": STARTING_CREDITS},
            })
            return

        if self.path.startswith("/api/model"):
            query = urllib.parse.urlparse(self.path).query
            model_url = urllib.parse.parse_qs(query).get("url", [""])[0]
            if not model_url.startswith("https://"):
                self.send_error(400, "Invalid model url")
                return
            try:
                req = urllib.request.Request(
                    model_url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "model/gltf-binary,application/octet-stream,*/*",
                    },
                )
                with urllib.request.urlopen(req, timeout=180) as res:
                    data = res.read()
                    content_type = res.headers.get("content-type") or "model/gltf-binary"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
            except Exception as err:
                log(f"model proxy error: {err}")
                self.send_error(502, str(err))
            return

        if self.path.startswith("/api/cached-model/"):
            name = Path(urllib.parse.unquote(self.path.split("/api/cached-model/", 1)[1])).name
            file_path = MODEL_DIR / name
            if not file_path.exists() and (LEGACY_MODEL_DIR / name).exists():
                file_path = LEGACY_MODEL_DIR / name
            if not file_path.exists() or file_path.stat().st_size < 1024:
                self.send_error(404, "Model not found")
                return
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "model/gltf-binary")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
            return

        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/register":
            try:
                self._json(self._register())
            except Exception as err:
                self._json({"error": str(err)}, status=400)
            return

        if self.path == "/api/login":
            try:
                self._json(self._login())
            except Exception as err:
                self._json({"error": str(err)}, status=400)
            return

        if self.path == "/api/logout":
            self._logout()
            self._json({"success": True})
            return

        if self.path == "/api/admin/add-credits":
            try:
                self._json(self._admin_add_credits())
            except Exception as err:
                self._json({"error": str(err)}, status=400)
            return

        if self.path == "/api/admin/create-invite":
            try:
                self._json(self._admin_create_invite())
            except Exception as err:
                self._json({"error": str(err)}, status=400)
            return

        if self.path == "/api/generate-3d":
            try:
                self._json(self._generate())
            except Exception as err:
                log(f"generate error: {err}")
                self._json({"error": str(err)}, status=500)
            return

        if self.path == "/api/save-file":
            try:
                self._json(self._save_file())
            except Exception as err:
                self._json({"error": str(err)}, status=500)
            return

        self.send_error(404, "Not found")

    def _read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def _set_session(self, data, user):
        token = secrets.token_urlsafe(32)
        data["sessions"][token] = user["email"]
        user["lastLoginAt"] = now_iso()
        write_accounts(data)
        self._pending_cookie = f"factory_session={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"

    def _register(self):
        body = self._read_body()
        email = normalize_email(body.get("email"))
        invite_code = str(body.get("inviteCode") or "").strip()
        if "@" not in email or "." not in email:
            raise RuntimeError("请填写有效邮箱。")
        data = read_accounts()
        if find_user(data, email):
            raise RuntimeError("这个邮箱已经注册，请直接登录。")
        invite = next((item for item in data["invites"] if item.get("code") == invite_code and item.get("active")), None)
        if not invite:
            raise RuntimeError("邀请码不正确或已停用。")
        user = {
            "email": email,
            "credits": STARTING_CREDITS,
            "inviteCode": invite_code,
            "createdAt": now_iso(),
            "lastLoginAt": "",
        }
        invite["usedBy"] = email
        invite["usedAt"] = now_iso()
        data["users"].append(user)
        data["records"].append({"type": "register", "email": email, "credits": STARTING_CREDITS, "createdAt": now_iso(), "note": "注册赠送"})
        self._set_session(data, user)
        return {"success": True, "user": public_user(user)}

    def _login(self):
        body = self._read_body()
        email = normalize_email(body.get("email"))
        data = read_accounts()
        user = find_user(data, email)
        if not user:
            raise RuntimeError("这个邮箱还没有注册，请先用邀请码注册。")
        self._set_session(data, user)
        return {"success": True, "user": public_user(user)}

    def _logout(self):
        data = read_accounts()
        token = cookie_value(self.headers, "factory_session")
        if token in data["sessions"]:
            del data["sessions"][token]
            write_accounts(data)
        self._pending_cookie = "factory_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"

    def _admin_add_credits(self):
        if not is_admin(self.headers):
            raise RuntimeError("管理员口令不正确。")
        body = self._read_body()
        email = normalize_email(body.get("email"))
        amount = int(float(body.get("amount", 0)))
        note = str(body.get("note") or "后台加积分").strip()
        if amount == 0:
            raise RuntimeError("积分数量不能为 0。")
        data = read_accounts()
        user = find_user(data, email)
        if not user:
            raise RuntimeError("没有找到这个用户。")
        user["credits"] = int(user.get("credits", 0)) + amount
        data["records"].append({"type": "admin_credit", "email": email, "credits": amount, "balance": user["credits"], "createdAt": now_iso(), "note": note})
        write_accounts(data)
        return {"success": True, "user": public_user(user)}

    def _admin_create_invite(self):
        if not is_admin(self.headers):
            raise RuntimeError("管理员口令不正确。")
        body = self._read_body()
        code = str(body.get("code") or "").strip()
        if not code:
            code = "KIKI-" + secrets.token_hex(3).upper()
        data = read_accounts()
        if any(item.get("code") == code for item in data["invites"]):
            raise RuntimeError("邀请码已存在。")
        data["invites"].append({"code": code, "active": True, "usedBy": "", "createdAt": now_iso()})
        write_accounts(data)
        return {"success": True, "code": code}

    def _generate(self):
        body = self._read_body()
        image = body.get("imageDataUrl", "")
        if not image:
            raise RuntimeError("Please upload an image first.")

        account_data, user = current_user_from_headers(self.headers)
        if not user:
            raise RuntimeError("请先注册或登录，再生成白模。")

        base_digest = image_hash(image)
        dimensions = normalize_dimensions(body)
        digest = cache_key(base_digest, dimensions)
        target = MODEL_DIR / f"{digest}.glb"
        cache = read_cache()

        for entry in cache["entries"]:
            if entry.get("imageHash") != digest:
                continue
            if str(entry.get("taskId", "")).startswith("local-"):
                continue
            local_url = entry.get("localModelUrl") or f"/api/cached-model/{digest}.glb"
            local_path = target
            if local_path.exists() and local_path.stat().st_size > 1024:
                return self._result(entry.get("taskId", ""), local_url, True, user=public_user(user), credits_used=0)
            legacy_path = LEGACY_MODEL_DIR / f"{digest}.glb"
            if legacy_path.exists() and legacy_path.stat().st_size > 1024:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(legacy_path.read_bytes())
                return self._result(entry.get("taskId", ""), f"/api/cached-model/{digest}.glb", True, user=public_user(user), credits_used=0)
            if entry.get("glbUrl", "").startswith("https://"):
                download_to_file(entry["glbUrl"], target)
                return self._result(entry.get("taskId", ""), f"/api/cached-model/{digest}.glb", True, user=public_user(user), credits_used=0)

        if int(user.get("credits", 0)) < GENERATION_COST:
            raise RuntimeError(f"积分不足。生成 1 个新白模需要 {GENERATION_COST} 积分，请联系管理员充值。")

        api_keys = meshy_api_keys()
        if not api_keys:
            raise RuntimeError("White model engine key is not configured.")

        create = None
        api_key = None
        last_error = None
        for index, candidate_key in enumerate(api_keys):
            try:
                create = request_json(
                    "https://api.meshy.ai/openapi/v1/image-to-3d",
                    method="POST",
                    headers={"Authorization": f"Bearer {candidate_key}"},
                    body={
                        "image_url": image,
                        "prompt": self._build_prompt(dimensions),
                        "target_formats": ["glb"],
                        "should_remesh": True,
                        "target_polycount": 30000,
                    },
                )
                api_key = candidate_key
                if index > 0:
                    log("generated with backup key after primary quota was unavailable")
                break
            except Exception as err:
                last_error = err
                if is_quota_error(err) and index < len(api_keys) - 1:
                    log("primary key quota unavailable, retrying with backup key")
                    continue
                raise

        if create is None or api_key is None:
            raise RuntimeError(str(last_error or "White model engine request failed."))
        task_id = create.get("result") or create.get("id") or create.get("task_id")
        if not task_id:
            raise RuntimeError("White model engine did not return a task id.")

        task = self._poll(api_key, task_id)
        urls = task.get("model_urls") or task.get("model_url") or {}
        glb_url = urls.get("glb") or urls.get("glb_url") or task.get("glb_url") or task.get("model_url")
        if not glb_url:
            raise RuntimeError("White model was generated, but no GLB file was returned.")

        local_model_url = f"/api/cached-model/{digest}.glb"
        try:
            download_to_file(glb_url, target)
        except Exception as err:
            log(f"local model download failed, using remote url: {err}")
            local_model_url = glb_url
        entry = {
            "imageHash": digest,
            "sourceImageHash": base_digest,
            "dimensions": dimensions,
            "fileName": Path(body.get("fileName") or "uploaded-image").name,
            "taskId": task_id,
            "glbUrl": glb_url,
            "localModelUrl": local_model_url,
            "thumbnailUrl": task.get("thumbnail_url") or task.get("preview_url") or "",
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        cache["entries"] = [item for item in cache["entries"] if item.get("imageHash") != digest]
        cache["entries"].insert(0, entry)
        cache["entries"] = cache["entries"][:100]
        write_cache(cache)

        account_data, fresh_user = current_user_from_headers(self.headers)
        if not fresh_user:
            raise RuntimeError("登录状态已过期，请重新登录。")
        fresh_user["credits"] = int(fresh_user.get("credits", 0)) - GENERATION_COST
        account_data["records"].append({
            "type": "generate",
            "email": fresh_user["email"],
            "credits": -GENERATION_COST,
            "balance": fresh_user["credits"],
            "fileName": Path(body.get("fileName") or "uploaded-image").name,
            "taskId": task_id,
            "fromCache": False,
            "createdAt": now_iso(),
        })
        write_accounts(account_data)
        return self._result(task_id, entry["localModelUrl"], False, entry["thumbnailUrl"], user=public_user(fresh_user), credits_used=GENERATION_COST)

    def _build_prompt(self, dimensions):
        base = "glass christmas ornament white 3d model, production-ready relief, smooth rounded edges, clean watertight mesh"
        if not dimensions:
            return base
        return (
            f"{base}, target physical size {dimensions['lengthIn']} inches long x "
            f"{dimensions['widthIn']} inches wide x {dimensions['heightIn']} inches high, "
            f"approximately {dimensions['heightMm']}mm long x {dimensions['widthMm']}mm wide x {dimensions['thicknessMm']}mm high, "
            "keep proportions manufacturable for blown glass ornament"
        )

    def _poll(self, api_key, task_id):
        deadline = time.time() + 12 * 60
        while time.time() < deadline:
            task = request_json(
                f"https://api.meshy.ai/openapi/v1/image-to-3d/{task_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=60,
            )
            status = str(task.get("status", "")).upper()
            if status in ("SUCCEEDED", "SUCCESS", "COMPLETED", "COMPLETE"):
                return task
            if status in ("FAILED", "ERROR", "CANCELED", "CANCELLED"):
                detail = task.get("task_error", {}).get("message") or task.get("message") or status
                raise RuntimeError(f"White model generation failed: {detail}")
            time.sleep(5)
        raise RuntimeError("White model generation timed out; the task may still be running.")

    def _save_file(self):
        body = self._read_body()
        file_name = Path(body.get("fileName", "export.bin")).name
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        raw = base64.b64decode(body.get("base64", ""))
        out_path = EXPORT_DIR / file_name
        out_path.write_bytes(raw)
        return {"success": True, "filePath": str(out_path), "backupPath": str(ROOT / "exports" / file_name)}

    def _result(self, task_id, glb_url, from_cache, thumbnail_url="", user=None, credits_used=0):
        return {
            "provider": "white-model-engine",
            "taskId": task_id,
            "status": "SUCCEEDED",
            "glbUrl": glb_url,
            "thumbnailUrl": thumbnail_url,
            "fromCache": from_cache,
            "creditsUsed": credits_used,
            "user": user,
        }

    def _json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if getattr(self, "_pending_cookie", ""):
            self.send_header("Set-Cookie", self._pending_cookie)
            self._pending_cookie = ""
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


if __name__ == "__main__":
    load_env()
    os.chdir(ROOT)
    print(f"V3 preview server running at http://{HOST}:{PORT}/client-preview.html")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
