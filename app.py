from flask import Flask, render_template_string, request, make_response, redirect
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
        html, body {
            height: 100%;
            margin: 0;
            padding: 0;
            font-family: Arial, sans-serif;
            background-color: #0d0d0d;
            color: white;
            box-sizing: border-box;
            text-align: center;
        }

        body {
            display: block;
            padding: 0px;
        }

        h2 {
            margin: 0 0 20px 0;
            text-align: center;
        }

        .container {
            width: 100%;
            max-width: 500px;
            margin: 0 auto;
            padding-top: 20px;
        }

        input, button, textarea, select {
            width: 100%;
            padding: 10px;
            margin: 10px 0;
            box-sizing: border-box;
            border-radius: 5px;
            border: 1px solid #444;
            background-color: #1a1a1a;
            color: #e0e0e0;
            font-size: 14px;
        }

        button {
            cursor: pointer;
            background-color: #333;
            color: #fff;
            transition: background 0.3s;
        }

        button:hover {
            background-color: #141414;
        }

        label {
            display: block;
            text-align: left;
            margin-top: 15px;
            font-size: 14px;
        }

        .note {
            color:#cfcfcf; 
            font-size:13px; 
            margin-bottom:8px;
            text-align: center;
        }

        .result-box {
            width: 100%;
            background: #1a1a1a;
            margin-top: 20px;
            margin: auto;
        }

        .result-box table {
            width: 100%;
            border-collapse: collapse;
        }

        .result-box th, .result-box td {
            border: 1px solid #333;
            padding: 8px;
        }
        #result-buttons {
            display: flex;
            gap: 10px;
        }
        #download-btn{
            flex: 1;
            padding: 0;
            border: none;
            background-color: transparent;
        }
        #download-btn img{
            width: 40px;
            height: 40px;
            border-radius: 8px; /* Rounded corners */
            border: none;
            transition: transform 0.2s ease, opacity 0.2s ease;
            cursor: pointer;
        }
        #download-btn img:hover {
            transform: scale(1.07);
            opacity: 0.85;
        }

        @media screen and (max-width: 600px) {
            .container {
                max-width: 100%;
            }
        }
    </style>
</head>
<body>
    <div class="container">
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
            <label>Select Term</label>
            <select name="term" id="term">
                <option value="68">1st Term</option>
                <option value="73">2nd Term</option>
                <option value="78" selected>3rd Term</option>
            </select>
            <div id="result-buttons">
                <button type="submit">Get Result</button>
                <button id="download-btn" formaction="/download" formmethod="POST"><img src="static/download.jpg"></button>
            </div>
        </form>
        {% endif %}
    </div>

    {% if result %}
        <div class="result-box">
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
PREVIEW_URL = "https://portal.cloudcampus24.com/Report/AccademicTranscript/Preview"

# ------------------- HELPER FUNCTIONS -------------------


