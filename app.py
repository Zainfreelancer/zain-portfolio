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

# --- SUPABASE CLIENT ---
@st.cache_resource
def init_supabase() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# --- DATABASE HELPERS ---
def load_sessions():
    """Load all chat sessions from Supabase."""
    if not supabase:
        return []
    try:
        response = supabase.table("chat_sessions").select("*").order("created_at", desc=True).execute()
        return response.data
    except Exception as e:
        st.error(f"Failed to load sessions: {e}")
        return []

def create_session(name: str):
    """Create a new chat session in Supabase."""
    if not supabase:
        return None
    try:
        response = supabase.table("chat_sessions").insert({"session_name": name}).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        st.error(f"Failed to create session: {e}")
        return None

def delete_session(session_id: int):
    """Delete a chat session (messages cascade automatically)."""
    if not supabase:
        return
    try:
        supabase.table("chat_sessions").delete().eq("id", session_id).execute()
    except Exception as e:
        st.error(f"Failed to delete session: {e}")

def load_messages(session_id: int):
    """Load all messages for a given session."""
    if not supabase:
        return []
    try:
        response = supabase.table("chat_messages").select("*").eq("session_id", session_id).order("created_at").execute()
        return response.data
    except Exception as e:
        st.error(f"Failed to load messages: {e}")
        return []

def save_message(session_id: int, role: str, content: str):
    """Save a message to a session."""
    if not supabase:
        return
    try:
        supabase.table("chat_messages").insert({
            "session_id": session_id,
            "role": role,
            "content": content
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

# --- TAVILY SEARCH HELPER ---
def tavily_search(query: str) -> str:
    if not TAVILY_API_KEY:
        return "Tavily search unavailable (no API key)."
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {TAVILY_API_KEY}", "Content-Type": "application/json"},
            json={"query": query, "search_depth": "advanced", "max_results": 5, "include_answer": True},
            timeout=15
        )
        response.raise_for_status()
        data = response.json()
        output = []
        if data.get("answer"):
            output.append(f"**Answer:** {data['answer']}\n")
        for i, result in enumerate(data.get("results", [])[:5], 1):
            output.append(f"{i}. **{result.get('title', 'No title')}**")
            output.append(f"   {result.get('content', '')[:300]}...")
            output.append(f"   Source: {result.get('url', '')}\n")
        return "\n".join(output) if output else "No results found."
    except Exception as e:
        return f"Tavily search failed: {e}"

# --- FIRECRAWL SEARCH HELPER ---
def firecrawl_search(query: str) -> str:
    if not FIRECRAWL_API_KEY:
        return "Firecrawl search unavailable (no API key)."
    try:
        response = requests.post(
            "https://api.firecrawl.dev/v1/search",
            headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}", "Content-Type": "application/json"},
            json={"query": query, "limit": 5},
            timeout=20
        )
        response.raise_for_status()
        data = response.json()
        output = []
        for i, result in enumerate(data.get("data", [])[:5], 1):
            output.append(f"{i}. **{result.get('title', 'No title')}**")
            desc = result.get('description') or result.get('markdown', '')
            output.append(f"   {desc[:300]}...")
            output.append(f"   Source: {result.get('url', '')}\n")
        return "\n".join(output) if output else "No results found."
    except Exception as e:
        return f"Firecrawl search failed: {e}"

# --- IPGEOLOCATION ASTRONOMY HELPER ---
def get_astronomy(location: str = "Islamabad,PK") -> str:
    if not IPGEOLOCATION_API_KEY:
        return "Astronomy data unavailable (no API key)."
    try:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        url = "https://api.ipgeolocation.io/v3/astronomy"
        params = {"apiKey": IPGEOLOCATION_API_KEY, "location": location, "date": today}
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        astronomy = data.get("astronomy", {})
        sun = astronomy.get("sun", {})
        moon = astronomy.get("moon", {})
        output = [f"**Astronomy for {location} on {today}:**\n"]
        if sun.get("sunrise"): output.append(f"☀️ Sunrise: {sun['sunrise']}")
        if sun.get("sunset"): output.append(f"🌇 Sunset: {sun['sunset']}")
        if sun.get("solar_noon"): output.append(f"🕛 Solar Noon: {sun['solar_noon']}")
        if sun.get("day_length"): output.append(f"⏱️ Day Length: {sun['day_length']}")
        if moon.get("moonrise"): output.append(f"🌙 Moonrise: {moon['moonrise']}")
        if moon.get("moonset"): output.append(f"🌙 Moonset: {moon['moonset']}")
        if moon.get("phase"): output.append(f"🌒 Moon Phase: {moon['phase']}")
        return "\n".join(output)
    except Exception as e:
        return f"Astronomy lookup failed: {e}"

