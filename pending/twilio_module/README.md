# twilio_module

Twilio integration for Engineer0. Provides SMS alerts, outbound voice calls, and a ConversationRelay AI phone bridge so you can talk to Engineer0 over a real phone call.

---

## What it does

| Feature | Description |
|---|---|
| SMS alerts | Engineer0 texts you task completions, errors, and status updates |
| Voice calls | Engineer0 calls your phone with a spoken message |
| ConversationRelay | Inbound calls connect to a live WebSocket bridge — you speak, Twilio transcribes, Engineer0 replies via text-to-speech |
| SMS commands | Control Engineer0 by replying to its texts |

---

## Setup

### 1. Install

```bash
pip install -e /path/to/twilio_module
# or
pip install twilio flask websockets
```

### 2. Environment variables

Copy `.env.example` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `TWILIO_ACCOUNT_SID` | From your Twilio console (starts with `AC`) |
| `TWILIO_AUTH_TOKEN` | From your Twilio console |
| `TWILIO_FROM_NUMBER` | Your Twilio phone number (E.164 format, e.g. `+15551234567`) |
| `TWILIO_TO_NUMBER` | Your personal number to receive alerts |
| `TWILIO_WEBHOOK_URL` | Public HTTPS base URL Twilio uses for webhooks (ngrok works) |

---

## Quick start

### Send an SMS

```python
from twilio_module import SMSNotifier

notifier = SMSNotifier()
notifier.send("Task complete: trained model with 94% accuracy")
```

### Call your phone

```python
from twilio_module import VoiceBridge

bridge = VoiceBridge()
bridge.call("Engineer Zero here. Your training run finished successfully.")
```

### Start ConversationRelay (AI phone calls)

```python
from twilio_module import ConversationRelayServer

def my_ai(text: str) -> str:
    # plug in your LLM / Engineer0 brain here
    return f"You said: {text}"

server = ConversationRelayServer(ai_chat_fn=my_ai, port=8765)
server.run()  # blocking — run in a thread or separate process
```

When someone calls your Twilio number, Twilio hits `/twilio/voice/inbound`, which returns TwiML pointing at `wss://yourserver:8765`. Twilio opens the WebSocket, streams transcripts, and speaks back the AI responses in real time.

---

## Wiring into Engineer0

### 1. Register the Flask blueprint

```python
# In your Engineer0 Flask app factory
from twilio_module import create_twilio_blueprint

app = Flask(__name__)
app.register_blueprint(create_twilio_blueprint(), url_prefix="/twilio")
```

This registers:
- `POST /twilio/sms/inbound` — handles incoming SMS from Twilio
- `POST /twilio/voice/inbound` — answers inbound calls with ConversationRelay TwiML

### 2. Set your webhook URLs in Twilio console

- SMS webhook: `https://yourngrok.ngrok.io/twilio/sms/inbound`
- Voice webhook: `https://yourngrok.ngrok.io/twilio/voice/inbound`

### 3. Start the WebSocket server alongside your Flask app

```python
import threading
from twilio_module import ConversationRelayServer

def start_ws():
    ConversationRelayServer(ai_chat_fn=engineer0_chat).run()

threading.Thread(target=start_ws, daemon=True).start()
```

---

## SMS commands

When you reply to an Engineer0 text, these keywords are parsed:

| Command | Action |
|---|---|
| `task: <description>` | Queue a new task for Engineer0 |
| `status` | Engineer0 replies with current task and system state |
| `learn: <fact>` | Store a fact in Engineer0's memory |
| `go` | Resume a paused Engineer0 run |
| `stop` | Pause the current Engineer0 run |

---

## Project layout

```
twilio_module/
    __init__.py          # exports: TwilioClient, TwilioConfig, SMSNotifier,
                         #          VoiceBridge, ConversationRelayServer, create_twilio_blueprint
    client.py            # TwilioClient + TwilioConfig (REST client wrapper)
    sms.py               # SMSNotifier (send/receive/parse/TwiML)
    voice.py             # VoiceBridge (call + ConversationRelay TwiML)
    websocket_server.py  # ConversationRelayServer (asyncio + websockets)
    flask_routes.py      # Blueprint factory for inbound webhooks
setup.py
.env.example
README.md
```

---

## Dependencies

- `twilio >= 8.0.0`
- `flask >= 2.0.0`
- `websockets >= 12.0`
