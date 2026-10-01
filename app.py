import os
import io
import base64
import subprocess
import sys
import uuid
from datetime import datetime

import streamlit as st
from PIL import Image
import requests
from supabase import create_client, Client
from astronomy import Observer, SearchRiseSet, Direction, Body

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool
from youngjin_langchain_tools import StreamlitLanggraphHandler

# --- PAGE CONFIG ---
st.set_page_config(page_title="CraftGPT Agent", page_icon="🚀", layout="centered")

# --- META AI-INSPIRED CSS ---
st.markdown("""
    <style>
        /* ===== Base ===== */
        .stApp {
            background-color: #000000 !important;
            color: #E3E3E3 !important;
        }
        html, body, [class*="css"] {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                         Roboto, Helvetica, Arial, sans-serif;
        }

        /* ===== Hide Streamlit chrome ===== */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {background: transparent !important;}

        /* ===== Title ===== */
        h1 {
            background: linear-gradient(90deg, #A78BFA, #F472B6, #60A5FA);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-weight: 700 !important;
            letter-spacing: -0.5px;
        }
        .caption, [data-testid="stCaptionContainer"] {
            color: #888 !important;
        }

        /* ===== Sidebar ===== */
        section[data-testid="stSidebar"] {
            background-color: #0a0a0a !important;
            border-right: 1px solid #1a1a1a;
        }
        section[data-testid="stSidebar"] * {
            color: #E3E3E3 !important;
        }

        /* ===== Buttons (default + sidebar) ===== */
        .stButton > button {
            background-color: transparent !important;
            color: #E3E3E3 !important;
            border: 1px solid transparent !important;
            border-radius: 10px !important;
            text-align: left !important;
            transition: background-color 0.15s ease, border-color 0.15s ease;
            padding: 8px 12px !important;
        }
        .stButton > button:hover {
            background-color: #1a1a1a !important;
            border-color: #2a2a2a !important;
        }
        .stButton > button:focus {
            box-shadow: none !important;
            border-color: #2a2a2a !important;
        }
        /* Sidebar-wide primary style for New Chat */
        section[data-testid="stSidebar"] .stButton > button {
            background-color: #141414 !important;
            border: 1px solid #1f1f1f !important;
        }
        section[data-testid="stSidebar"] .stButton > button:hover {
            background-color: #1f1f1f !important;
        }

        /* ===== Chat input ===== */
        .stChatInput {
            background-color: #141414 !important;
            border: 1px solid #262626 !important;
            border-radius: 26px !important;
        }
        .stChatInput textarea {
            background-color: transparent !important;
            color: #E3E3E3 !important;
            padding: 12px 18px !important;
            font-size: 15px !important;
        }
        .stChatInput textarea::placeholder {
            color: #666 !important;
        }

        /* ===== Chat messages ===== */
        [data-testid="stChatMessage"] {
            background-color: transparent !important;
            padding: 6px 0 !important;
        }
        /* User bubble right-aligned feel */
        [data-testid="stChatMessage"] p {
            color: #E3E3E3 !important;
            font-size: 15px !important;
            line-height: 1.55 !important;
        }

        /* ===== Download button (icon-like) ===== */
        .stDownloadButton > button {
            background-color: transparent !important;
            color: #777 !important;
            border: none !important;
            border-radius: 8px !important;
            padding: 4px 10px !important;
            font-size: 13px !important;
        }
        .stDownloadButton > button:hover {
            color: #E3E3E3 !important;
            background-color: #1a1a1a !important;
        }

        /* ===== Inputs (login forms etc.) ===== */
        .stTextInput input, .stTextArea textarea {
            background-color: #141414 !important;
            color: #E3E3E3 !important;
            border: 1px solid #262626 !important;
            border-radius: 10px !important;
        }

        /* ===== Selectbox ===== */
        div[data-baseweb="select"] > div {
            background-color: #141414 !important;
            border: 1px solid #262626 !important;
            border-radius: 10px !important;
        }

        /* ===== Tabs ===== */
        .stTabs [data-baseweb="tab"] {
            color: #888 !important;
        }
        .stTabs [aria-selected="true"] {
            color: #E3E3E3 !important;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: 8px;
            border-bottom: 1px solid #1f1f1f;
        }

        /* ===== Divider ===== */
        hr {
            border-color: #1f1f1f !important;
        }

        /* ===== Scrollbar ===== */
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #222; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: #333; }

        /* ===== Top-right model badge ===== */
        .model-badge {
            display: inline-block;
            background: #141414;
            color: #aaa;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 12px;
            border: 1px solid #262626;
            float: right;
        }

        /* ===== Sidebar section labels ===== */
        .sidebar-label {
            font-size: 11px;
            color: #666 !important;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin: 12px 0 6px 0;
            font-weight: 600;
        }
    </style>
""", unsafe_allow_html=True)