def cloudcampus_login(session: requests.Session, username: str, password: str) -> bool:
    """
    Perform strict login check.
    Returns True ONLY if credentials are correct.
    """

    # Load login page
    try:
        r = session.get(LOGIN_URL, timeout=15)
    except:
        return False

    soup = BeautifulSoup(r.text, "html.parser")
    token = soup.find("input", {"name": "__RequestVerificationToken"})
    if not token:
        return False

    csrf = token["value"]

    payload = {
        "UserName": username,
        "Password": password,
        "__RequestVerificationToken": csrf,
        "ReturnUrl": "/"
    }

    # POST credentials
    try:
        login_res = session.post(
            LOGIN_URL,
            data=payload,
            headers={"Referer": LOGIN_URL, "User-Agent": "Mozilla/5.0"},
            timeout=15,
            allow_redirects=True
        )
    except:
        return False

    # After login, check INDEX page
    try:
        idx = session.get(INDEX_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    except:
        return False

    html = idx.text

    # STRICT checks
    if "Login" in html and "Password" in html:
        # Still shows login screen → wrong credentials
        return False

    # If no token found → not authenticated
    if '__RequestVerificationToken' not in html:
        return False

    # SUCCESS
    return True



def fetch_transcript(session: requests.Session, target_student_id: str, target_term: str):
    """
    Returns a dict:
      { "ok": True, "html": "<...>" }
    or
      { "ok": False, "error": "auth"|"student"|"network", "message": "..." }
    """
    try:
        r = session.get(INDEX_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    except Exception as e:
        print("fetch_transcript: index GET failed:", e)
        return {"ok": False, "error": "network", "message": "Network error. Try again."}

    if r.status_code != 200:
        print("fetch_transcript: index status != 200:", r.status_code)
        # If index redirected to login or returned non-200 it's likely auth issue
        return {"ok": False, "error": "auth", "message": "Not authenticated."}

    index_html = r.text
    # extract token for AJAX call
    m = re.search(r'name="__RequestVerificationToken"\s+value="([^"]+)"', index_html)
    token = m.group(1) if m else ""

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/json",
        "__RequestVerificationToken": token,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://portal.cloudcampus24.com",
        "Referer": INDEX_URL
    }
    payload = {"StudentIdC": target_student_id, "ReferID": target_term}
    try:
        res = session.post(SEARCH_URL, headers=headers, json=payload, timeout=15, allow_redirects=True)
    except Exception as e:
        print("fetch_transcript: search POST failed:", e)
        return {"ok": False, "error": "network", "message": "Network error while searching. Try again."}

    # If the portal redirected to login or returned login page, treat as auth failure
    if res.status_code in (401, 403) or ("Login" in res.text and "__RequestVerificationToken" in res.text == False):
        print("fetch_transcript: search returned auth-like response:", res.status_code)
        return {"ok": False, "error": "auth", "message": "Authentication failed."}

    if res.status_code != 200 or "500 - Internal Server Error" in res.text:
        # Most likely wrong student id or server error
        if res.status_code == 500 or "Internal Server Error" in res.text:
            return {"ok": False, "error": "student", "message": "Wrong student ID, please try again."}
        return {"ok": False, "error": "student", "message": "Wrong student ID, please try again."}

    html = res.text
    html = html.replace("</head>", dark_css + "</head>") if "</head>" in html else dark_css + html
    return {"ok": True, "html": html}


@app.route("/download", methods=["POST"])
def download_transcript():
    # Load saved credentials
    creds_cookie = request.cookies.get("portal_creds")
    if not creds_cookie:
        return redirect("/")

    try:
        username, password = serializer.loads(creds_cookie)
    except Exception:
        # malformed cookie -> clear and redirect to login
        resp = make_response(redirect("/"))
        resp.set_cookie("portal_creds", "", expires=0)
        return resp

    # Get student + term
    student_id = request.form.get("student_id", "").strip()
    term = request.form.get("term", "").strip()

    # Start login session
    session = requests.Session()

    # Login using saved creds (necessary to get auth cookies)
    if not cloudcampus_login(session, username, password):
        # Credentials invalid → clear cookie + show login form with error
        resp = make_response(render_template_string(
            HTML_FORM, creds_needed=True,
            result="<b style='color:red;'>Saved credentials are invalid. Please sign in again.</b>"
        ))
        resp.set_cookie("portal_creds", "", expires=0)
        return resp

    # Fetch token from INDEX page
    try:
        r = session.get(INDEX_URL, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        token_input = soup.find("input", {"name": "__RequestVerificationToken"})
        if not token_input:
            return render_template_string(
                HTML_FORM,
                creds_needed=False,
                result="<b style='color:red;'>Server error! Please try again.</b>"
            )
        csrf_token = token_input["value"]
    except Exception as e:
        print("download: index GET failed:", e)
        return render_template_string(
            HTML_FORM,
            creds_needed=False,
            result="<b style='color:red;'>Network error! Try again.</b>"
        )

    # Build Preview request
    payload = {
        "__RequestVerificationToken": csrf_token,
        "StudentIdCHdnTerm": student_id,
        "ReferIDTerm": term
    }

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://portal.cloudcampus24.com",
        "Referer": INDEX_URL
    }

    # Send Preview request
    try:
        preview = session.post(PREVIEW_URL, data=payload, headers=headers, timeout=20, allow_redirects=True)
    except Exception as e:
        print("download: preview POST failed:", e)
        return render_template_string(
            HTML_FORM,
            creds_needed=False,
            result="<b style='color:red;'>An error occurred. Please try again.</b>"
        )

    # If preview indicates auth problem
    if preview.status_code in (401, 403) or ("Login" in preview.text and "__RequestVerificationToken" not in preview.text):
        resp = make_response(render_template_string(
            HTML_FORM, creds_needed=True,
            result="<b style='color:red;'>Saved credentials are invalid. Please sign in again.</b>"
        ))
        resp.set_cookie("portal_creds", "", expires=0)
        return resp

    if preview.status_code != 200 or "500 - Internal Server Error" in preview.text:
        resp = make_response("", 302)
        resp.headers["Location"] = "/"
        resp.set_cookie("transcript_error", "Wrong student ID, please try again.", max_age=3)
        return resp


    # Success → send file to user
    resp = make_response(preview.content)
    resp.headers["Content-Disposition"] = (
        f"attachment; filename=result_{student_id}.pdf"
    )
    resp.mimetype = "application/pdf"
    return resp


@app.route("/", methods=["GET", "POST"])
def index_route():
    creds_needed = True
    result = None
    # Check if redirected with error
    error_msg = request.cookies.get("transcript_error")
    if error_msg:
        result = f"<b style='color:red;'>{error_msg}</b>"


    # Check cookie
    creds_cookie = request.cookies.get("portal_creds")
    username = password = None
    if creds_cookie:
        try:
            username, password = serializer.loads(creds_cookie)
            creds_needed = False
        except Exception:
            creds_needed = True

    if request.method == "POST":
        if creds_needed:
            # Save credentials to cookie, but verify them first
            username = request.form.get("login_username", "").strip()
            password = request.form.get("login_password", "").strip()
            if username and password:
                # verify by logging in and confirming INDEX loads correctly
                temp_session = requests.Session()
                if not cloudcampus_login(temp_session, username, password):
                    # do NOT save cookie
                    return render_template_string(
                        HTML_FORM, creds_needed=True,
                        result="<b style='color:red;'>Login failed! Check username/password.</b>"
                    )
                # LOGIN SUCCESS -> save cookie
                cookie_value = serializer.dumps([username, password])
                resp = make_response(render_template_string(
                    HTML_FORM, creds_needed=False,
                    result="<b style='color:green;'>Credentials saved! Enter Student ID.</b>"
                ))
                resp.set_cookie("portal_creds", cookie_value, max_age=30*24*3600)  # 30 days
                return resp
        else:
            # Fetch transcript
            target_student_id = request.form.get("student_id", "").strip()
            target_term = request.form.get("term", "").strip()

            # Re-load saved creds and ensure they're valid for a session
            creds_cookie = request.cookies.get("portal_creds")
            if not creds_cookie:
                return render_template_string(HTML_FORM, creds_needed=True,
                                              result="<b style='color:red;'>Please sign in first.</b>")
            try:
                username, password = serializer.loads(creds_cookie)
            except Exception:
                resp = make_response(render_template_string(
                    HTML_FORM, creds_needed=True,
                    result="<b style='color:red;'>Saved credentials corrupted. Please sign in again.</b>"
                ))
                resp.set_cookie("portal_creds", "", expires=0)
                return resp

            session = requests.Session()
            if not cloudcampus_login(session, username, password):
                # login failed -> clear cookie and show login form
                resp = make_response(render_template_string(
                    HTML_FORM, creds_needed=True,
                    result="<b style='color:red;'>Saved credentials are invalid. Please sign in again.</b>"
                ))
                resp.set_cookie("portal_creds", "", expires=0)
                return resp

            fetched = fetch_transcript(session, target_student_id, target_term)
            if not fetched["ok"]:
                # handle errors specifically
                if fetched["error"] == "auth":
                    resp = make_response(render_template_string(
                        HTML_FORM, creds_needed=True,
                        result=f"<b style='color:red;'>{fetched['message']}</b>"
                    ))
                    resp.set_cookie("portal_creds", "", expires=0)
                    return resp
                else:
                    result = f"<b style='color:red;'>{fetched['message']}</b>"
            else:
                result = fetched["html"]

    resp = make_response(render_template_string(
        HTML_FORM,
        creds_needed=creds_needed,
        result=result
    ))
    resp.set_cookie("transcript_error", "", expires=0)
    return resp



if __name__ == "__main__":
    app.run(debug=True)
