import os
import time
import csv
import logging
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
load_dotenv()  # đọc .env cùng thư mục app.py

GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = (os.getenv("GEMINI_MODEL") or "gemini-2.0-flash").strip()
FLASK_PORT = int(os.getenv("FLASK_PORT") or "5000")

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1/models"


# ================== LOGGING ==================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("app")
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)


# ================== APP CONFIG ==================
app = Flask(__name__)

UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"txt", "pdf", "docx", "csv", "jpg", "jpeg", "png"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE


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


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[-1].lower() in ALLOWED_EXTENSIONS


# ================== CHAT FALLBACK ==================
def demo_fallback_bot(message: str) -> str:
    msg = (message or "").strip().lower()
    if not msg:
        return "Nhập gì đó đi bro."

    if any(x in msg for x in ["hello", "hi", "chào"]):
        return "Chào mày. Gemini đang bị quota/permission, nhưng UI + upload vẫn chạy."
    if any(x in msg for x in ["help", "giúp", "hướng dẫn"]):
        return (
            "Gemini đang lỗi quota/key/permission nên tao fallback.\n"
            "Test thử upload nhiều file (txt/pdf/docx/csv/ảnh) để xem đọc nội dung + OCR."
        )
    if "ocr" in msg:
        return "Upload ảnh (jpg/png) tao OCR cho. Nếu thiếu Tesseract thì thôi."
    return "Gemini đang không phản hồi (quota/key/permission). Nhưng upload + đọc file/OCR vẫn chạy."


# ================== GEMINI CALL ==================
def gemini_generate(message: str, timeout: int = 60) -> Tuple[bool, str]:
    if not GEMINI_API_KEY:
        return False, "NO_KEY"

    url = f"{GEMINI_BASE}/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    payload = {"contents": [{"parts": [{"text": message}]}]}

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)

        if resp.status_code == 200:
            data = resp.json()
            try:
                return True, data["candidates"][0]["content"]["parts"][0]["text"]
            except Exception:
                return False, "BAD_FORMAT"

        # trả về nguyên body để biết nó chửi gì (403/429/400...)
        return False, f"HTTP_{resp.status_code}: {resp.text}"

    except requests.exceptions.RequestException as e:
        return False, f"NETWORK_ERROR: {e}"


def chatbot_response(message: str) -> str:
    message = (message or "").strip()
    if not message:
        return "⚠️ Vui lòng nhập một tin nhắn."
    if len(message) > 10000:
        return "⚠️ Tin nhắn quá dài (tối đa 10000 ký tự)."

    ok, out = gemini_generate(message)
    if ok:
        return out

    logger.warning(f"[Gemini fail] {out[:400]}")
    return demo_fallback_bot(message)


# ================== FILE READER ==================
def read_file_content(file_path: str, ext: str) -> str:
    try:
        if ext == "txt":
            with open(file_path, "r", encoding="utf-8") as f:
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
                return "\n".join(texts) if texts else "⚠️ PDF không trích xuất được text."

        if ext == "docx":
            d = docx.Document(file_path)
            texts = [p.text for p in d.paragraphs if p.text.strip()]
            return "\n".join(texts) if texts else "⚠️ DOCX rỗng."

        if ext == "csv":
            lines = []
            with open(file_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                for row in reader:
                    lines.append(", ".join(row))
            return "\n".join(lines) if lines else "⚠️ CSV rỗng."

        if ext in {"jpg", "jpeg", "png"}:
            cmd = getattr(pytesseract.pytesseract, "tesseract_cmd", "")
            if not cmd or not os.path.exists(cmd):
                return "⚠️ Chưa cài Tesseract nên không OCR được ảnh."
            image = Image.open(file_path)
            text = pytesseract.image_to_string(image, lang="vie+eng")
            return text if text.strip() else "⚠️ Không tìm thấy text trong ảnh."

        return "❌ Không hỗ trợ định dạng này."

    except Exception as e:
        logger.error(f"read_file_content error: {e}")
        return f"❌ Lỗi khi đọc file: {str(e)[:160]}"


# ================== ROUTES ==================
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "has_api_key": bool(GEMINI_API_KEY),
        "model": GEMINI_MODEL,
        "tesseract_found": bool(getattr(pytesseract.pytesseract, "tesseract_cmd", "")) and os.path.exists(getattr(pytesseract.pytesseract, "tesseract_cmd", "")),
        "upload_folder": UPLOAD_FOLDER,
        "ts": time.time()
    })


@app.route("/send_message", methods=["POST"])
def send_message():
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    bot_message = chatbot_response(user_message)
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

        filename = secure_filename(f.filename)
        if not allowed_file(filename):
            results.append({
                "filename": filename,
                "error": f"Định dạng không hỗ trợ. Cho phép: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            })
            continue

        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        f.save(file_path)

        ext = filename.rsplit(".", 1)[-1].lower()
        content = read_file_content(file_path, ext)

        results.append({
            "filename": filename,
            "file_url": f"/uploads/{filename}",
            "file_content": content,
            "mimetype": f.mimetype or ""
        })

    return jsonify({"message": "✓ Upload xong!", "files": results}), 200


@app.route("/uploads/<filename>")
def uploaded_file(filename):
    filename = secure_filename(filename)
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": f"Tệp quá lớn. Max: {MAX_FILE_SIZE / 1024 / 1024:.0f}MB"}), 413


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("🚀 Starting Chatbox")
    logger.info(f"✓ Model: {GEMINI_MODEL}")
    logger.info(f"✓ Has key: {bool(GEMINI_API_KEY)}")
    logger.info(f"Server: http://127.0.0.1:{FLASK_PORT}")
    logger.info("=" * 60)
    app.run(debug=True, port=FLASK_PORT, use_reloader=True)