# --- SPARKLE AVATAR (Meta AI-style gradient) ---
SPARKLE_AVATAR = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
    "<stop offset='0' stop-color='%23A78BFA'/>"
    "<stop offset='0.5' stop-color='%23F472B6'/>"
    "<stop offset='1' stop-color='%2360A5FA'/>"
    "</linearGradient></defs>"
    "<path fill='url(%23g)' d='M16 3l1.8 8.2L26 13l-8.2 1.8L16 23l-1.8-8.2L6 13l8.2-1.8z'/>"
    "<circle fill='url(%23g)' cx='25' cy='6' r='2'/>"
    "<circle fill='url(%23g)' cx='6' cy='24' r='2'/>"
    "</svg>"
)

# --- HEADER ---
st.title("CraftGPT Agent")

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

# --- API KEYS ---
OPENROUTER_KEY = st.secrets.get("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY")
GROQ_KEY       = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
TAVILY_KEY     = st.secrets.get("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY")
FIRECRAWL_KEY  = st.secrets.get("FIRECRAWL_API_KEY") or os.getenv("FIRECRAWL_API_KEY")
IPGEO_KEY      = st.secrets.get("IPGEOLOCATION_API_KEY") or os.getenv("IPGEOLOCATION_API_KEY")
SUPABASE_URL   = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = st.secrets.get("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_ANON_KEY")
SUPABASE_DB_URL = st.secrets.get("SUPABASE_DB_URL") or os.getenv("SUPABASE_DB_URL")

# --- WORKSPACE DIRECTORY ---
WORKSPACE = "agent_workspace"
os.makedirs(WORKSPACE, exist_ok=True)

# --- PERSISTENT CHECKPOINTER ---
@st.cache_resource
def get_checkpointer():
    try:
        pool = ConnectionPool(
            SUPABASE_DB_URL,
            max_size=5,
            max_idle=300.0,
            kwargs={"autocommit": True, "prepare_threshold": 0},
        )
        checkpointer = PostgresSaver(pool)
        checkpointer.setup()
        return checkpointer
    except Exception as e:
        st.error(f"Checkpointer failed to initialize: {e}")
        return None

checkpointer = get_checkpointer()

# --- SUPABASE CLIENT ---
@st.cache_resource
def init_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        return None
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

supabase = init_supabase()

# --- PASSWORD HASHING ---
import bcrypt
import secrets as pysecrets

