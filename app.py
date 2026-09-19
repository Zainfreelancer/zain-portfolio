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

# Agent imports
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
GROQ_KEY = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
CEREBRAS_KEY = st.secrets.get("CEREBRAS_API_KEY") or os.getenv("CEREBRAS_API_KEY")
TAVILY_KEY = st.secrets.get("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY")
FIRECRAWL_KEY = st.secrets.get("FIRECRAWL_API_KEY") or os.getenv("FIRECRAWL_API_KEY")
IPGEO_KEY = st.secrets.get("IPGEOLOCATION_API_KEY") or os.getenv("IPGEOLOCATION_API_KEY")
SUPABASE_URL = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
SUPABASE_DB_URL = st.secrets.get("SUPABASE_DB_URL") or os.getenv("SUPABASE_DB_URL")
APP_URL = st.secrets.get("APP_URL", "https://your-app.streamlit.app")

# --- WORKSPACE DIRECTORY ---
WORKSPACE = "agent_workspace"
os.makedirs(WORKSPACE, exist_ok=True)

# --- PERSISTENT CHECKPOINTER (Postgres-backed, survives reboots) ---
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
        checkpointer.setup()  # Creates the checkpoint tables automatically
        return checkpointer
    except Exception as e:
        st.error(f"Checkpointer failed to initialize: {e}")
        return None

checkpointer = get_checkpointer()

# --- SUPABASE CLIENT (for auth + chat history) ---
@st.cache_resource
def init_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    return create_client(SUPABASE_URL, SUPABASE_KEY)
supabase = init_supabase()

# --- AUTH GATE ---
if "user" not in st.session_state:
    st.session_state.user = None
if st.session_state.user is None and supabase:
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.user = session.user
    except Exception:
        pass

if st.session_state.user is None:
    st.markdown("### 🔐 Welcome to CraftGPT")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🐙 Sign in with GitHub", use_container_width=True):
            try:
                res = supabase.auth.sign_in_with_oauth({"provider": "github", "options": {"redirect_to": APP_URL}})
                st.markdown(f'<meta http-equiv="refresh" content="0; url={res.url}">', unsafe_allow_html=True)
            except Exception as e:
                st.error(f"GitHub login failed: {e}")
    with col2:
        st.markdown("**Or use email:**")
    with st.form("magic_link_form"):
        email = st.text_input("📧 Gmail address:", placeholder="yourname@gmail.com")
        if st.form_submit_button("✉️ Send Magic Link", use_container_width=True):
            if not email.lower().endswith("@gmail.com"):
                st.error("❌ Only Gmail addresses are allowed.")
            else:
                try:
                    supabase.auth.sign_in_with_otp({"email": email, "options": {"email_redirect_to": APP_URL}})
                    st.success(f"✅ Magic link sent to **{email}**.")
                except Exception as e:
                    st.error(f"Failed to send link: {e}")
    st.divider()
    if st.button("👤 Continue as Guest", use_container_width=True):
        try:
            guest = supabase.auth.sign_in_anonymously()
            st.session_state.user = guest.user
            st.rerun()
        except Exception as e:
            st.error(f"Guest login failed: {e}")
    st.stop()

user_id = st.session_state.user.id
user_email = getattr(st.session_state.user, "email", None)
is_guest = user_email is None or getattr(st.session_state.user, "is_anonymous", False)

# --- DATABASE HELPERS ---
def load_sessions():
    if not supabase: return []
    try: return supabase.table("chat_sessions").select("*").eq("user_id", user_id).order("created_at", desc=True).execute().data
    except Exception: return []
def create_session(name):
    if not supabase: return None
    try:
        r = supabase.table("chat_sessions").insert({"session_name": name, "user_id": user_id}).execute()
        return r.data[0] if r.data else None
    except Exception: return None
def delete_session(sid):
    if supabase:
        supabase.table("chat_sessions").delete().eq("id", sid).eq("user_id", user_id).execute()
def load_messages(sid):
    if not supabase: return []
    try: return supabase.table("chat_messages").select("*").eq("session_id", sid).eq("user_id", user_id).order("created_at").execute().data
    except Exception: return []
def save_message(sid, role, content):
    if supabase: supabase.table("chat_messages").insert({"session_id": sid, "user_id": user_id, "role": role, "content": content}).execute()
