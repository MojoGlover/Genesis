import gradio as gr
import requests
import json

def chat(message, history):
    # Show thinking status
    yield "🤔 Thinking..."
    
    response = requests.post(
        "http://localhost:8000/ai",
        json={"prompt": message}
    )
    
    data = response.json()
    
    # Show model used
    model_info = f"[{data['model']} • {data['latency_ms']}ms]"
    if data.get('tool_used'):
        model_info += f" • 🔧 {data['tool_used']}"
    
    # Stream the response with metadata
    yield f"{data['response']}\n\n_{model_info}_"

gr.ChatInterface(chat).launch()
