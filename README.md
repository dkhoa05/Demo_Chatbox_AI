# 🚀 Demo Chatbox AI (Flask + Gemini)

A modern AI chatbox built with:

- 🔹 Flask backend
- 🔹 Gemini API (Google Generative AI)
- 🔹 File upload (txt, pdf, docx, csv, image OCR)
- 🔹 Dark / Light theme toggle
- 🔹 Typing indicator animation
- 🔹 Rate limiting
- 🔹 Context injection from uploaded files

---

## 📦 Installation

```bash
pip install -r requirements.txt
python app.py
Create a .env file:

GEMINI_API_KEY=your_api_key_here
GEMINI_MODEL=gemini-2.0-flash
FLASK_PORT=5000
Then open:

http://127.0.0.1:5000
🛠 Tech Stack
Python

Flask

Google Gemini API

HTML / CSS / Vanilla JS

✨ Features
AI chat with retry backoff

Upload file → inject into prompt

PDF / DOCX / CSV reader

Image OCR (Tesseract)

Modern glass UI

Typing indicator animation
