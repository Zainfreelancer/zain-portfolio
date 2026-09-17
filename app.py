import os
import io
import base64

import streamlit as st
from PIL import Image
from openai import OpenAI
import requests

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

# Initialize persistent session chat history arrays
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- API KEY MANAGEMENT WITH MULTI-PROVIDER BACKEND ---
GLOBAL_OPENROUTER_KEY = st.secrets.get("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY")
GLOBAL_GROQ_KEY = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
TAVILY_API_KEY = st.secrets.get("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY")
FIRECRAWL_API_KEY = st.secrets.get("FIRECRAWL_API_KEY") or os.getenv("FIRECRAWL_API_KEY")

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

# Sidebar Workspace Layout configuration panels
with st.sidebar:
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

    # --- WEB SEARCH CONTROLS ---
    web_search_enabled = st.toggle(
        "🌐 Enable Live Web Search",
        value=True,
        help="Uses YOUR Tavily + Firecrawl keys (not OpenRouter credits)."
    )

    search_provider = "Tavily (Fast + AI-Optimized)"
    if web_search_enabled:
        search_provider = st.selectbox(
            "🔎 Search Provider:",
            options=[
                "Tavily (Fast + AI-Optimized)",
                "Firecrawl (Deep Content Extraction)",
            ],
            index=0,
            help="Primary search engine. The other one auto-activates as backup if this fails."
        )

    user_custom_key = st.text_input(
        f"🔑 Custom {active_provider.upper()} Key Override (Optional):",
        type="password",
        help=f"Optionally paste your custom key here to override the global system tokens for {active_provider}."
    )

    st.header("📸 Media input panel")
    uploaded_file = st.file_uploader("Snapshot your worksheet page/equation:", type=["jpg", "jpeg", "png"], key="homework_file")

# Evaluate cascading priority constraints across providers
if active_provider == "groq":
    ACTIVE_API_KEY = user_custom_key if user_custom_key else GLOBAL_GROQ_KEY
    BASE_URL = "https://api.groq.com/openai/v1"
else:
    ACTIVE_API_KEY = user_custom_key if user_custom_key else GLOBAL_OPENROUTER_KEY
    BASE_URL = "https://openrouter.ai/api/v1"

if not ACTIVE_API_KEY:
    st.warning(f"Please add your `{active_provider.upper()}_API_KEY` to your secrets or use the custom key field override in the sidebar configuration!")

# 🛠️ WORKSPACE RESET CLEAR UTILITY BUTTON
if len(st.session_state.messages) > 0:
    if st.sidebar.button("🧹 Clear Chat History", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# Render persistent historical chat message blocks onto screen layout grids
for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar=msg["role"]):
        if isinstance(msg["content"], list):
            for item in msg["content"]:
                if item.get("type") == "text":
                    st.write(item.get("text", ""))
                elif item.get("type") == "image_url":
                    img_data = item.get("image_url", {})
                    img_url = img_data.get("url") if isinstance(img_data, dict) else img_data
                    if img_url:
                        st.image(img_url, caption="Uploaded Context Image", width=300)
        else:
            st.write(msg["content"])
            if msg["role"] == "assistant":
                st.download_button(
                    label="📥 Download Solution Sheet",
                    data=msg["content"],
                    file_name="craftgpt_solution.md",
                    mime="text/markdown",
                    key=f"dl_{hash(msg['content'])}"
                )

# Process visual workbook images into base64 string caches safely if available
img_base64 = None
if uploaded_file:
    image = Image.open(uploaded_file)
    st.image(image, caption="Uploaded Homework Image", use_container_width=True)
    buffered = io.BytesIO()
    image.save(buffered, format="JPEG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode()

# --- CHAT CONVERSATION PROCESSING LAYER ---
if prompt := st.chat_input("Ask CraftGPT a homework question..."):

    user_content = [{"type": "text", "text": prompt}]

    vision_models = ["openrouter/free"]
    is_vision_supported = selected_model_id in vision_models

    if img_base64 and is_vision_supported:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"},
        })

    st.session_state.messages.append({"role": "user", "content": user_content})

    with st.chat_message("user", avatar="user"):
        st.write(prompt)

    with st.chat_message("assistant", avatar="assistant"):
        response_placeholder = st.empty()

        if not ACTIVE_API_KEY:
            response_placeholder.error(f"API Key missing for {active_provider.upper()}.")
        elif img_base64 and not is_vision_supported:
            response_placeholder.error(
                f"🛑 **Model Vision Conflict:** You uploaded an image, but **{selected_model_name}** is text-only. "
                "Toggle to **Auto Free Router** to analyze worksheet photos."
            )
        else:
            # --- WEB SEARCH WITH SELECTED PROVIDER + AUTO FALLBACK ---
            search_context = ""
            if web_search_enabled:
                with st.spinner(f"🔍 Searching with {search_provider}..."):
                    if "Tavily" in search_provider:
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

            # FIXED: Clean system prompt — no "use the web search tool" language
            system_prompt = r"""You are a world-class, empathetic homework assistant named CraftGPT. Help step by step and explain clearly with strict mathematical accuracy. ALWAYS use LaTeX formatting enclosed in double dollar signs for blocks (e.g., \[x^2\]) or single dollar signs for inline text (e.g., x)."""

            # FIXED: Inject search results as plain context, not as a tool the model must call
            if search_context and "unavailable" not in search_context.lower() and "failed" not in search_context.lower():
                system_prompt += f"\n\nHere is some up-to-date information that may help answer the user's question:\n\n{search_context}\n\nUse this information to inform your answer. Cite sources when appropriate. Do not attempt to call any search tools yourself — the search has already been done for you."

            api_messages = [{"role": "system", "content": system_prompt}]

            for msg in st.session_state.messages[-4:]:
                api_messages.append({"role": msg["role"], "content": msg["content"]})

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
                st.session_state.messages.append({"role": "assistant", "content": full_response})

                if img_base64:
                    st.session_state["homework_file"] = None

                st.rerun()

            except Exception as exc:
                if "402" in str(exc) or "credit" in str(exc).lower():
                    response_placeholder.error(
                        f"⚠️ **{active_provider.upper()} Budget Limit:** Out of credits."
                    )
                else:
                    response_placeholder.error(f"Pipeline error on {active_provider.upper()}: {exc}")