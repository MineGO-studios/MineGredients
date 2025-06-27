from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
load_dotenv()
import os
import google_auth_oauthlib.flow
import googleapiclient.discovery
import googleapiclient.errors
import pickle

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "dev-key"))  # Replace with a real random key for production
templates = Jinja2Templates(directory="templates")

# Settings
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = "1pBkxBebvkW8IwHsqZVwdZ871yhFzRvkm8ig8fKDAuXs"  # <--- Replace with your own Google Sheet ID

def get_credentials():
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)
        return creds
    return None

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    creds = get_credentials()
    if not creds:
        return RedirectResponse("/login")
    # Read current ingredients
    service = googleapiclient.discovery.build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=SHEET_ID, range="Sheet1!A1:H").execute()
    values = result.get("values", [])
    return templates.TemplateResponse("index.html", {"request": request, "ingredients": values})

@app.get("/login")
async def login(request: Request):
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        "credentials.json", scopes=SCOPES)
    flow.redirect_uri = "http://localhost:8000/oauth2callback"
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true"
    )
    request.session["state"] = state
    return RedirectResponse(authorization_url)

@app.get("/oauth2callback")
async def oauth2callback(request: Request):
    state = request.session.get("state")
    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        "credentials.json", scopes=SCOPES, state=state)
    flow.redirect_uri = "http://localhost:8000/oauth2callback"
    authorization_response = str(request.url)
    flow.fetch_token(authorization_response=authorization_response)
    creds = flow.credentials
    with open("token.pickle", "wb") as token:
        pickle.dump(creds, token)
    return RedirectResponse("/")

@app.post("/add")
async def add_ingredient(request: Request,
                         name: str = Form(...), protein: str = Form(""), carbs: str = Form(""),
                         fat: str = Form(""), fiber: str = Form(""), sodium: str = Form(""),
                         sugar: str = Form(""), weight: str = Form("")):
    creds = get_credentials()
    if not creds:
        return RedirectResponse("/login")
    service = googleapiclient.discovery.build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()
    row = [name, protein, carbs, fat, fiber, sodium, sugar, weight]
    sheet.values().append(
        spreadsheetId=SHEET_ID,
        range="Sheet1!A1",
        valueInputOption="USER_ENTERED",
        body={"values": [row]}
    ).execute()
    return RedirectResponse("/", status_code=303)