# --- DETECT ASTRONOMY QUERIES ---
def is_astronomy_query(text: str) -> bool:
    keywords = ["sunrise", "sunset", "moonrise", "moonset", "moon phase",
        "astronomy", "twilight", "solar noon", "day length",
        "when does the sun", "when does the moon", "when does sunrise",
        "when does sunset", "when is sunset", "when is sunrise",
        "golden hour", "blue hour", "visible planet", "planet visible"]
    return any(kw in text.lower() for kw in keywords)

# --- SIDEBAR ---
with st.sidebar:
    st.header("💬 Chat Sessions")

    if st.button("➕ New Chat", use_container_width=True):
        sessions = load_sessions()
        i = 1
        existing_names = [s["session_name"] for s in sessions]
        while f"Chat {i}" in existing_names:
            i += 1
        new = create_session(f"Chat {i}")
        if new:
            st.session_state.active_session_id = new["id"]
        st.rerun()

    sessions = load_sessions()
    for s in sessions:
        col1, col2 = st.columns([4, 1])
        with col1:
            is_active = s["id"] == st.session_state.active_session_id
            label = f"🟢 {s['session_name']}" if is_active else f"⚪ {s['session_name']}"
            if st.button(label, key=f"select_{s['id']}", use_container_width=True):
                st.session_state.active_session_id = s["id"]
                st.rerun()
        with col2:
            if len(sessions) > 1:
                if st.button("🗑️", key=f"delete_{s['id']}"):
                    delete_session(s["id"])
                    remaining = [x for x in sessions if x["id"] != s["id"]]
                    if remaining:
                        st.session_state.active_session_id = remaining[0]["id"]
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
    selected_model_meta = model_mapping[selected_model_name]
    selected_model_id = selected_model_meta["id"]
    active_provider = selected_model_meta["provider"]

    web_search_enabled = st.toggle("🌐 Enable Live Web Search", value=True)
    search_provider = "Tavily"
    if web_search_enabled:
        search_provider_choice = st.selectbox(
            "🔎 Primary Search Provider:",
            options=["Tavily (Fast + AI-Optimized)", "Firecrawl (Deep Content Extraction)"],
            index=0
        )
        search_provider = "Tavily" if "Tavily" in search_provider_choice else "Firecrawl"
        if search_provider == "Tavily":
            st.caption("🔄 Auto-Backup: Firecrawl")
        else:
            st.caption("🔄 Auto-Backup: Tavily")

    astronomy_enabled = st.toggle("🔭 Enable Astronomy Data (IPGeolocation)", value=True)

    user_custom_key = st.text_input(
        f"🔑 Custom {active_provider.upper()} Key Override (Optional):",
        type="password"
    )

    st.header("📸 Media input panel")
    uploaded_file = st.file_uploader("Snapshot your worksheet/page:", type=["jpg", "jpeg", "png"], key="homework_file")

# --- PROVIDER ROUTING ---
if active_provider == "groq":
    ACTIVE_API_KEY = user_custom_key if user_custom_key else GLOBAL_GROQ_KEY
    BASE_URL = "https://api.groq.com/openai/v1"
else:
    ACTIVE_API_KEY = user_custom_key if user_custom_key else GLOBAL_OPENROUTER_KEY
    BASE_URL = "https://openrouter.ai/api/v1"

if not ACTIVE_API_KEY:
    st.warning(f"Please add your `{active_provider.upper()}_API_KEY` to your secrets.")

# --- RENDER ACTIVE SESSION'S HISTORY FROM SUPABASE ---
if st.session_state.active_session_id:
    history = load_messages(st.session_state.active_session_id)
    for msg in history:
        with st.chat_message(msg["role"], avatar=msg["role"]):
            st.write(msg["content"])
            if msg["role"] == "assistant":
                st.download_button(
                    label="📥 Download Solution Sheet",
                    data=msg["content"],
                    file_name="craftgpt_solution.md",
                    mime="text/markdown",
                    key=f"dl_{msg['id']}"
                )

# --- IMAGE PROCESSING ---
img_base64 = None
if uploaded_file:
    image = Image.open(uploaded_file)
    st.image(image, caption="Uploaded Homework Image", use_container_width=True)
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode()

