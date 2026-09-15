import os
import io
import base64

import streamlit as st
from PIL import Image
from openai import OpenAI

# 1. Cleanly set your browser tab title text
st.set_page_config(page_title="CraftGPT App", page_icon="🚀", layout="centered")

# 💎 PREMIUM GEMINI STYLING INJECTION (Gives it custom dark theme and rounded chat bubbles)
st.markdown("""
    <style>
        /* Base Background Canvas Color */
        .stApp {
            background-color: #131314 !important;
            color: #E3E3E3 !important;
        }
        /* Custom Header Gradient Effect */
        h1 {
            background: linear-gradient(45deg, #4285F4, #9B51E0);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            font-weight: 800 !important;
        }
        /* File Uploader styling */
        .stFileUploader {
            background-color: #1E1F20;
            border-radius: 12px;
            padding: 10px;
            border: 1px solid #444746;
        }
        /* Make user message boxes soft round gray */
        div[data-testid="stChatMessage"] {
            border-radius: 16px;
            padding: 15px;
            margin-bottom: 10px;
        }
    </style>
""", unsafe_allow_html=True)

st.title("🚀 CraftGPT")
st.caption("Universal Multimodal Homework Assistant | Powered by OpenRouter")

if "messages" not in st.session_state:
    st.session_state.messages = []

OPENROUTER_API_KEY = st.secrets.get("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY")

if not OPENROUTER_API_KEY:
    st.warning("Please add your `OPENROUTER_API_KEY` to your Streamlit secrets file to activate your AI brain!")
    st.info("You can get a free key by registering at openrouter.ai")

# Render previous chat histories cleanly
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# 💎 Moves your camera workspace upload layout neatly into a left-hand navigation column tray
with st.sidebar:
    st.header("📸 Media input panel")
    uploaded_file = st.file_uploader("Snapshot your worksheet page/equation:", type=["jpg", "jpeg", "png"])

img_base64 = None

if uploaded_file:
    image = Image.open(uploaded_file)
    st.image(image, caption="Uploaded Homework Image", use_container_width=True)

    buffered = io.BytesIO()
    image.save(buffered, format="JPEG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode()

if prompt := st.chat_input("Ask CraftGPT a homework question..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        response_placeholder = st.empty()
        
        if not OPENROUTER_API_KEY:
            response_placeholder.error("API Key missing. Enter your key to run the engine.")
        else:
            # Connect using the standardized OpenAI structural client pointing to OpenRouter
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=OPENROUTER_API_KEY,
            )

            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a world-class, empathetic homework assistant named CraftGPT. "
                        "Help step by step and explain clearly. "
                        "CRITICAL: When writing mathematical equations, formulas, fractions, or symbols, "
                        "ALWAYS use LaTeX formatting enclosed in double dollar signs for blocks (e.g., $$x^2$$) "
                        "or single dollar signs for inline text (e.g., $x$). Avoid plain text math notation entirely."
                    ),
                }
            ]

            user_content = [{"type": "text", "text": prompt}]
            if img_base64:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"},
                })

            messages.append({"role": "user", "content": user_content})

            try:
                # ⚡ Official bulletproof SDK Streaming block
                stream = client.chat.completions.create(
                    model="openai/gpt-4o-mini",
                    messages=messages,
                    temperature=0.7,
                    stream=True,
                    extra_headers={
                        "HTTP-Referer": "http://localhost:8501",
                        "X-Title": "CraftGPT Companion",
                    }
                )

                full_response = ""
                for chunk in stream:
                    if chunk.choices and len(chunk.choices) > 0:
                        # FIX HERE: Safely reading index 0 choices chunk delta text content
                        chunk_text = chunk.choices[0].delta.content or ""
                        full_response += chunk_text
                        response_placeholder.markdown(full_response + "▌")
                
                response_placeholder.markdown(full_response)
                st.session_state.messages.append({"role": "assistant", "content": full_response})

            except Exception as exc:
                response_placeholder.error(f"Failed to communicate with OpenRouter. Error: {exc}")
