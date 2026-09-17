import os
import io
import base64
from datetime import datetime

import streamlit as st
from PIL import Image
from openai import OpenAI
import requests
from supabase import create_client, Client

# 1. Set browser tab layout parameters cleanly
st.set_page_config(page_title="CraftGPT App", page_icon="🚀", layout="centered")

# 💎 PREMIUM STYLING INJECTION
st.markdown("""
    <style>
        .stApp { background-color: #131314 !important; color: #E3E3E3 !important; }
        h1 { background: linear-gradient(45deg, #4285F4, #9B51E0); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-weight: 800 !important; }
        .stFileUploader { background-color: #1E1F20; border-radius: 12px; padding: 10px; border: 1px solid #444746; }
        div[data-testid="stChatMessage"] { border-radius: 16px; padding: 15px; margin-bottom: 10px; }
    </style>
""", unsafe_allow_html=True)

st.title("🚀 CraftGPT")
st.caption("Universal Multimodal Homework Assistant | Powered by OpenRouter & Groq")

# --- API KEY MANAGEMENT ---
GLOBAL_OPENROUTER_KEY = st.secrets.get("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY")
GLOBAL_GROQ_KEY = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = st.secrets.get("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY")
FIRECRAWL_API_KEY = st.secrets.get("FIRECRAWL_API_KEY") or os.getenv("FIRECRAWL_API_KEY")
IPGEOLOCATION_API_KEY = st.secrets.get("IPGEOLOCATION_API_KEY") or os.getenv("IPGEOLOCATION_API_KEY")
SUPABASE_URL = st.secrets.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
SUPABASE_KEY = st.secrets.get("SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
APP_URL = st.secrets.get("APP_URL") or "https://zain-portfolio-gpd9mlwggjcq75c85qkx9.streamlit.app"

# --- SUPABASE CLIENT ---
@st.cache_resource
def init_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# --- AUTHENTICATION GATE ---
if "user" not in st.session_state:
    st.session_state.user = None

# Try to restore session from Supabase (after magic link / GitHub redirect)
if st.session_state.user is None and supabase:
    try:
        session = supabase.auth.get_session()
        if session and session.user:
            st.session_state.user = session.user
    except Exception:
        pass

# Login screen if not authenticated
if st.session_state.user is None:
    st.markdown("### 🔐 Welcome to CraftGPT")
    st.markdown("Please sign in to continue:")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("🐙 Sign in with GitHub", use_container_width=True):
            try:
                res = supabase.auth.sign_in_with_oauth({
                    "provider": "github",
                    "options": {"redirect_to": APP_URL}
                })
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
                    supabase.auth.sign_in_with_otp({
                        "email": email,
                        "options": {"email_redirect_to": APP_URL}
                    })
                    st.success(f"✅ Magic link sent to **{email}**. Check your inbox.")
                    st.info("After clicking the link, come back here.")
                except Exception as e:
                    st.error(f"Failed to send link: {e}")
    
    st.stop()

# --- LOGGED IN ---
user_id = st.session_state.user.id
user_email = st.session_state.user.email

# --- DATABASE HELPERS (per-user) ---
def load_sessions():
    if not supabase: return []
    try:
        response = supabase.table("chat_sessions").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        return response.data
    except Exception as e:
        st.error(f"Failed to load sessions: {e}")
        return []

def create_session(name: str):
    if not supabase: return None
    try:
        response = supabase.table("chat_sessions").insert({"session_name": name, "user_id": user_id}).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        st.error(f"Failed to create session: {e}")
        return None

def delete_session(session_id: int):
    if not supabase: return
    try:
        supabase.table("chat_sessions").delete().eq("id", session_id).eq("user_id", user_id).execute()
    except Exception as e:
        st.error(f"Failed to delete session: {e}")

def load_messages(session_id: int):
    if not supabase: return []
    try:
        response = supabase.table("chat_messages").select("*").eq("session_id", session_id).eq("user_id", user_id).order("created_at").execute()
        return response.data
    except Exception as e:
        st.error(f"Failed to load messages: {e}")
        return []

def save_message(session_id: int, role: str, content: str):
    if not supabase: return
    try:
        supabase.table("chat_messages").insert({
            "session_id": session_id, "user_id": user_id, "role": role, "content": content
        }).execute()
    except Exception as e:
        st.error(f"Failed to save message: {e}")

# --- SESSION INIT ---
if "active_session_id" not in st.session_state:
    sessions = load_sessions()
    if sessions:
        st.session_state.active_session_id = sessions[0]["id"]
    else:
        new = create_session("Chat 1")
        st.session_state.active_session_id = new["id"] if new else None

# --- SEARCH HELPERS ---
def tavily_search(query: str) -> str:
    if not TAVILY_API_KEY: return "Tavily search unavailable."
    try:
        r = requests.post("https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {TAVILY_API_KEY}", "Content-Type": "application/json"},
            json={"query": query, "search_depth": "advanced", "max_results": 5, "include_answer": True},
            timeout=15)
        r.raise_for_status()
        data = r.json()
        out = []
        if data.get("answer"): out.append(f"**Answer:** {data['answer']}\n")
        for i, x in enumerate(data.get("results", [])[:5], 1):
            out.append(f"{i}. **{x.get('title','')}**")
            out.append(f"   {x.get('content','')[:300]}...")
            out.append(f"   Source: {x.get('url','')}\n")
        return "\n".join(out) or "No results found."
    except Exception as e:
        return f"Tavily search failed: {e}"

