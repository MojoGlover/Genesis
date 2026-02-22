"""watchdog/config.py — log monitoring config for Computer Black apps."""

WATCHDOG_CONFIG = {
    "madjanet": {
        "package":    "com.computerblack.madjanet",
        "tag_filter": ["ReactNative", "MadJanet", "ExpoSpeech", "AndroidRuntime"],
        "crash_patterns": [
            "FATAL EXCEPTION",
            "AndroidRuntime",
            "Process.*died",
            "java.lang.RuntimeException",
            "signal 11",     # SIGSEGV
            "signal 6",      # SIGABRT
        ],
        "ignore_patterns": [
            "eglCodecCommon",   # harmless GPU noise
            "OpenGLRenderer",
            "Choreographer",
        ],
    },
}

# How many lines of historical log to show on startup
DEFAULT_TAIL_LINES = 50

# ANSI colors for terminal output
COLORS = {
    "error":   "\033[91m",   # bright red
    "warn":    "\033[93m",   # yellow
    "info":    "\033[94m",   # blue
    "crash":   "\033[41m",   # red background
    "reset":   "\033[0m",
    "green":   "\033[92m",
    "gray":    "\033[90m",
}
