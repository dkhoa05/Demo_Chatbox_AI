import os
import time
import csv
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple

import requests
from flask import Flask, request, render_template, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

import pytesseract
from PIL import Image
import PyPDF2
import docx

# ================== LOAD ENV ==================
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or "gemini-2.0-flash").strip()
FLASK_PORT = int(os.getenv("FLASK_PORT") or "5000")

GEMINI_MODELS_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_LIST_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# ================== LOGGING ==================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("app")
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

# ================== APP CONFIG ==================
app = Flask(__name__)

UPLOAD_FOLDER = str(BASE_DIR / "static" / "uploads")
ALLOWED_EXTENSIONS = {"txt", "pdf", "docx", "csv", "jpg", "jpeg", "png"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

# ================== Flask-Limiter (optional) ==================
limiter = None
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address

    limiter = Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=["30 per minute"]
    )
    logger.info("✓ Flask-Limiter enabled (30/min)")
except Exception as e:
    limiter = None
    logger.warning(f"⚠️ Flask-Limiter not enabled: {e}. Install: pip install Flask-Limiter")

# ================== TESSERACT PATH ==================
tesseract_paths = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]
for p in tesseract_paths:
    if os.path.exists(p):
        pytesseract.pytesseract.tesseract_cmd = p
        logger.info(f"✓ Tesseract found: {p}")
        break
else:
    logger.warning("⚠️ Tesseract not found. OCR ảnh sẽ không chạy.")

def tesseract_ok() -> bool:
    cmd = getattr(pytesseract.pytesseract, "tesseract_cmd", "")
    return bool(cmd) and os.path.exists(cmd)

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[-1].lower() in ALLOWED_EXTENSIONS

def unique_filename(folder: str, filename: str) -> str:
    name, ext = os.path.splitext(filename)
    candidate = filename
    full = os.path.join(folder, candidate)
    if not os.path.exists(full):
        return candidate
    i = 2
    while True:
        candidate = f"{name}__{i}{ext}"
        full = os.path.join(folder, candidate)
        if not os.path.exists(full):
            return candidate
        i += 1

# ================== CHAT FALLBACK ==================
def demo_fallback_bot(message: str) -> str:
    msg = (message or "").strip().lower()
    if not msg:
        return "Nhập gì đó đi bro."
    if any(x in msg for x in ["hello", "hi", "chào"]):
        return "Chào mày. Gemini đang bị quota/rate-limit, nhưng UI + upload vẫn chạy."
    if any(x in msg for x in ["help", "giúp", "hướng dẫn"]):
        return "Gemini đang lỗi quota/rate-limit nên tao fallback. Upload file rồi hỏi tiếp."
    if "ocr" in msg:
        return "Upload ảnh (jpg/png) tao OCR cho. Nếu thiếu Tesseract thì thôi."
    return "Gemini đang không phản hồi (quota/rate-limit). Nhưng upload + đọc file/OCR vẫn chạy."

# ================== GEMINI CALL ==================
def gemini_generate(message: str, timeout: int = 60) -> Tuple[bool, str]:
    if not GEMINI_API_KEY:
        return False, "NO_KEY"

    url = f"{GEMINI_MODELS_BASE}/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {"contents": [{"parts": [{"text": message}]}]}

    retries = 5
    base_sleep = 1.5

    for attempt in range(retries):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)

            if resp.status_code == 200:
                data = resp.json()
                try:
                    return True, data["candidates"][0]["content"]["parts"][0]["text"]
                except Exception:
                    return False, "BAD_FORMAT"

            if resp.status_code in (429, 503):
                sleep_s = base_sleep * (2 ** attempt)
                logger.warning(f"[Gemini retry] HTTP_{resp.status_code}, sleep {sleep_s:.1f}s (attempt {attempt+1}/{retries})")
                time.sleep(sleep_s)
                continue

            return False, f"HTTP_{resp.status_code}: {resp.text}"

        except requests.exceptions.RequestException as e:
            return False, f"NETWORK_ERROR: {e}"

    return False, "HTTP_429: Resource exhausted (retried)"

def chatbot_response(prompt: str) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        return "⚠️ Vui lòng nhập một tin nhắn."
    if len(prompt) > 20000:
        return "⚠️ Nội dung quá dài (giới hạn 20000 ký tự)."

    ok, out = gemini_generate(prompt)
    if ok:
        return out

    logger.warning(f"[Gemini fail] {out[:600]}")
    return demo_fallback_bot(prompt)