def firecrawl_search(query: str) -> str:
    if not FIRECRAWL_API_KEY: return "Firecrawl search unavailable."
    try:
        r = requests.post("https://api.firecrawl.dev/v1/search",
            headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}", "Content-Type": "application/json"},
            json={"query": query, "limit": 5}, timeout=20)
        r.raise_for_status()
        data = r.json()
        out = []
        for i, x in enumerate(data.get("data", [])[:5], 1):
            out.append(f"{i}. **{x.get('title','')}**")
            out.append(f"   {(x.get('description') or x.get('markdown',''))[:300]}...")
            out.append(f"   Source: {x.get('url','')}\n")
        return "\n".join(out) or "No results found."
    except Exception as e:
        return f"Firecrawl search failed: {e}"

# --- ASTRONOMY HELPER ---
def get_astronomy(location: str = "Islamabad,PK") -> str:
    if not IPGEOLOCATION_API_KEY: return "Astronomy data unavailable."
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        r = requests.get("https://api.ipgeolocation.io/v3/astronomy",
            params={"apiKey": IPGEOLOCATION_API_KEY, "location": location, "date": today},
            timeout=15)
        r.raise_for_status()
        data = r.json()
        astro = data.get("astronomy", {})
        sun, moon = astro.get("sun", {}), astro.get("moon", {})
        out = [f"**Astronomy for {location} on {today}:**\n"]
        for k, label in [("sunrise","☀️ Sunrise"),("sunset","🌇 Sunset"),("solar_noon","🕛 Solar Noon"),("day_length","⏱️ Day Length")]:
            if sun.get(k): out.append(f"{label}: {sun[k]}")
        for k, label in [("moonrise","🌙 Moonrise"),("moonset","🌙 Moonset"),("phase","🌒 Moon Phase")]:
            if moon.get(k): out.append(f"{label}: {moon[k]}")
        return "\n".join(out)
    except Exception as e:
        return f"Astronomy lookup failed: {e}"

def is_astronomy_query(text: str) -> bool:
    kw = ["sunrise","sunset","moonrise","moonset","moon phase","astronomy","twilight","solar noon",
          "day length","when does the sun","when does the moon","when is sunset","when is sunrise",
          "golden hour","blue hour","visible planet","planet visible"]
    return any(k in text.lower() for k in kw)

