import os
import io
import base64

import streamlit as st
from PIL import Image
from openai import OpenAI

# 1. Cleanly set your browser tab title text
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
st.caption("Universal Multimodal Homework Assistant | Powered by OpenRouter")

# Initialize persistent chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

OPENROUTER_API_KEY = st.secrets.get("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API_KEY")

if not OPENROUTER_API_KEY:
    st.warning("Please add your `OPENROUTER_API_KEY` to your Streamlit secrets file to activate your AI brain!")
    st.info("You can get a free key by registering at openrouter.ai")

# 🛠️ CLEAR HISTORY UTILITY: Clean workspace reset
if len(st.session_state.messages) > 0:
    if st.sidebar.button("🧹 Clear Chat History", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

# Cleanly renders BOTH historical text and historical images in the chat view with system avatars
for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar=msg["role"]):
        if isinstance(msg["content"], list):
            for item in msg["content"]:
                if item["type"] == "text":
                    st.write(item["text"])
                elif item["type"] == "image_url":
                    st.image(item["image_url"]["url"], caption="Uploaded Context Image", width=300)
        else:
            st.write(msg["content"])
            
            # EXPORT FEATURE: Add a download utility button under every assistant answer block
            if msg["role"] == "assistant":
                st.download_button(
                    label="📥 Download Solution Sheet",
                    data=msg["content"],
                    file_name="craftgpt_solution.md",
                    mime="text/markdown",
                    key=f"dl_{hash(msg['content'])}"
                )

# Sidebar Workspace Layout
with st.sidebar:
    st.header("⚙️ Configuration")
    
    # Dynamic Model Selector Dropdown
    model_mapping = {
        "GPT-4o (All-Rounder)": "openai/gpt-4o",
        "Gemini 2.5 Pro (Best for Diagrams & Charts)": "google/gemini-2.5-pro",
        "DeepSeek R1 (Best for Math & Logic Proofs)": "deepseek/deepseek-r1"
    }
    selected_model_name = st.selectbox(
        "Choose AI Brain Model:",
        options=list(model_mapping.keys()),
        index=0
    )
    selected_model_id = model_mapping[selected_model_name]

    st.header("📸 Media input panel")
    uploaded_file = st.file_uploader("Snapshot your worksheet page/equation:", type=["jpg", "jpeg", "png"], key="homework_file")

img_base64 = None

if uploaded_file:
    image = Image.open(uploaded_file)
    st.image(image, caption="Uploaded Homework Image", use_container_width=True)

    buffered = io.BytesIO()
    image.save(buffered, format="JPEG")
    img_base64 = base64.b64encode(buffered.getvalue()).decode()

if prompt := st.chat_input("Ask CraftGPT a homework question..."):
    
    # Construct contemporary payload for THIS dynamic turn only
    user_content = [{"type": "text", "text": prompt}]
    
    # SAFE VISION FILTER: Only attach the image if the selected model supports vision input
    is_vision_supported = "deepseek-r1" not in selected_model_id
    
    if img_base64 and is_vision_supported:
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{img_base64}"},
        })

    # Save cleanly to historical array
    st.session_state.messages.append({"role": "user", "content": user_content})
    
    with st.chat_message("user", avatar="user"):
        st.write(prompt)

    with st.chat_message("assistant", avatar="assistant"):
        response_placeholder = st.empty()
        
        if not OPENROUTER_API_KEY:
            response_placeholder.error("API Key missing. Enter your key to run the engine.")
        elif img_base64 and not is_vision_supported:
            response_placeholder.error(
                f"🛑 **Model Vision Conflict:** You uploaded an image, but **{selected_model_name}** is a text-only model. "
                "Please select **Gemini 2.5 Pro** or **GPT-4o** in the sidebar configuration to analyze math images."
            )
        else:
            client = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=OPENROUTER_API_KEY,
            )

            # Build our clean operational system context
            api_messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a world-class, empathetic homework assistant named CraftGPT. "
                        "Help step by step and explain clearly with strict mathematical accuracy. "
                        "ALWAYS use LaTeX formatting enclosed in double dollar signs for blocks (e.g., \[x^2\]) "
                        "or single dollar signs for inline text (e.g., \(x\))."
                    ),
                }
            ]
            
            # 🛠️ OPTIMIZED ROLLING WINDOW: Maps only the last 4 turns to protect your token ceiling context bounds
            for msg in st.session_state.messages[-4:]:
                api_messages.append({"role": msg["role"], "content": msg["content"]})

            try:
                stream = client.chat.completions.create(
                    model=selected_model_id, 
                    messages=api_messages,
                    temperature=0.1, 
                    max_tokens=2000, # Raised safely back up because memory leaks are plugged!
                    stream=True,
                    extra_headers={
                        "HTTP-Referer": "http://localhost:8501",
                        "X-Title": "CraftGPT Companion",
                    }
                )

                full_response = ""
                for chunk in stream:
                    if chunk.choices and len(chunk.choices) > 0:
                        chunk_text = chunk.choices[0].delta.content or ""
                        full_response += chunk_text
                        response_placeholder.markdown(full_response + "▌")
                
                response_placeholder.markdown(full_response)
                st.session_state.messages.append({"role": "assistant", "content": full_response})
                st.rerun()

            except Exception as exc:
                # 🛠️ SAFE FAILOVER CAPTURE BLOCK
                if "402" in str(exc):
                    response_placeholder.error(
                        "⚠️ **Server Budget Limit Hit:** The global account balance is currently out of credits. "
                        "To keep using the platform completely free, go to your app settings panel and register your own custom "
                        "free key endpoint from openrouter.ai/settings/credits."
                    )
                else:
                    response_placeholder.error(f"Failed to communicate with OpenRouter. Error: {exc}")

    # SAFE PLACEMENT: Trigger rerun cleanly OUTSIDE the assistant rendering context block
    if img_base64:
        st.session_state["homework_file"] = None
        st.rerun()
