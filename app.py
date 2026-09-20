import os
import io
import base64
import subprocess
import sys
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
st.markdown("""
    <style>
        .stApp { background-color: #131314 !important; color: #E3E3E3 !important; }
        h1 { background: linear-gradient(45deg, #4285F4, #9B51E0); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 800 !important; }
    </style>
""", unsafe_allow_html=True)
st.title("🚀 CraftGPT Agent")
st.caption("Autonomous Homework Agent | Tier 3 Codex-Style")

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

# --- AUTH HELPERS ---
def username_to_email(username: str) -> str:
    return f"{username.strip().lower()}@craftgpt.local"

# --- AUTH GATE ---
if "user" not in st.session_state:
    st.session_state.user = None
if "is_guest" not in st.session_state:
    st.session_state.is_guest = False

if st.session_state.user is None and not st.session_state.is_guest:
    st.markdown("### 🔐 Welcome to CraftGPT")

    if not supabase:
        st.error("❌ Supabase not configured. Check secrets.")
        st.stop()

    tab_login, tab_signup = st.tabs(["🔐 Login", "📝 Sign Up"])

    with tab_login:
        with st.form("login_form"):
            login_user = st.text_input("Username", placeholder="yourname")
            login_pwd = st.text_input("Password", type="password")
            if st.form_submit_button("Login", use_container_width=True):
                if not login_user or not login_pwd:
                    st.error("Enter both username and password.")
                else:
                    try:
                        res = supabase.auth.sign_in_with_password({
                            "email": username_to_email(login_user),
                            "password": login_pwd,
                        })
                        if res.user:
                            st.session_state.user = res.user
                            st.session_state.is_guest = False
                            st.rerun()
                        else:
                            st.error("❌ Invalid username or password.")
                    except Exception:
                        st.error("❌ Invalid username or password.")

    with tab_signup:
        with st.form("signup_form"):
            new_user = st.text_input("Choose username", placeholder="yourname")
            new_pwd = st.text_input("Password (min 6 chars)", type="password")
            new_pwd2 = st.text_input("Confirm password", type="password")
            if st.form_submit_button("Create account", use_container_width=True):
                if not new_user or not new_pwd:
                    st.error("Fill in both fields.")
                elif new_pwd != new_pwd2:
                    st.error("❌ Passwords don't match.")
                elif len(new_pwd) < 6:
                    st.error("❌ Password must be 6+ characters.")
                else:
                    try:
                        res = supabase.auth.sign_up({
                            "email": username_to_email(new_user),
                            "password": new_pwd,
                        })
                        if res.user:
                            # Insert profile row using the newly-authenticated session
                            try:
                                supabase.table("profiles").insert({
                                    "id": res.user.id,
                                    "username": new_user.strip().lower(),
                                }).execute()
                            except Exception as e:
                                st.warning(f"Profile row: {e}")
                            st.success("✅ Account created! Switch to Login tab and sign in.")
                        else:
                            st.error("❌ Sign up failed.")
                    except Exception as e:
                        st.error(f"❌ {e}")

    st.divider()
    if st.button("👤 Continue as Guest", use_container_width=True):
        st.session_state.is_guest = True
        st.session_state.user = None
        st.rerun()
    st.stop()

# --- AUTH SUCCESS PATH ---
is_guest = st.session_state.is_guest
user_id = st.session_state.user.id if st.session_state.user else None
user_name = "guest"
if not is_guest and user_id:
    try:
        prof = supabase.table("profiles").select("username").eq("id", user_id).execute()
        if prof.data:
            user_name = prof.data[0]["username"]
    except Exception:
        user_name = "user"

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

if "active_session_id" not in st.session_state:
    if is_guest:
        st.session_state.active_session_id = None
    else:
        sessions = load_sessions()
        if sessions:
            st.session_state.active_session_id = sessions[0]["id"]
        else:
            new = create_session("Chat 1")
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
        for k, l in [("sunrise","☀️ Sunrise"),("sunset","🌇 Sunset"),("solar_noon","🕛 Solar Noon"),("day_length","⏱️ Day Length")]:
            if sun.get(k): out.append(f"{l}: {sun[k]}")
        for k, l in [("moonrise","🌙 Moonrise"),("moonset","🌙 Moonset"),("phase","🌒 Moon Phase")]:
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
        return f"✅ Success:\n{result.stdout}" if result.returncode == 0 else f"❌ Error:\n{result.stderr}"
    except subprocess.TimeoutExpired:
        return "⏱️ Execution timed out after 20 seconds."
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
        return f"✅ Successfully wrote {len(content)} chars to {path}"
    except Exception as e: return f"Error writing file: {e}"