# --- SIDEBAR ---
with st.sidebar:
    st.success(f"👤 {user_email}")
    if st.button("🚪 Log out", use_container_width=True):
        try:
            supabase.auth.sign_out()
        except Exception:
            pass
        st.session_state.user = None
        st.session_state.active_session_id = None
        st.rerun()

    st.divider()
    st.header("💬 Chat Sessions")
    if st.button("➕ New Chat", use_container_width=True):
        sessions = load_sessions()
        existing = [s["session_name"] for s in sessions]
        i = 1
        while f"Chat {i}" in existing: i += 1
        new = create_session(f"Chat {i}")
        if new: st.session_state.active_session_id = new["id"]
        st.rerun()

    for s in load_sessions():
        col1, col2 = st.columns([4, 1])
        with col1:
            is_active = s["id"] == st.session_state.active_session_id
            label = f"🟢 {s['session_name']}" if is_active else f"⚪ {s['session_name']}"
            if st.button(label, key=f"select_{s['id']}", use_container_width=True):
                st.session_state.active_session_id = s["id"]
                st.rerun()
        with col2:
            sessions = load_sessions()
            if len(sessions) > 1:
                if st.button("🗑️", key=f"del_{s['id']}"):
                    delete_session(s["id"])
                    remaining = [x for x in sessions if x["id"] != s["id"]]
                    if remaining: st.session_state.active_session_id = remaining[0]["id"]
                    st.rerun()

    st.divider()
    st.header("⚙️ Configuration")

    model_mapping = {
        "🎯 Auto Free Router — Best for images, diagrams & general homework":
            {"id": "openrouter/free", "provider": "openrouter"},
        "🧠 Nemotron 3 Ultra — Deep math, long proofs & reasoning (1M context)":
            {"id": "nvidia/nemotron-3-ultra-550b-a55b:free", "provider": "openrouter"},
        "💻 Laguna S 2.1 — Coding, programming & debugging help":
            {"id": "poolside/laguna-s-2.1:free", "provider": "openrouter"},
        "⚡ Nemotron 3 Super — Fast answers, multi-agent workflows (1M context)":
            {"id": "nvidia/nemotron-3-super-120b-a12b:free", "provider": "openrouter"},
        "⚡ Groq GPT OSS 120B — Fast backup for general chat & homework":
            {"id": "openai/gpt-oss-120b", "provider": "groq"},
    }

    selected_model_name = st.selectbox("Choose AI Brain Model:", options=list(model_mapping.keys()), index=0)
    meta = model_mapping[selected_model_name]
    selected_model_id = meta["id"]
    active_provider = meta["provider"]

    web_search_enabled = st.toggle("🌐 Enable Live Web Search", value=True)
    search_provider = "Tavily"
    if web_search_enabled:
        choice = st.selectbox("🔎 Primary Search Provider:",
            options=["Tavily (Fast + AI-Optimized)", "Firecrawl (Deep Content Extraction)"], index=0)
        search_provider = "Tavily" if "Tavily" in choice else "Firecrawl"
        st.caption("🔄 Auto-Backup: Firecrawl" if search_provider == "Tavily" else "🔄 Auto-Backup: Tavily")

    astronomy_enabled = st.toggle("🔭 Enable Astronomy Data (IPGeolocation)", value=True)
    user_custom_key = st.text_input(f"🔑 Custom {active_provider.upper()} Key Override (Optional):", type="password")
    st.header("📸 Media input panel")
    uploaded_file = st.file_uploader("Snapshot your worksheet/page:", type=["jpg","jpeg","png"], key="homework_file")

# --- PROVIDER ROUTING ---
if active_provider == "groq":
    ACTIVE_API_KEY = user_custom_key or GLOBAL_GROQ_KEY
    BASE_URL = "https://api.groq.com/openai/v1"
else:
    ACTIVE_API_KEY = user_custom_key or GLOBAL_OPENROUTER_KEY
    BASE_URL = "https://openrouter.ai/api/v1"

# --- RENDER CHAT HISTORY ---
if st.session_state.active_session_id:
    for msg in load_messages(st.session_state.active_session_id):
        with st.chat_message(msg["role"], avatar=msg["role"]):
            st.write(msg["content"])
            if msg["role"] == "assistant":
                st.download_button("📥 Download Solution",
                    data=msg["content"], file_name="craftgpt_solution.md",
                    mime="text/markdown", key=f"dl_{msg['id']}")

