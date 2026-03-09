/**
 * GENESIS Mobile PWA — Alpine.js Application
 */

function genesis() {
  return {
    // ── State ──────────────────────────────────────
    tab: 0,                  // 0=Chat, 1=Tasks, 2=Code, 3=Settings
    message: '',
    history: [],             // [{role, content}]
    tasks: [],               // orchestrator task objects
    choices: [],             // formatted choice strings
    selectedTaskId: null,
    selectedTaskDetails: '',
    code: '# Start a conversation to generate code',
    savePath: '/workspace/script.py',
    executionLog: '',
    status: 'ready',
    voiceAudio: null,
    locationStatus: 'Not shared',
    isLoading: false,
    isExecuting: false,
    isRecording: false,
    toastMsg: '',
    toastTimeout: null,

    // ── Init ───────────────────────────────────────
    init() {
      // Track swipe panel position
      const panels = this.$refs.panels;
      if (panels) {
        panels.addEventListener('scroll', () => {
          const idx = Math.round(panels.scrollLeft / panels.offsetWidth);
          this.tab = idx;
        });
      }
      // Initial task fetch
      this.refreshTasks();
    },

    // ── Navigation ─────────────────────────────────
    goTo(idx) {
      this.tab = idx;
      const panels = this.$refs.panels;
      if (panels) {
        panels.scrollTo({ left: idx * panels.offsetWidth, behavior: 'smooth' });
      }
    },

    // ── Chat ───────────────────────────────────────
    async send() {
      const text = this.message.trim();
      if (!text || this.isLoading) return;

      this.history.push({ role: 'user', content: text });
      this.message = '';
      this.isLoading = true;
      this.scrollChat();

      try {
        const res = await fetch('/chat/message', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text }),
        });
        const data = await res.json();

        if (data.response) {
          this.history.push({ role: 'assistant', content: data.response });
        }
        this.status = data.state || 'ready';
        this.tasks = data.tasks || [];
        if (data.code) this.code = data.code;
        if (data.suggested_filename) this.savePath = data.suggested_filename;
        if (data.execution_log && data.execution_log.length) {
          this.executionLog = this.formatLog(data.execution_log);
        }

        // TTS playback
        if (data.voice_audio) {
          this.voiceAudio = data.voice_audio;
          this.$nextTick(() => {
            const audio = this.$refs.ttsPlayer;
            if (audio) audio.play().catch(() => {});
          });
        }
      } catch (err) {
        this.history.push({ role: 'assistant', content: 'Connection error. Is the server running?' });
        this.toast('Connection error');
      }

      this.isLoading = false;
      this.scrollChat();
    },

    scrollChat() {
      this.$nextTick(() => {
        const el = this.$refs.messages;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },

    // ── Tasks ──────────────────────────────────────
    async refreshTasks() {
      try {
        const res = await fetch('/chat/tasks');
        const data = await res.json();
        this.tasks = data.tasks || [];
        this.choices = data.choices || [];
      } catch (e) {
        // silent
      }
    },

    async selectTask(task) {
      this.selectedTaskId = task.id;
      const choiceStr = this.choices.find(c => c.startsWith(task.id)) || '';
      if (!choiceStr) return;

      try {
        const res = await fetch('/chat/select-task', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task_choice: choiceStr }),
        });
        const data = await res.json();
        this.selectedTaskDetails = data.details || '';
        if (data.suggested_filename) this.savePath = data.suggested_filename;
      } catch (e) {
        this.toast('Failed to select task');
      }
    },

    async executeTask() {
      if (this.isExecuting) return;
      this.isExecuting = true;
      this.executionLog = '';

      try {
        const res = await fetch('/chat/execute', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ task_id: this.selectedTaskId }),
        });
        const data = await res.json();

        if (data.code) this.code = data.code;
        if (data.execution_log) {
          this.executionLog = this.formatLog(data.execution_log);
        }

        if (data.success) {
          this.toast('Build complete!');
        } else {
          this.toast(data.status || 'Build failed');
        }

        await this.refreshTasks();
      } catch (e) {
        this.toast('Execution error');
      }

      this.isExecuting = false;
    },

    // ── Code ───────────────────────────────────────
    async refreshCode() {
      try {
        const res = await fetch('/chat/code');
        const data = await res.json();
        if (data.filename) {
          this.code = data.content || '';
          this.savePath = data.filename;
        } else {
          this.code = data.content || 'No files found';
        }
        this.toast('Code refreshed');
      } catch (e) {
        this.toast('Failed to refresh code');
      }
    },

    // ── Voice (Browser SpeechRecognition) ──────────
    toggleRecording() {
      if (this.isRecording) {
        this._recognition && this._recognition.stop();
        this.isRecording = false;
        return;
      }

      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SR) {
        this.toast('Speech recognition not supported');
        return;
      }

      const recognition = new SR();
      recognition.lang = 'en-US';
      recognition.interimResults = false;
      recognition.maxAlternatives = 1;

      recognition.onresult = (event) => {
        const text = event.results[0][0].transcript;
        this.message = text;
        this.isRecording = false;
      };
      recognition.onerror = () => {
        this.isRecording = false;
        this.toast('Voice input failed');
      };
      recognition.onend = () => {
        this.isRecording = false;
      };

      this._recognition = recognition;
      recognition.start();
      this.isRecording = true;
    },

    // ── Location ───────────────────────────────────
    shareLocation() {
      if (!navigator.geolocation) {
        this.locationStatus = 'Geolocation not supported';
        return;
      }

      this.locationStatus = 'Getting location...';
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          const { latitude, longitude, accuracy } = pos.coords;
          try {
            await fetch('/location', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ latitude, longitude, accuracy, source: 'pwa' }),
            });
            this.locationStatus = `${latitude.toFixed(4)}, ${longitude.toFixed(4)} (${accuracy.toFixed(0)}m)`;
            this.toast('Location shared');
          } catch (e) {
            this.locationStatus = 'Failed to save location';
          }
        },
        (err) => {
          this.locationStatus = `Error: ${err.message}`;
        },
        { enableHighAccuracy: true, timeout: 10000 }
      );
    },

    // ── Reset ──────────────────────────────────────
    async resetAll() {
      try {
        await fetch('/chat/reset', { method: 'POST' });
        this.history = [];
        this.tasks = [];
        this.choices = [];
        this.selectedTaskId = null;
        this.selectedTaskDetails = '';
        this.code = '# Start a conversation to generate code';
        this.savePath = '/workspace/script.py';
        this.executionLog = '';
        this.status = 'ready';
        this.toast('Reset complete');
      } catch (e) {
        this.toast('Reset failed');
      }
    },

    // ── Helpers ────────────────────────────────────
    formatLog(log) {
      if (!log || !log.length) return '';
      return log.map((entry, i) => {
        if (entry.type === 'fix_attempt') {
          const fix = entry.fix || {};
          const result = entry.result || {};
          const icon = result.success ? '\u2705' : '\u274c';
          return `\ud83d\udd27 Fix ${entry.iteration || '?'}: ${fix.description || ''}\n   ${icon}`;
        }
        const step = entry.step || {};
        const result = entry.result || {};
        const icon = result.success ? '\u2705' : '\u274c';
        return `[${i + 1}] ${step.description || 'Step'}\n    ${step.action || ''} ${icon}`;
      }).join('\n\n');
    },

    statusIcon(s) {
      return { pending: '\u23f3', queued: '\u23f3', in_progress: '\ud83d\udd04', complete: '\u2705', failed: '\u274c' }[s] || '\u2753';
    },

    toast(msg) {
      this.toastMsg = msg;
      clearTimeout(this.toastTimeout);
      this.toastTimeout = setTimeout(() => { this.toastMsg = ''; }, 2500);
    },
  };
}