# ================== FILE READER ==================
def read_file_content(file_path: str, ext: str) -> str:
    try:
        if ext == "txt":
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                t = f.read()
                return t if t.strip() else "⚠️ TXT rỗng."

        if ext == "pdf":
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                texts = []
                for page in reader.pages:
                    t = page.extract_text()
                    if t:
                        texts.append(t)
                return "\n".join(texts) if texts else "⚠️ PDF không trích xuất được text (PDF scan thì cần OCR PDF)."

        if ext == "docx":
            d = docx.Document(file_path)
            texts = [p.text for p in d.paragraphs if p.text.strip()]
            return "\n".join(texts) if texts else "⚠️ DOCX rỗng."

        if ext == "csv":
            lines = []
            with open(file_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
                reader = csv.reader(f)
                for row in reader:
                    lines.append(", ".join(row))
            return "\n".join(lines) if lines else "⚠️ CSV rỗng."

        if ext in {"jpg", "jpeg", "png"}:
            if not tesseract_ok():
                return "⚠️ Chưa cài Tesseract nên không OCR được ảnh."
            image = Image.open(file_path)
            text = pytesseract.image_to_string(image, lang="vie+eng")
            return text if text.strip() else "⚠️ Không tìm thấy text trong ảnh."

        return "❌ Không hỗ trợ định dạng này."
    except Exception as e:
        logger.error(f"read_file_content error: {e}")
        return f"❌ Lỗi khi đọc file: {str(e)[:200]}"

# ================== ROUTES ==================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/favicon.ico")
def favicon():
    return "", 204

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "env_found": ENV_PATH.exists(),
        "has_api_key": bool(GEMINI_API_KEY),
        "model": GEMINI_MODEL,
        "tesseract_found": tesseract_ok(),
        "upload_folder": UPLOAD_FOLDER,
        "ts": time.time(),
    })

@app.route("/models")
def list_models():
    if not GEMINI_API_KEY:
        return jsonify({"error": "NO_KEY"}), 400
    try:
        url = f"{GEMINI_LIST_MODELS_URL}?key={GEMINI_API_KEY}"
        r = requests.get(url, timeout=30)
        return jsonify({"status_code": r.status_code, "data": r.json()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/send_message", methods=["POST"])
def send_message():
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()

    context = (data.get("context") or "").strip()
    context_name = (data.get("context_name") or "").strip()

    if context:
        if len(context) > 12000:
            context = context[:12000] + "\n...[TRUNCATED]"

        prompt = (
            "Bạn là trợ lý trả lời dựa trên nội dung file người dùng đã upload.\n"
            f"File: {context_name or 'unknown'}\n\n"
            f"Nội dung file:\n{context}\n\n"
            f"Câu hỏi người dùng:\n{user_message}"
        )
    else:
        prompt = user_message

    bot_message = chatbot_response(prompt)
    return jsonify({"message": bot_message})

@app.route("/upload", methods=["POST"])
def upload_files():
    files = request.files.getlist("files")
    if not files:
        one = request.files.get("file")
        files = [one] if one else []

    if not files:
        return jsonify({"error": "Không có tệp nào được gửi!"}), 400

    results: List[Dict[str, Any]] = []

    for f in files:
        if not f or not f.filename:
            results.append({"filename": "", "error": "Tên tệp không hợp lệ!"})
            continue

        raw_name = secure_filename(f.filename)
        if not raw_name:
            results.append({"filename": "", "error": "Tên tệp sau khi sanitize bị rỗng."})
            continue

        if not allowed_file(raw_name):
            results.append({
                "filename": raw_name,
                "error": f"Định dạng không hỗ trợ. Cho phép: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            })
            continue

        safe_name = unique_filename(app.config["UPLOAD_FOLDER"], raw_name)
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], safe_name)
        f.save(file_path)

        ext = safe_name.rsplit(".", 1)[-1].lower()
        content = read_file_content(file_path, ext)

        results.append({
            "filename": safe_name,
            "original_name": raw_name,
            "file_url": f"/uploads/{safe_name}",
            "file_content": content,
            "mimetype": f.mimetype or "",
        })

    return jsonify({"message": "✓ Upload xong!", "files": results}), 200

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    filename = secure_filename(filename)
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": f"Tệp quá lớn. Max: {MAX_FILE_SIZE / 1024 / 1024:.0f}MB"}), 413

# ================== MAIN ==================
if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("🚀 Starting Chatbox")
    logger.info(f"✓ .env found: {ENV_PATH.exists()}")
    logger.info(f"✓ Model: {GEMINI_MODEL}")
    logger.info(f"✓ Has key: {bool(GEMINI_API_KEY)}")
    logger.info(f"✓ Tesseract: {tesseract_ok()}")
    logger.info(f"Server: http://127.0.0.1:{FLASK_PORT}")
    logger.info("=" * 60)
    app.run(debug=True, port=FLASK_PORT, use_reloader=True)
