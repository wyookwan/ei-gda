import json, os, re, uuid
from functools import wraps
from flask import session, redirect, url_for, flash

def json_dumps(obj):
    return json.dumps(obj, ensure_ascii=False)

def json_loads(s, default=None):
    if not s:
        return default if default is not None else {}
    try:
        return json.loads(s)
    except Exception:
        return default if default is not None else {}

def normalize_text(text: str) -> str:
    text = text or ""
    text = text.replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()

def extract_headings_from_text(text: str):
    headings = []
    for raw in (text or '').splitlines():
        line = raw.strip()
        if not line or len(line) > 160:
            continue
        if re.match(r"^(\d+(\.\d+)*\s+.+|[A-Z][A-Z\s\-\&]{4,}|ABSTRACT|REFERENCES|ACKNOWLEDGEMENT[S]?)$", line):
            headings.append(line)
    seen, out = set(), []
    for h in headings:
        k = h.lower()
        if k not in seen:
            seen.add(k)
            out.append(h)
    return out[:300]

def save_uploaded_file(file_storage, upload_folder):
    ext = os.path.splitext(file_storage.filename)[1].lower()
    new_name = f"{uuid.uuid4().hex}{ext}"
    os.makedirs(upload_folder, exist_ok=True)
    path = os.path.join(upload_folder, new_name)
    file_storage.save(path)
    return new_name, path

def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get('user_id'):
                return redirect(url_for('login'))
            if role and session.get('role') != role:
                flash('Access denied.', 'danger')
                dest = {'admin':'admin_dashboard','committee':'committee_dashboard','user':'dashboard'}.get(session.get('role'),'login')
                return redirect(url_for(dest))
            return fn(*args, **kwargs)
        return wrapper
    return deco
