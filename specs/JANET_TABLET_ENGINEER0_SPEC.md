# Janet Tablet Capabilities + Engineer0 Sandbox Spec
_Captured 2026-05-05 — from Darnie's session requirements_

---

## MadJanet (PlugToo — Android tablet)

### Camera & Vision
- [ ] Still camera: capture photos on demand (from chat or autonomously)
- [ ] Video recording: start/stop video capture
- [ ] Image analysis: OCR + object/scene recognition (vision model required)
- [ ] Video analysis: extract and analyze frames, describe content
- [ ] Send images from any plug to Janet for analysis (cross-plug image routing)

### Audio
- [ ] Audio recording: record ambient/directed audio clips
- [ ] Audio transcription: STT of recorded clips (extend existing speech recognition)
- [ ] Audio playback: play back recordings or TTS responses

### Device & System
- [ ] Open other apps on tablet via Android Intents (Linking / expo-intent-launcher)
  - NOTE: RN can launch apps by package name or deep link; cannot inject input into them
- [ ] Error log access: read logcat / app error logs; relay to user on demand
- [ ] Auto error logging: catch all unhandled errors, persist to AsyncStorage + sync to PlugOps
- [ ] File system access: read/write within app sandbox + Downloads/Documents with permission

### Web
- [ ] Web search: query search API (Brave/Google CSE) from within Janet
- [ ] Web browsing: embedded WebView panel for navigation (react-native-webview)
- [ ] Extract text from web pages for Janet to analyze

### Data Sync
- [ ] Sync Janet's conversation history and artifacts to PlugOps on demand
- [ ] Artifacts (photos, audio clips, transcripts) uploadable to PlugOps via API

### UI: Artifact Panel
- [ ] Right-side split panel on chat screen
- [ ] Shows: images, video playback, web pages, text artifacts, live camera preview
- [ ] Resizable or toggle-able
- [ ] Live camera feed option (preview while Janet is using camera)

### Cross-Plug Chat
- [ ] Send images to Janet from PlugWan (Mac dashboard), PlugToo (tablet), PlugTree (iPhone)
- [ ] PlugOps API must handle multipart uploads + route to Janet's inbox
- [ ] Janet receives images as attachments in her message stream

---

## Engineer0 (Zee)

### Sandbox Environment
- [ ] Dedicated sandbox dir: ~/engineer0-sandbox/ (separate from production)
- [ ] All new code written here first; tested before promoting to cmptrblk/
- [ ] Sandbox has its own git repo (local) for version tracking test work
- [ ] Promotion command: `promote <file/dir>` moves from sandbox to production path

### Todo List
- [ ] Todo file: ~/engineer0-sandbox/TODO.md (Markdown checklist)
- [ ] Engineer0 checks TODO.md on her task_loop (every 30s)
- [ ] Picks the next unchecked item, works on it autonomously
- [ ] Marks item done (checks it off) when complete, adds result note
- [ ] User can add items from any chat interface (dashboard, PlugOps chat)

### Chat & Assignment
- [ ] Full chat via PlugOps dashboard (already working via /api/v1/chat)
- [ ] Assign tasks by chatting: "Add to your todo: ..."  → appends to TODO.md
- [ ] Engineer0 reports what she's working on in status/heartbeat

### Testing in Sandbox
- [ ] Run tests in sandbox before promoting: `python test.py` or `pytest`
- [ ] Test results logged to ~/engineer0-sandbox/test_results/
- [ ] Engineer0 only promotes code that passes tests

---

## Build Order (recommended)

1. **Engineer0 sandbox** — sandbox dir, TODO.md, task_loop hook (quick win)
2. **Janet artifact panel** — UI split panel (React Native)
3. **Janet camera tools** — still photo + video capture tools (expo-camera already installed)
4. **PlugOps image routing** — multipart upload endpoint + inbox delivery
5. **Cross-plug image send** — dashboard + iPhone UI for sending images
6. **Janet video/image analysis** — vision model decision (llava locally or API)
7. **Janet web tools** — search API + WebView browser panel
8. **Janet audio recording** — capture + transcription
9. **Janet system tools** — app launching, log access, error reporting
10. **Janet data sync** — artifact upload to PlugOps

---

## Technical Notes

### Vision model
Janet's current model (madjanet:latest) is text-only.
Options:
  A. Pull llava:7b or bakllava to tablet Ollama (requires ~4GB + capable tablet)
  B. Route vision requests through PlugOps → Engineer0 → Claude API (cloud, no tablet GPU)
  C. Pull minicpm-v or moondream (smaller vision models, ~2GB)

Recommendation: Start with B (cloud routing via PlugOps) while testing model size feasibility
for on-device option. Tablet is Teclast — check if it has enough RAM for a 4B vision model.

### "Full tablet control" clarification
React Native cannot inject input into other apps or control the screen like an automation tool.
What IS possible from within the app:
  - Launch other apps (by package name)
  - Camera, mic, file system (with permissions)
  - Network requests
  - Expose an accessibility service (separate APK) — not scoped for now

