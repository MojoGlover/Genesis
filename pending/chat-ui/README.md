# PlugOps Chat UI Starter (Responsive + Files + STT + Voice Mode Buttons)

This is a **starter UI** you can hand to a coding model (Claude Code / Cursor / etc.) and say:
"Make this production-ready, wire it to my gateway, keep all features."

## What you get right now
- ✅ Responsive app shell (desktop/tablet/phone)
- ✅ Chat page with streaming (SSE) demo backend
- ✅ File upload UX (chips, drag/drop) + **API contract**
- ✅ Speech-to-text (browser Web Speech API) in chat composer + voice workspace page
- ✅ TTS replies (browser SpeechSynthesis)
- ✅ Pages: /chat, /files, /voice, /settings

## Known limitation (intentional starter)
**/api/files** is a contract stub in App Router because `formidable` expects a Node IncomingMessage.
There are 3 fast fixes:

### Fix A (recommended): move uploads to Pages Router
1) Create `src/pages/api/files.ts`
2) Use `formidable` there (works cleanly)
3) Update the UI fetch URL to `/api/files` (same path)

### Fix B: signed uploads (best for cloud)
- Use signed upload URLs to GCS/S3
- UI uploads directly to storage
- API just returns file_id + metadata

### Fix C: custom multipart parser for App Router
- Implement Web API multipart parsing (more work)

## Run locally
```bash
npm install
npm run dev
```

Open:
- http://localhost:3000/chat

## Backend wiring plan
Replace these demo endpoints:
- GET  /api/models?provider=local|hosted
- POST /api/chat   (SSE streaming)
- POST /api/files  (multipart)  <-- implement via Fix A/B/C
Optional:
- POST /api/stt
- POST /api/tts

## Voice chat mode (full duplex)
This starter includes:
- STT dictation (browser)
- TTS speak replies (browser)
- "Voice" button + stop TTS

To make **real full voice chat**:
- Capture mic continuously (AudioWorklet/WebRTC)
- Detect end-of-utterance
- Stream audio to server STT
- Stream audio back from server TTS
- Support barge-in by stopping playback immediately on mic activity

## Notes
- Settings persist in localStorage (starter).
- Chat streaming is a demo echo server.
- Layout is built to add more pages later without redesign.
