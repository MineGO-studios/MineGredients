import os
import json
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Load environment vars
load_dotenv()

# --- CONFIGURATION ---
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"  # Development only

CLIENT_SECRETS_FILE = "credentials.json"
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/spreadsheets",
]
REDIRECT_URI = "http://localhost:8000/oauth2callback"

USER_DB_FILE = "user_sheets.json"

# --- FASTAPI SETUP ---
app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "dev-key")
)
templates = Jinja2Templates(directory="templates")

def load_user_db():
    if os.path.exists(USER_DB_FILE):
        with open(USER_DB_FILE, "r") as f:
            return json.load(f)
    return {}

def save_user_db(db):
    with open(USER_DB_FILE, "w") as f:
            json.dump(db, f)

def credentials_to_dict(credentials):
    return {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes,
    }

def create_user_sheet_if_needed(user_email, credentials):
    db = load_user_db()
    if user_email in db:
        return db[user_email]["sheet_id"]
    try:
        svc = build("sheets", "v4", credentials=credentials)
        sheet = svc.spreadsheets().create(body={"properties": {"title": "MineGredients"}}).execute()
        sheet_id = sheet["spreadsheetId"]
        headers = [["Name","Protein","Carbs","Fat","Fiber","Sodium","Sugar","Weight (g/ml)"]]
        svc.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range="A1:H1",
            valueInputOption="RAW",
            body={"values": headers}
        ).execute()
        db[user_email] = {"sheet_id": sheet_id}
        save_user_db(db)
        return sheet_id
    except HttpError as e:
        print(f"Google API error for {user_email}: {e}")
        raise HTTPException(500, "Could not create your Google Sheet. Try again later.")
    except Exception as e:
        print(f"Unknown error for {user_email}: {e}")
        raise HTTPException(500, "Unexpected onboarding error. Try again later.")

# --- ROUTES ---
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if "user_email" not in request.session:
        return RedirectResponse("/login")
    user_email = request.session["user_email"]
    onboarding = request.session.pop("onboarding_done", False)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "user_email": user_email,
        "onboarding": onboarding
    })

@app.get("/login")
async def login(request: Request):
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )
    request.session["oauth_state"] = state
    return RedirectResponse(url)

@app.get("/oauth2callback")
async def oauth2callback(request: Request):
    state = request.session.get("oauth_state")
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=state,
        redirect_uri=REDIRECT_URI
    )
    flow.fetch_token(authorization_response=str(request.url))
    creds = flow.credentials
    user_info = build("oauth2", "v2", credentials=creds).userinfo().get().execute()
    email = user_info["email"]
    request.session["user_email"] = email
    request.session["google_token"] = credentials_to_dict(creds)
    try:
        sheet_id = create_user_sheet_if_needed(email, creds)
        request.session["sheet_id"] = sheet_id
        request.session["onboarding_done"] = True
        return RedirectResponse("/")
    except HTTPException as e:
        return HTMLResponse(f"<h2>Error</h2><p>{e.detail}</p><a href='/login'>Retry</a>", status_code=500)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login")