def delete_all_guest_data():
    if supabase and user_id:
        try:
            supabase.table("chat_messages").delete().eq("user_id", user_id).execute()
            supabase.table("chat_sessions").delete().eq("user_id", user_id).execute()
        except Exception: pass

if "active_session_id" not in st.session_state:
    sessions = load_sessions()
    if sessions: st.session_state.active_session_id = sessions[0]["id"]
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
        sub_model = ChatOpenAI(model="inclusionai/ling-3.0-flash-vl:free",
            base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_KEY, temperature=0.1)
        return create_react_agent(sub_model, [internet_search, deep_scrape])
    except Exception: return None

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
def build_agent(model_id, provider):
    if provider == "cerebras":
        model = ChatOpenAI(model=model_id, base_url="https://api.cerebras.ai/v1", api_key=CEREBRAS_KEY, temperature=0.1)
    elif provider == "groq":
        model = ChatOpenAI(model=model_id, base_url="https://api.groq.com/openai/v1", api_key=GROQ_KEY, temperature=0.1)
    else:
        model = ChatOpenAI(model=model_id, base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_KEY, temperature=0.1)
    return create_react_agent(model, agent_tools, checkpointer=checkpointer)

# --- SIDEBAR ---
with st.sidebar:
    if is_guest:
        st.info("👤 **Guest Mode**")
        if st.button("🔐 Sign in to save chats", use_container_width=True):
            delete_all_guest_data()
            try: supabase.auth.sign_out()
            except Exception: pass
            st.session_state.user = None; st.session_state.active_session_id = None; st.rerun()
    else:
        st.success(f"👤 {user_email}")
        if st.button("🚪 Log out", use_container_width=True):
            try: supabase.auth.sign_out()
            except Exception: pass
            st.session_state.user = None; st.session_state.active_session_id = None; st.rerun()
    st.divider()
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
        "🖼️ Ling 3.0 Flash VL (Vision + Agent)": {"id": "inclusionai/ling-3.0-flash-vl:free", "provider": "openrouter"},
        "🚀 Gemma 4 31B (Vision + Agent)": {"id": "google/gemma-4-31b-it:free", "provider": "openrouter"},
        "🧠 Nemotron 3 Super (Deep Reasoning)": {"id": "nvidia/nemotron-3-super-120b-a12b:free", "provider": "openrouter"},
        "💻 North Mini Code (Agentic Coding)": {"id": "cohere/north-mini-code:free", "provider": "openrouter"},
        "⚡ Cerebras GPT OSS 120B (Fast Agent)": {"id": "gpt-oss-120b", "provider": "cerebras"},
    }
    selected_model_name = st.selectbox("Choose Agent Brain:", options=list(model_mapping.keys()), index=0)
    selected_model_id = model_mapping[selected_model_name]["id"]
    st.header("📸 Media input panel")
    uploaded_file = st.file_uploader("Snapshot your worksheet/page:", type=["jpg", "jpeg", "png"],
        key=f"homework_file_{st.session_state.uploader_key}")

# --- RENDER CHAT HISTORY ---
if st.session_state.active_session_id:
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
    save_message(st.session_state.active_session_id, "user", prompt)
    with st.chat_message("user", avatar="user"):
        st.write(prompt)
    with st.chat_message("assistant", avatar="assistant"):
        if not OPENROUTER_KEY:
            st.error("No OpenRouter API key configured.")
        else:
            provider = model_mapping[selected_model_name]["provider"]
            agent = build_agent(selected_model_id, provider)
            handler = StreamlitLanggraphHandler(container=st.container(),
                expand_new_thoughts=True, show_tool_calls=True, show_tool_results=True)
            vision_models = ["inclusionai/ling-3.0-flash-vl:free"]
            if img_base64 and selected_model_id not in vision_models:
                st.warning("⚠️ The selected model is text-only. Switch to **Ling 3.0 Flash VL** to analyze images.")
            try:
                if img_base64:
                    user_message = {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
                    ]}
                else:
                    user_message = {"role": "user", "content": prompt}
                response = handler.invoke(agent=agent, input={"messages": [user_message]},
                    config={"configurable": {"thread_id": str(st.session_state.active_session_id)}})
                st.write(response)
                save_message(st.session_state.active_session_id, "assistant", response)
                if img_base64: st.session_state.uploader_key += 1
                st.rerun()
            except Exception as exc:
                st.error(f"Agent error: {exc}")