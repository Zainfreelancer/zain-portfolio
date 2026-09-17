import os
import io
import base64

import streamlit as st
from PIL import Image
from openai import OpenAI

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

# Sidebar Workspace Layout configuration panels
with st.sidebar:
    st.header("⚙️ Configuration")

    # 🌟 FREE MODEL SELECTOR MAPPING WITH DESCRIPTIONS
    # Only verified-working free models as of Sept 2026
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

    selected_model_name = st.selectbox(
        "Choose AI Brain Model:",
        options=list(model_mapping.keys()),
        index=0
    )

    # Extract operational metadata for backend routing paths
    selected_model_meta = model_mapping[selected_model_name]
    selected_model_id = selected_model_meta["id"]
    active_provider = selected_model_meta["provider"]

    # Custom key input UI layout fallback fields
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

    # Only openrouter/free supports vision among our verified models
    vision_models = ["openrouter/free"]
    is_vision_supported = selected_model_id in vision_models

    if img_base64 and is_vision_supported:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"},
        })

    # Save immediately into persistent array tracking elements
    st.session_state.messages.append({"role": "user", "content": user_content})

    with st.chat_message("user", avatar="user"):
        st.write(prompt)

    with st.chat_message("assistant", avatar="assistant"):
        response_placeholder = st.empty()

        if not ACTIVE_API_KEY:
            response_placeholder.error(f"API Key missing for {active_provider.upper()}. Configure your tokens inside your app settings dashboard panel.")
        elif img_base64 and not is_vision_supported:
            response_placeholder.error(
                f"🛑 **Model Vision Conflict:** You uploaded an image, but **{selected_model_name}** is a text-only model profile. "
                "Please toggle over to **Auto Free Router** in the sidebar configuration dropdown to analyze worksheet photos."
            )
        else:
            client = OpenAI(
                base_url=BASE_URL,
                api_key=ACTIVE_API_KEY,
            )

            # Raw string declaration to prevent escaping character anomalies
            api_messages = [
                {
                    "role": "system",
                    "content": r"You are a world-class, empathetic homework assistant named CraftGPT. Help step by step and explain clearly with strict mathematical accuracy. ALWAYS use LaTeX formatting enclosed in double dollar signs for blocks (e.g., \[x^2\]) or single dollar signs for inline text (e.g., x)."
                }
            ]

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

                # Clear visual file state trackers cleanly upon completed resolution pass
                if img_base64:
                    st.session_state["homework_file"] = None

                st.rerun()

            except Exception as exc:
                if "402" in str(exc) or "credit" in str(exc).lower():
                    response_placeholder.error(
                        f"⚠️ **{active_provider.upper()} Server Budget Limit:** Out of computational credits. "
                        "Please pass a custom valid token string inside the configuration panel override field on the sidebar to reset the routing gateway."
                    )
                else:
                    response_placeholder.error(f"Communications tracking link broke down along the {active_provider.upper()} framework pipeline stack. Error message text: {exc}")