# --- IMAGE PROCESSING ---
img_base64 = None
if uploaded_file:
    image = Image.open(uploaded_file)
    st.image(image, caption="Uploaded Homework Image", use_container_width=True)
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    img_base64 = base64.b64encode(buf.getvalue()).decode()

# --- CHAT PROCESSING ---
if prompt := st.chat_input("Ask CraftGPT a homework question..."):
    is_vision = selected_model_id == "openrouter/free"
    save_message(st.session_state.active_session_id, "user", prompt)

    with st.chat_message("user", avatar="user"):
        st.write(prompt)
        if img_base64 and is_vision:
            st.image(f"data:image/jpeg;base64,{img_base64}", width=300)

    with st.chat_message("assistant", avatar="assistant"):
        placeholder = st.empty()

        if not ACTIVE_API_KEY:
            placeholder.error(f"API Key missing for {active_provider.upper()}.")
        elif img_base64 and not is_vision:
            placeholder.error(f"🛑 **{selected_model_name}** is text-only. Use **Auto Free Router** for images.")
        else:
            astro_ctx = ""
            if astronomy_enabled and is_astronomy_query(prompt):
                with st.spinner("🔭 Fetching astronomy data..."):
                    astro_ctx = get_astronomy("Islamabad,PK")

            search_ctx = ""
            if web_search_enabled:
                with st.spinner(f"🔍 Searching with {search_provider}..."):
                    if search_provider == "Tavily":
                        if TAVILY_API_KEY: search_ctx = tavily_search(prompt)
                        if (not search_ctx or "failed" in search_ctx.lower()) and FIRECRAWL_API_KEY:
                            search_ctx = firecrawl_search(prompt)
                    else:
                        if FIRECRAWL_API_KEY: search_ctx = firecrawl_search(prompt)
                        if (not search_ctx or "failed" in search_ctx.lower()) and TAVILY_API_KEY:
                            search_ctx = tavily_search(prompt)

            client = OpenAI(base_url=BASE_URL, api_key=ACTIVE_API_KEY)
            sys_prompt = r"""You are a world-class, empathetic homework assistant named CraftGPT. Help step by step with strict mathematical accuracy. ALWAYS use LaTeX in $$ for blocks or $ for inline."""

            if astro_ctx and "unavailable" not in astro_ctx.lower():
                sys_prompt += f"\n\nAstronomy data:\n\n{astro_ctx}\n\nUse this precise data. Do not call tools yourself."
            if search_ctx and "unavailable" not in search_ctx.lower() and "failed" not in search_ctx.lower():
                sys_prompt += f"\n\nLive web results:\n\n{search_ctx}\n\nUse this info. Cite sources. Do not call tools yourself."

            api_messages = [{"role": "system", "content": sys_prompt}]
            for m in load_messages(st.session_state.active_session_id)[-4:]:
                api_messages.append({"role": m["role"], "content": m["content"]})

            if img_base64 and is_vision:
                api_messages[-1] = {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}]
                }

            try:
                headers = {}
                if active_provider == "openrouter":
                    headers = {"HTTP-Referer": APP_URL, "X-Title": "CraftGPT"}
                stream = client.chat.completions.create(
                    model=selected_model_id, messages=api_messages,
                    temperature=0.1, stream=True,
                    extra_headers=headers if active_provider == "openrouter" else None
                )
                full = ""
                for chunk in stream:
                    if chunk.choices and len(chunk.choices) > 0:
                        full += chunk.choices[0].delta.content or ""
                        placeholder.markdown(full + "▌")
                placeholder.markdown(full)
                save_message(st.session_state.active_session_id, "assistant", full)
                if img_base64:
                    st.session_state["homework_file"] = None
                st.rerun()
            except Exception as exc:
                if "402" in str(exc) or "credit" in str(exc).lower():
                    placeholder.error(f"⚠️ **{active_provider.upper()} Budget Limit:** Out of credits.")
                else:
                    placeholder.error(f"Pipeline error: {exc}")