def hash_pwd(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def check_pwd(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False

# --- AUTH FUNCTIONS ---
def sign_up(username: str, password: str, email: str = ""):
    username = username.strip().lower()
    email = email.strip().lower()
    if not username or not password:
        return False, "Fill in all fields."
    if " " in username:
        return False, "Username cannot contain spaces."
    if len(username) < 3:
        return False, "Username must be 3+ characters."
    if len(password) < 6:
        return False, "Password must be 6+ characters."
    try:
        existing = supabase.table("profiles").select("id").eq("username", username).execute()
        if existing.data:
            return False, "Username already taken."
        recovery = "-".join(pysecrets.token_hex(2).upper() for _ in range(3))
        recovery_hash = bcrypt.hashpw(recovery.encode(), bcrypt.gensalt()).decode()
        payload = {
            "username": username,
            "password_hash": hash_pwd(password),
            "recovery_hash": recovery_hash,
        }
        if email:
            payload["email"] = email
        result = supabase.table("profiles").insert(payload).execute()
        if result.data:
            return True, recovery
        return False, "Signup failed."
    except Exception as e:
        return False, f"Error: {e}"

def log_in(username: str, password: str):
    username = username.strip().lower()
    try:
        res = supabase.table("profiles").select("id, username, password_hash").eq("username", username).execute()
        if not res.data:
            return None
        user = res.data[0]
        if not user.get("password_hash"):
            return None
        if check_pwd(password, user["password_hash"]):
            return {"id": user["id"], "username": user["username"]}
        return None
    except Exception:
        return None

def reset_password(username: str, recovery_code: str, new_password: str):
    username = username.strip().lower()
    if len(new_password) < 6:
        return False, "Password must be 6+ characters."
    try:
        res = supabase.table("profiles").select("id, recovery_hash").eq("username", username).execute()
        if not res.data:
            return False, "Username not found."
        user = res.data[0]
        if not user.get("recovery_hash"):
            return False, "No recovery code set for this account."
        if not check_pwd(recovery_code.strip().upper(), user["recovery_hash"]):
            return False, "Invalid recovery code."
        supabase.table("profiles").update({
            "password_hash": hash_pwd(new_password)
        }).eq("id", user["id"]).execute()
        return True, "Password updated!"
    except Exception as e:
        return False, f"Error: {e}"

# --- AUTH GATE ---
if "user" not in st.session_state:
    st.session_state.user = None
if "is_guest" not in st.session_state:
    st.session_state.is_guest = False
if "show_reset" not in st.session_state:
    st.session_state.show_reset = False

# --- GUEST STATE ---
if "guest_messages" not in st.session_state:
    st.session_state.guest_messages = []
if "guest_thread_id" not in st.session_state:
    st.session_state.guest_thread_id = str(uuid.uuid4())

if st.session_state.user is None and not st.session_state.is_guest:
    st.markdown("### Welcome to CraftGPT")

    if not supabase:
        st.error("Supabase not configured. Check secrets.")
        st.stop()

    # --- FORGOT PASSWORD ---
    if st.session_state.show_reset:
        st.markdown("#### Reset Your Password")
        with st.form("reset_form"):
            r_user = st.text_input("Username")
            r_code = st.text_input("Recovery code", placeholder="XXXX-XXXX-XXXX")
            r_new1 = st.text_input("New password", type="password")
            r_new2 = st.text_input("Confirm new password", type="password")
            c1, c2 = st.columns(2)
            with c1:
                do_reset = st.form_submit_button("Reset Password", use_container_width=True)
            with c2:
                back = st.form_submit_button("← Back to Login", use_container_width=True)
            if do_reset:
                if r_new1 != r_new2:
                    st.error("Passwords don't match.")
                else:
                    ok, msg = reset_password(r_user, r_code, r_new1)
                    if ok:
                        st.success(msg + " You can now log in.")
                        st.session_state.show_reset = False
                    else:
                        st.error(msg)
            if back:
                st.session_state.show_reset = False
                st.rerun()
        st.stop()

    # --- LOGIN / SIGNUP ---
    tab_login, tab_signup = st.tabs(["Login", "Sign Up"])

    with tab_login:
        with st.form("login_form"):
            login_user = st.text_input("Username", placeholder="yourname")
            login_pwd = st.text_input("Password", type="password")
            if st.form_submit_button("Login", use_container_width=True):
                user = log_in(login_user, login_pwd)
                if user:
                    st.session_state.user = user
                    st.session_state.is_guest = False
                    st.session_state.guest_messages = []
                    st.session_state.active_session_id = None
                    st.rerun()
                else:
                    st.error("Invalid username or password.")

    with tab_signup:
        with st.form("signup_form"):
            new_user = st.text_input("Choose username", placeholder="yourname")
            new_email = st.text_input("Email (optional)", placeholder="you@example.com")
            new_pwd = st.text_input("Password (min 6 chars)", type="password")
            new_pwd2 = st.text_input("Confirm password", type="password")
            if st.form_submit_button("Create account", use_container_width=True):
                if new_pwd != new_pwd2:
                    st.error("Passwords don't match.")
                else:
                    ok, result = sign_up(new_user, new_pwd, new_email)
                    if ok:
                        st.success("Account created!")
                        st.warning(
                            f"### SAVE THIS RECOVERY CODE\n\n"
                            f"## `{result}`\n\n"
                            "**Write it down right now.** You'll need it if you forget your password. "
                            "It will **never** be shown again."
                        )
                        user = log_in(new_user, new_pwd)
                        if user:
                            st.session_state.user = user
                            st.session_state.is_guest = False
                            st.session_state.guest_messages = []
                            st.session_state.active_session_id = None
                            st.rerun()
                    else:
                        st.error(result)

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Forgot Password", use_container_width=True):
            st.session_state.show_reset = True
            st.rerun()
    with col_b:
        if st.button("Continue as Guest", use_container_width=True):
            st.session_state.is_guest = True
            st.session_state.user = None
            st.rerun()
    st.stop()

# --- AUTH SUCCESS PATH ---
is_guest = st.session_state.is_guest
user_id = st.session_state.user["id"] if st.session_state.user else None
user_name = st.session_state.user["username"] if st.session_state.user else "guest"

# --- DATABASE HELPERS ---
def load_sessions():
    if is_guest or not user_id: return []
    try:
        return supabase.table("chat_sessions").select("*").eq("user_id", user_id).order("created_at", desc=True).execute().data
    except Exception:
        return []

def create_session(name):
    if is_guest or not user_id: return None
    try:
        r = supabase.table("chat_sessions").insert({"session_name": name, "user_id": user_id}).execute()
        return r.data[0] if r.data else None
    except Exception:
        return None

def delete_session(sid):
    if is_guest or not user_id: return
    try:
        supabase.table("chat_messages").delete().eq("session_id", sid).eq("user_id", user_id).execute()
        supabase.table("chat_sessions").delete().eq("id", sid).eq("user_id", user_id).execute()
    except Exception:
        pass

def load_messages(sid):
    if is_guest or not user_id or not sid: return []
    try:
        return supabase.table("chat_messages").select("*").eq("session_id", sid).eq("user_id", user_id).order("created_at").execute().data
    except Exception:
        return []

def save_message(sid, role, content):
    if is_guest or not user_id or not sid: return
    try:
        supabase.table("chat_messages").insert({
            "session_id": sid, "user_id": user_id, "role": role, "content": content
        }).execute()
    except Exception:
        pass

def update_session_title(sid, new_title):
    if is_guest or not user_id or not sid:
        return
    try:
        supabase.table("chat_sessions").update(
            {"session_name": new_title}
        ).eq("id", sid).eq("user_id", user_id).execute()
    except Exception:
        pass

def generate_session_title(first_message: str) -> str:
    try:
        model = ChatOpenAI(
            model="openai/gpt-oss-20b",
            base_url="https://api.groq.com/openai/v1",
            api_key=GROQ_KEY,
            temperature=0.3,
        )
        resp = model.invoke(
            "Generate a concise 3-5 word title for this conversation. "
            "Return ONLY the title. No quotes, no trailing punctuation.\n\n"
            f"First user message: {first_message[:500]}"
        )
        title = resp.content.strip().strip('"').strip("'").rstrip(".")
        return title[:60] or first_message.strip()[:30] or "New Chat"
    except Exception:
        return first_message.strip()[:30] or "New Chat"

if "active_session_id" not in st.session_state:
    if is_guest:
        st.session_state.active_session_id = None
    else:
        sessions = load_sessions()
        if sessions:
            st.session_state.active_session_id = sessions[0]["id"]
        else:
            new = create_session("New Chat")
            st.session_state.active_session_id = new["id"] if new else None

# --- TOOL FUNCTIONS ---
def tavily_search(query):
    if not TAVILY_KEY: return "Search unavailable."
    try:
        r = requests.post("https://api.tavily.com/search", headers={"Authorization": f"Bearer {TAVILY_KEY}"},
            json={"query": query, "search_depth": "advanced", "max_results": 5, "include_answer": True}, timeout=15)
        r.raise_for_status(); data = r.json(); out = []
        if data.get("answer"): out.append(f"**Answer:** {data['answer']}\n")
        for i, x in enumerate(data.get("results", [])[:5], 1):
            out.append(f"{i}. **{x.get('title','')}**\n   {x.get('content','')[:300]}...\n   Source: {x.get('url','')}\n")
        return "\n".join(out) or "No results."
    except Exception as e: return f"Search failed: {e}"

def firecrawl_search(query):
    if not FIRECRAWL_KEY: return "Firecrawl unavailable."
    try:
        r = requests.post("https://api.firecrawl.dev/v1/search", headers={"Authorization": f"Bearer {FIRECRAWL_KEY}"},
            json={"query": query, "limit": 5}, timeout=20); r.raise_for_status()
        data = r.json(); out = []
        for i, x in enumerate(data.get("data", [])[:5], 1):
            out.append(f"{i}. **{x.get('title','')}**\n   {(x.get('description') or x.get('markdown',''))[:300]}...\n   Source: {x.get('url','')}\n")
        return "\n".join(out) or "No results."
    except Exception as e: return f"Firecrawl failed: {e}"

def get_astronomy(location="Islamabad,PK"):
    if not IPGEO_KEY: return "Astronomy unavailable."
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        r = requests.get("https://api.ipgeolocation.io/v3/astronomy",
            params={"apiKey": IPGEO_KEY, "location": location, "date": today}, timeout=15); r.raise_for_status()
        data = r.json(); astro = data.get("astronomy", {}); sun, moon = astro.get("sun", {}), astro.get("moon", {}); out = []
        for k, l in [("sunrise","Sunrise"),("sunset","Sunset"),("solar_noon","Solar Noon"),("day_length","Day Length")]:
            if sun.get(k): out.append(f"{l}: {sun[k]}")
        for k, l in [("moonrise","Moonrise"),("moonset","Moonset"),("phase","Moon Phase")]:
            if moon.get(k): out.append(f"{l}: {moon[k]}")
        return "\n".join(out) or "No astronomy data."
    except Exception as e: return f"Astronomy failed: {e}"

def get_planet_riseset(planet_name):
    try:
        observer = Observer(33.6844, 73.0479, 0)
        pmap = {"mercury": Body.Mercury, "venus": Body.Venus, "mars": Body.Mars, "jupiter": Body.Jupiter, "saturn": Body.Saturn}
        key = planet_name.lower()
        if key not in pmap: return f"Planet '{planet_name}' not supported."
        body = pmap[key]; now = datetime.utcnow()
        rise = SearchRiseSet(body, observer, Direction.Rise, now, 1); set_t = SearchRiseSet(body, observer, Direction.Set, now, 1)
        out = [f"**{planet_name.capitalize()} rise/set for Islamabad ({now.strftime('%Y-%m-%d')} UTC):**"]
        if rise: out.append(f"• Rise: {rise.utc_strftime('%H:%M')} UTC")
        if set_t: out.append(f"• Set: {set_t.utc_strftime('%H:%M')} UTC")
        return "\n".join(out) if (rise or set_t) else f"No rise/set for {planet_name}."
    except Exception as e: return f"Planet failed: {e}"

# --- CODE EXECUTION TOOL ---
@tool
def run_python(code: str) -> str:
    """Execute Python code in a restricted subprocess and return stdout/stderr."""
    import tempfile
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            temp_file = f.name
        result = subprocess.run([sys.executable, temp_file], capture_output=True, text=True, timeout=20)
        return f"Success:\n{result.stdout}" if result.returncode == 0 else f"Error:\n{result.stderr}"
    except subprocess.TimeoutExpired:
        return "Execution timed out after 20 seconds."
    except Exception as e:
        return f"Execution failed: {e}"
    finally:
        if temp_file and os.path.exists(temp_file):
            try: os.unlink(temp_file)
            except Exception: pass

# --- FILE SYSTEM TOOLS ---
@tool
def read_file(path: str) -> str:
    """Read a file's contents from the agent workspace."""
    safe_path = os.path.join(WORKSPACE, os.path.basename(path))
    try:
        with open(safe_path, 'r') as f: return f.read()
    except FileNotFoundError: return f"File not found: {path}"
    except Exception as e: return f"Error reading file: {e}"

@tool
def write_file(path: str, content: str) -> str:
    """Write content to a file in the agent workspace."""
    safe_path = os.path.join(WORKSPACE, os.path.basename(path))
    try:
        with open(safe_path, 'w') as f: f.write(content)
        return f"Successfully wrote {len(content)} chars to {path}"
    except Exception as e: return f"Error writing file: {e}"

@tool
def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Replace old_text with new_text in a file."""
    safe_path = os.path.join(WORKSPACE, os.path.basename(path))
    try:
        with open(safe_path, 'r') as f: content = f.read()
        if old_text not in content: return f"Error: text not found in {path}"
        with open(safe_path, 'w') as f: f.write(content.replace(old_text, new_text, 1))
        return f"Successfully edited {path}"
    except FileNotFoundError: return f"File not found: {path}"
    except Exception as e: return f"Error editing file: {e}"

@tool
def list_files() -> str:
    """List all files in the agent workspace."""
    try:
        files = os.listdir(WORKSPACE)
        return "\n".join(files) if files else "Workspace is empty."
    except Exception as e: return f"Error listing files: {e}"

# --- WRAP AS LANGCHAIN TOOLS ---
@tool
def internet_search(query: str) -> str:
    """Search the web for current information, news, or facts."""
    return tavily_search(query)

@tool
def deep_scrape(query: str) -> str:
    """Deep-scrape web pages for detailed content using Firecrawl."""
    return firecrawl_search(query)

@tool
def astronomy_data(location: str = "Islamabad") -> str:
    """Get sun and moon rise/set times for a location."""
    return get_astronomy(location)

@tool
def planet_riseset(planet: str) -> str:
    """Calculate planet rise/set times for Islamabad."""
    return get_planet_riseset(planet)

# --- SUB-AGENT ---
def create_research_subagent():
    try:
        sub_model = ChatOpenAI(
            model="openai/gpt-oss-20b",
            base_url="https://api.groq.com/openai/v1",
            api_key=GROQ_KEY,
            temperature=0.1,
        )
        return create_react_agent(sub_model, [internet_search, deep_scrape])
    except Exception:
        return None

@tool
def delegate_research(query: str) -> str:
    """Delegate a research task to a specialized sub-agent."""
    subagent = create_research_subagent()
    if not subagent: return "Research sub-agent unavailable."
    try:
        result = subagent.invoke({"messages": [{"role": "user", "content": query}]})
        return result["messages"][-1].content
    except Exception as e: return f"Research delegation failed: {e}"

agent_tools = [internet_search, deep_scrape, astronomy_data, planet_riseset,
               run_python, read_file, write_file, edit_file, list_files, delegate_research]

# --- AGENT BUILDER ---
FALLBACK_CHAIN = [
    ("groq",       "openai/gpt-oss-120b"),
    ("groq",       "openai/gpt-oss-20b"),
    ("openrouter", "inclusionai/ling-3.0-flash-vl:free"),
]

def _make_model(provider, model_id):
    if provider == "groq":
        if not GROQ_KEY:
            raise RuntimeError("GROQ_API_KEY missing in secrets.")
        return ChatOpenAI(model=model_id, base_url="https://api.groq.com/openai/v1",
                          api_key=GROQ_KEY, temperature=0.1)
    if provider == "openrouter":
        if not OPENROUTER_KEY:
            raise RuntimeError("OPENROUTER_API_KEY missing in secrets.")
        return ChatOpenAI(model=model_id, base_url="https://openrouter.ai/api/v1",
                          api_key=OPENROUTER_KEY, temperature=0.1)
    raise RuntimeError(f"Unknown provider: {provider}")

def build_agent(model_id, provider):
    attempts = [(provider, model_id)] + [x for x in FALLBACK_CHAIN if x != (provider, model_id)]
    last_err = None
    for prov, mid in attempts:
        try:
            model = _make_model(prov, mid)
            agent = create_react_agent(model, agent_tools, checkpointer=checkpointer)
            if (prov, mid) != (provider, model_id):
                st.info(f"Fallback in use: **{mid}** ({prov})")
            return agent
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"All models failed. Last error: {last_err}")

# --- SIDEBAR ---
with st.sidebar:
    # User chip at top
    if is_guest:
        st.markdown(
            f"<div style='padding:10px 12px;border-radius:10px;"
            f"background:#141414;border:1px solid #1f1f1f;color:#aaa;"
            f"font-size:13px;'>👤 Guest Mode</div>",
            unsafe_allow_html=True,
        )
        if st.button("Log in / Sign up", use_container_width=True):
            st.session_state.user = None
            st.session_state.is_guest = False
            st.session_state.active_session_id = None
            st.rerun()
    else:
        st.markdown(
            f"<div style='padding:10px 12px;border-radius:10px;"
            f"background:#141414;border:1px solid #1f1f1f;color:#E3E3E3;"
            f"font-size:13px;'>👤 {user_name}</div>",
            unsafe_allow_html=True,
        )
        if st.button("Log out", use_container_width=True):
            st.session_state.user = None
            st.session_state.is_guest = False
            st.session_state.active_session_id = None
            st.rerun()

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    # --- New Chat (Meta AI-style row) ---
    if not is_guest:
        if st.button("✎  New chat", use_container_width=True):
            new = create_session("New Chat")
            if new: st.session_state.active_session_id = new["id"]
            st.rerun()

        # --- History label ---
        st.markdown("<div class='sidebar-label'>History</div>", unsafe_allow_html=True)

        # --- Flat history list ---
        sessions = load_sessions()
        for s in sessions:
            is_active = s["id"] == st.session_state.active_session_id
            # Active gets a subtle highlight; inactive is plain
            label = s["session_name"] if not is_active else f"● {s['session_name']}"
            if st.button(label, key=f"sel_{s['id']}", use_container_width=True):
                st.session_state.active_session_id = s["id"]
                st.rerun()

        # --- Delete for active session (moved to bottom, quieter) ---
        if len(sessions) > 1:
            with st.expander("Manage sessions"):
                for s in sessions:
                    cols = st.columns([4, 1])
                    with cols[0]:
                        st.caption(s["session_name"])
                    with cols[1]:
                        if st.button("🗑", key=f"del2_{s['id']}"):
                            delete_session(s["id"])
                            remaining = [x for x in load_sessions() if x["id"] != s["id"]]
                            if remaining:
                                st.session_state.active_session_id = remaining[0]["id"]
                            st.rerun()
    else:
        st.markdown("<div class='sidebar-label'>Guest Chat</div>", unsafe_allow_html=True)
        if st.button("Clear chat", use_container_width=True):
            st.session_state.guest_messages = []
            st.session_state.guest_thread_id = str(uuid.uuid4())
            st.rerun()

    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

    # --- Model picker ---
    st.markdown("<div class='sidebar-label'>Model</div>", unsafe_allow_html=True)
    model_mapping = {
        "GPT-OSS 120B (Fast, Free)":    {"id": "openai/gpt-oss-120b",              "provider": "groq"},
        "GPT-OSS 20B (Fastest, Free)":  {"id": "openai/gpt-oss-20b",                 "provider": "groq"},
        "Ling 3.0 Flash VL (Vision)":   {"id": "inclusionai/ling-3.0-flash-vl:free",   "provider": "openrouter"},
        "North Mini Code (Free)":       {"id": "cohere/north-mini-code:free",         "provider": "openrouter"},
    }
    selected_model_name = st.selectbox("Choose Agent Brain:", options=list(model_mapping.keys()), index=0, label_visibility="collapsed")
    selected_model_id = model_mapping[selected_model_name]["id"]

    st.markdown("<div class='sidebar-label'>Media</div>", unsafe_allow_html=True)
    uploaded_file = st.file_uploader("Snapshot your worksheet:", type=["jpg", "jpeg", "png"],
        key=f"homework_file_{st.session_state.uploader_key}", label_visibility="collapsed")

# --- TOP-RIGHT MODEL BADGE (Meta AI vibe) ---
st.markdown(
    f"<div class='model-badge'>{selected_model_name.split(' (')[0]}</div>",
    unsafe_allow_html=True,
)

# --- RENDER CHAT HISTORY ---
if is_guest:
    for i, msg in enumerate(st.session_state.guest_messages):
        avatar = SPARKLE_AVATAR if msg["role"] == "assistant" else "👤"
        with st.chat_message(msg["role"], avatar=avatar):
            st.write(msg["content"])
            if msg["role"] == "assistant":
                st.download_button("Download", data=msg["content"], file_name="solution.md",
                    mime="text/markdown", key=f"dl_guest_{i}")
elif st.session_state.active_session_id:
    for msg in load_messages(st.session_state.active_session_id):
        avatar = SPARKLE_AVATAR if msg["role"] == "assistant" else "👤"
        with st.chat_message(msg["role"], avatar=avatar):
            st.write(msg["content"])
            if msg["role"] == "assistant":
                st.download_button("Download", data=msg["content"], file_name="solution.md",
                    mime="text/markdown", key=f"dl_{msg['id']}")

# --- IMAGE PROCESSING ---
img_base64 = None
if uploaded_file:
    image = Image.open(uploaded_file); st.image(image, use_container_width=True)
    buf = io.BytesIO(); image.save(buf, format="JPEG"); img_base64 = base64.b64encode(buf.getvalue()).decode()

# --- AGENT CHAT ---
if prompt := st.chat_input("Ask CraftGPT..."):
    if is_guest:
        st.session_state.guest_messages.append({"role": "user", "content": prompt})
    elif st.session_state.active_session_id:
        save_message(st.session_state.active_session_id, "user", prompt)

        prior = load_messages(st.session_state.active_session_id)
        if len(prior) == 1:
            new_title = generate_session_title(prompt)
            update_session_title(st.session_state.active_session_id, new_title)

    with st.chat_message("user", avatar="👤"):
        st.write(prompt)
    with st.chat_message("assistant", avatar=SPARKLE_AVATAR):
        if not (GROQ_KEY or OPENROUTER_KEY):
            st.error("No API key configured. Add GROQ_API_KEY or OPENROUTER_API_KEY to secrets.")
        else:
            provider = model_mapping[selected_model_name]["provider"]
            try:
                agent = build_agent(selected_model_id, provider)
            except Exception as e:
                st.error(f"Could not initialize agent: {e}")
                st.stop()
            handler = StreamlitLanggraphHandler(container=st.container(),
                expand_new_thoughts=True, show_tool_calls=True, show_tool_results=True)
            vision_models = ["inclusionai/ling-3.0-flash-vl:free"]
            if img_base64 and selected_model_id not in vision_models:
                st.warning("This model is text-only. Switch to Ling 3.0 Flash VL to analyze images.")
            try:
                if img_base64:
                    user_message = {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
                    ]}
                else:
                    user_message = {"role": "user", "content": prompt}

                if is_guest:
                    thread_key = f"guest-{st.session_state.guest_thread_id}"
                else:
                    thread_key = f"{user_id}-{st.session_state.active_session_id}"

                response = handler.invoke(agent=agent, input={"messages": [user_message]},
                    config={"configurable": {"thread_id": thread_key}})
                st.write(response)

                if is_guest:
                    st.session_state.guest_messages.append({"role": "assistant", "content": response})
                elif st.session_state.active_session_id:
                    save_message(st.session_state.active_session_id, "assistant", response)

                if img_base64: st.session_state.uploader_key += 1
                st.rerun()
            except Exception as exc:
                st.error(f"Agent error: {exc}")