@tool
def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Replace old_text with new_text in a file."""
    safe_path = os.path.join(WORKSPACE, os.path.basename(path))
    try:
        with open(safe_path, 'r') as f: content = f.read()
        if old_text not in content: return f"❌ Error: text not found in {path}"
        with open(safe_path, 'w') as f: f.write(content.replace(old_text, new_text, 1))
        return f"✅ Successfully edited {path}"
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
            model="llama-3.1-8b-instant",
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
    ("groq",       "llama-3.3-70b-versatile"),
    ("groq",       "llama-3.1-8b-instant"),
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
                st.info(f"⚠️ Fallback in use: **{mid}** ({prov})")
            return agent
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"All models failed. Last error: {last_err}")

# --- SIDEBAR ---
with st.sidebar:
    if is_guest:
        st.info("👤 **Guest Mode**")
        if st.button("🔐 Log in / Sign up", use_container_width=True):
            st.session_state.user = None
            st.session_state.is_guest = False
            st.session_state.active_session_id = None
            st.rerun()
    else:
        st.success(f"👤 {user_name}")
        if st.button("🚪 Log out", use_container_width=True):
            try: supabase.auth.sign_out()
            except Exception: pass
            st.session_state.user = None
            st.session_state.is_guest = False
            st.session_state.active_session_id = None
            st.rerun()
    st.divider()

    if not is_guest:
        st.header("💬 Chat Sessions")
        if st.button("➕ New Chat", use_container_width=True):
            sessions = load_sessions(); existing = [s["session_name"] for s in sessions]; i = 1
            while f"Chat {i}" in existing: i += 1
            new = create_session(f"Chat {i}")
            if new: st.session_state.active_session_id = new["id"]
            st.rerun()
        for s in load_sessions():
            col1, col2 = st.columns([4, 1])
            with col1:
                is_active = s["id"] == st.session_state.active_session_id
                label = f"🟢 {s['session_name']}" if is_active else f"⚪ {s['session_name']}"
                if st.button(label, key=f"sel_{s['id']}", use_container_width=True):
                    st.session_state.active_session_id = s["id"]; st.rerun()
            with col2:
                if len(load_sessions()) > 1 and st.button("🗑️", key=f"del_{s['id']}"):
                    delete_session(s["id"]); remaining = [x for x in load_sessions() if x["id"] != s["id"]]
                    if remaining: st.session_state.active_session_id = remaining[0]["id"]
                    st.rerun()
        st.divider()

    st.header("⚙️ Configuration")
    model_mapping = {
        "⚡ Groq Llama 3.3 70B (Fast + Free)":    {"id": "llama-3.3-70b-versatile",              "provider": "groq"},
        "💨 Groq Llama 3.1 8B (Fastest + Free)":  {"id": "llama-3.1-8b-instant",                 "provider": "groq"},
        "🖼️ Ling 3.0 Flash VL (Vision, Free)":    {"id": "inclusionai/ling-3.0-flash-vl:free",   "provider": "openrouter"},
        "🚀 Gemma 2 9B (Free)":                    {"id": "google/gemma-2-9b-it:free",            "provider": "openrouter"},
    }
    selected_model_name = st.selectbox("Choose Agent Brain:", options=list(model_mapping.keys()), index=0)
    selected_model_id = model_mapping[selected_model_name]["id"]
    st.header("📸 Media input panel")
    uploaded_file = st.file_uploader("Snapshot your worksheet/page:", type=["jpg", "jpeg", "png"],
        key=f"homework_file_{st.session_state.uploader_key}")

# --- RENDER CHAT HISTORY ---
if not is_guest and st.session_state.active_session_id:
    for msg in load_messages(st.session_state.active_session_id):
        with st.chat_message(msg["role"], avatar=msg["role"]):
            st.write(msg["content"])
            if msg["role"] == "assistant":
                st.download_button("📥 Download", data=msg["content"], file_name="solution.md",
                    mime="text/markdown", key=f"dl_{msg['id']}")

# --- IMAGE PROCESSING ---
img_base64 = None
if uploaded_file:
    image = Image.open(uploaded_file); st.image(image, use_container_width=True)
    buf = io.BytesIO(); image.save(buf, format="JPEG"); img_base64 = base64.b64encode(buf.getvalue()).decode()

# --- AGENT CHAT ---
if prompt := st.chat_input("Ask CraftGPT..."):
    if not is_guest and st.session_state.active_session_id:
        save_message(st.session_state.active_session_id, "user", prompt)
    with st.chat_message("user", avatar="user"):
        st.write(prompt)
    with st.chat_message("assistant", avatar="assistant"):
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
                st.warning("⚠️ This model is text-only. Switch to **Ling 3.0 Flash VL** to analyze images.")
            try:
                if img_base64:
                    user_message = {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
                    ]}
                else:
                    user_message = {"role": "user", "content": prompt}
                thread_key = f"{user_id or 'guest'}-{st.session_state.active_session_id or 'guest'}"
                response = handler.invoke(agent=agent, input={"messages": [user_message]},
                    config={"configurable": {"thread_id": thread_key}})
                st.write(response)
                if not is_guest and st.session_state.active_session_id:
                    save_message(st.session_state.active_session_id, "assistant", response)
                if img_base64: st.session_state.uploader_key += 1
                st.rerun()
            except Exception as exc:
                st.error(f"Agent error: {exc}")