# --- CHAT PROCESSING ---
if prompt := st.chat_input("Ask CraftGPT a homework question..."):

    is_vision_supported = selected_model_id == "openrouter/free"

    # Save user message to Supabase (text only — image handled separately)
    save_message(st.session_state.active_session_id, "user", prompt)

    with st.chat_message("user", avatar="user"):
        st.write(prompt)
        if img_base64 and is_vision_supported:
            st.image(f"data:image/jpeg;base64,{img_base64}", width=300)

    with st.chat_message("assistant", avatar="assistant"):
        response_placeholder = st.empty()

        if not ACTIVE_API_KEY:
            response_placeholder.error(f"API Key missing for {active_provider.upper()}.")
        elif img_base64 and not is_vision_supported:
            response_placeholder.error(
                f"🛑 **Model Vision Conflict:** **{selected_model_name}** is text-only. "
                "Toggle to **Auto Free Router** to analyze worksheet photos."
            )
        else:
            astronomy_context = ""
            if astronomy_enabled and is_astronomy_query(prompt):
                with st.spinner("🔭 Fetching astronomy data..."):
                    astronomy_context = get_astronomy("Islamabad,PK")

            search_context = ""
            if web_search_enabled:
                with st.spinner(f"🔍 Searching with {search_provider}..."):
                    if search_provider == "Tavily":
                        if TAVILY_API_KEY:
                            search_context = tavily_search(prompt)
                        if (not search_context or "failed" in search_context.lower() or "unavailable" in search_context.lower()) and FIRECRAWL_API_KEY:
                            search_context = firecrawl_search(prompt)
                    else:
                        if FIRECRAWL_API_KEY:
                            search_context = firecrawl_search(prompt)
                        if (not search_context or "failed" in search_context.lower() or "unavailable" in search_context.lower()) and TAVILY_API_KEY:
                            search_context = tavily_search(prompt)

            client = OpenAI(base_url=BASE_URL, api_key=ACTIVE_API_KEY)

            system_prompt = r"""You are a world-class, empathetic homework assistant named CraftGPT. Help step by step and explain clearly with strict mathematical accuracy. ALWAYS use LaTeX formatting enclosed in double dollar signs for blocks (e.g., \[x^2\]) or single dollar signs for inline text (e.g., x)."""

            if astronomy_context and "unavailable" not in astronomy_context.lower() and "failed" not in astronomy_context.lower():
                system_prompt += f"\n\nAstronomy data for the user's location (Islamabad, Pakistan):\n\n{astronomy_context}\n\nUse this precise data to answer the user's astronomy question. Do not attempt to call any tools yourself."

            if search_context and "unavailable" not in search_context.lower() and "failed" not in search_context.lower():
                system_prompt += f"\n\nHere is some up-to-date information that may help answer the user's question:\n\n{search_context}\n\nUse this information to inform your answer. Cite sources when appropriate. Do not attempt to call any search tools yourself."

            api_messages = [{"role": "system", "content": system_prompt}]

            # Build message history from last 4 Supabase messages
            recent = load_messages(st.session_state.active_session_id)[-4:]
            for msg in recent:
                if msg["role"] == "user":
                    api_messages.append({"role": "user", "content": msg["content"]})
                else:
                    api_messages.append({"role": "assistant", "content": msg["content"]})

            # If an image is uploaded and vision supported, append it to the last user message
            if img_base64 and is_vision_supported:
                api_messages[-1] = {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"}}
                    ]
                }

            try:
                extra_headers = {}
                if active_provider == "openrouter":
                    extra_headers = {
                        "HTTP-Referer": "http://localhost:8501",
                        "X-Title": "CraftGPT Companion",
                    }

                stream = client.chat.completions.create(
                    model=selected_model_id,
                    messages=api_messages,
                    temperature=0.1,
                    stream=True,
                    extra_headers=extra_headers if active_provider == "openrouter" else None
                )

                full_response = ""
                for chunk in stream:
                    if chunk.choices and len(chunk.choices) > 0:
                        chunk_text = chunk.choices[0].delta.content or ""
                        full_response += chunk_text
                        response_placeholder.markdown(full_response + "▌")

                response_placeholder.markdown(full_response)

                # Save assistant reply to Supabase
                save_message(st.session_state.active_session_id, "assistant", full_response)

                if img_base64:
                    st.session_state["homework_file"] = None

                st.rerun()

            except Exception as exc:
                if "402" in str(exc) or "credit" in str(exc).lower():
                    response_placeholder.error(f"⚠️ **{active_provider.upper()} Budget Limit:** Out of credits.")
                else:
                    response_placeholder.error(f"Pipeline error on {active_provider.upper()}: {exc}")