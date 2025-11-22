from flask import Flask, render_template_string, request, make_response
import requests
from bs4 import BeautifulSoup
import re
from itsdangerous import URLSafeSerializer

app = Flask(__name__)
SECRET_KEY = "replace_this_with_a_random_secret_key"  # change this to something secret
serializer = URLSafeSerializer(SECRET_KEY)

HTML_FORM = """
<!DOCTYPE html>
<html>
<head>
    <title>Transcript Fetcher</title>
    <style>
        body { background-color: #0d0d0d; color: white; font-family: Arial; padding: 20px; }
        input, button, textarea { padding: 10px; margin-top: 10px; display:block; }
        textarea { width: 300px; height: 40px; }
        label { margin-top:12px; display:block; font-size:14px; }
        .note { color:#cfcfcf; font-size:13px; margin-bottom:8px; }
    </style>
</head>
<body>
    <h2>Student Transcript Checker</h2>
    {% if creds_needed %}
    <p class="note">Enter your portal username & password (stored securely in cookies for this device)</p>
    <form method="POST">
        <label>Portal Username</label>
        <input name="login_username" placeholder="Your portal username" required>
        <label>Portal Password</label>
        <input type="password" name="login_password" placeholder="Portal password" required>
        <button type="submit">Save Credentials</button>
    </form>
    {% else %}
    <p class="note">Enter the <strong>student ID</strong> to fetch transcript</p>
    <form method="POST">
        <label>Target Student ID</label>
        <textarea name="student_id" placeholder="Enter Student ID" required></textarea>
        <button type="submit">Get Result</button>
    </form>
    {% endif %}

    {% if result %}
        <hr>
        <h3>Result</h3>
        <div style="background:#1a1a1a; padding:20px; border-radius:8px;">
            {{ result|safe }}
        </div>
    {% endif %}
</body>
</html>
"""

dark_css = """
<style>
body { background-color: #0d0d0d !important; color: #e0e0e0 !important; font-family: Arial, sans-serif; }
table { background-color: #1a1a1a !important; color: #e0e0e0 !important; border-color: #333 !important; }
th { background-color: #222 !important; color: #fff !important; border: 1px solid #444 !important; }
td { background-color: #1a1a1a !important; border: 1px solid #333 !important; }
strong { color: #fff !important; }
.row, .col-sm-4, .col-sm-12 { background-color: #0d0d0d !important; }
</style>
"""

LOGIN_URL = "https://portal.cloudcampus24.com/UserAuth/Login?ReturnUrl=%2F"
INDEX_URL = "https://portal.cloudcampus24.com/Report/AccademicTranscript/Index"
SEARCH_URL = "https://portal.cloudcampus24.com/Report/AccademicTranscript/SearchTerm"

# ------------------- HELPER FUNCTIONS -------------------

def cloudcampus_login(session: requests.Session, username: str, password: str):
    r = session.get(LOGIN_URL, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")
    token_input = soup.find("input", {"name": "__RequestVerificationToken"})
    if not token_input or not token_input.get("value"):
        return False
    csrf_token = token_input["value"]
    payload = {
        "UserName": username,
        "Password": password,
        "__RequestVerificationToken": csrf_token,
        "ReturnUrl": "/"
    }
    headers = {"User-Agent": "Mozilla/5.0", "Referer": LOGIN_URL}
    post = session.post(LOGIN_URL, data=payload, headers=headers, timeout=15, allow_redirects=True)
    if post.url != LOGIN_URL or ("Logout" in post.text) or session.cookies.get("CloudCmpXGXV_1.14.0_SBDF"):
        return True
    return False

def fetch_transcript(session: requests.Session, target_student_id: str):
    r = session.get(INDEX_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    index_html = r.text
    m = re.search(r'name="__RequestVerificationToken"\s+value="([^"]+)"', index_html)
    token = m.group(1) if m else session.cookies.get("__RequestVerificationToken")
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
        "__RequestVerificationToken": token,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://portal.cloudcampus24.com",
        "Referer": INDEX_URL
    }
    payload = {"StudentIdC": target_student_id, "ReferID": "78"}
    res = session.post(SEARCH_URL, headers=headers, json=payload, timeout=15)
    html = res.text
    html = html.replace("</head>", dark_css + "</head>") if "</head>" in html else dark_css + html
    return html

# ------------------- FLASK ROUTE -------------------

@app.route("/", methods=["GET", "POST"])
def index_route():
    creds_needed = True
    result = None

    # Check cookie
    creds_cookie = request.cookies.get("portal_creds")
    username = password = None
    if creds_cookie:
        try:
            username, password = serializer.loads(creds_cookie)
            creds_needed = False
        except:
            creds_needed = True

    if request.method == "POST":
        if creds_needed:
            # Save credentials to cookie
            username = request.form.get("login_username").strip()
            password = request.form.get("login_password").strip()
            if username and password:
                resp = make_response(render_template_string(HTML_FORM, creds_needed=False, result="<b style='color:green;'>Credentials saved! Enter Student ID.</b>"))
                cookie_value = serializer.dumps([username, password])
                resp.set_cookie("portal_creds", cookie_value, max_age=30*24*3600)  # 30 days
                return resp
        else:
            # Fetch transcript
            target_student_id = request.form.get("student_id").strip()
            session = requests.Session()
            if not cloudcampus_login(session, username, password):
                result = "<b style='color:red;'>Login failed! Check saved credentials.</b>"
            else:
                result = fetch_transcript(session, target_student_id)

    return render_template_string(HTML_FORM, creds_needed=creds_needed, result=result)

# ------------------- RUN APP -------------------
if __name__ == "__main__":
    app.run(debug=True)
