"""
fluency.py — Text-to-speech pre-processor for BlackZero agents.

Converts raw LLM output into speech-ready text.
Removes markdown, handles numbers, adds natural pauses,
fixes abbreviations TTS engines commonly mispronounce.

This is the shared foundation. Each agent applies it before speaking.
Their voice_profile.py layers personality on top — this layer just
makes the raw output sound like a human said it.
"""

from __future__ import annotations

import re


# ── Markdown stripping ─────────────────────────────────────────────────────────

def strip_markdown(text: str) -> str:
    """Remove markdown formatting that sounds wrong when spoken."""
    # Code blocks
    text = re.sub(r'```[\s\S]*?```', '[code block]', text)
    text = re.sub(r'`[^`]+`', lambda m: m.group(0)[1:-1], text)
    # Headers
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Bold/italic
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
    # Links — keep the label, drop the URL
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # Bullet points → natural flow
    text = re.sub(r'^\s*[-*•]\s+', '', text, flags=re.MULTILINE)
    # Numbered lists → spoken transition words
    text = _convert_numbered_list(text)
    # Horizontal rules
    text = re.sub(r'\n[-*_]{3,}\n', '\n', text)
    return text.strip()


def _convert_numbered_list(text: str) -> str:
    """Convert '1. item\n2. item' to 'First, item. Second, item.'"""
    ordinals = ['First', 'Second', 'Third', 'Fourth', 'Fifth',
                'Sixth', 'Seventh', 'Eighth', 'Ninth', 'Tenth']
    counter = [0]

    def replace(m: re.Match) -> str:
        i = counter[0]
        counter[0] += 1
        label = ordinals[i] if i < len(ordinals) else f'Number {i+1}'
        return f'{label}, '

    return re.sub(r'^\s*\d+\.\s+', replace, text, flags=re.MULTILINE)


# ── Number conversion ──────────────────────────────────────────────────────────

_ONES = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven',
         'eight', 'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen',
         'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen']
_TENS = ['', '', 'twenty', 'thirty', 'forty', 'fifty',
         'sixty', 'seventy', 'eighty', 'ninety']


def _num_to_words(n: int) -> str:
    if n < 0:
        return 'negative ' + _num_to_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ('' if n % 10 == 0 else '-' + _ONES[n % 10])
    if n < 1000:
        rest = n % 100
        return _ONES[n // 100] + ' hundred' + ('' if rest == 0 else ' ' + _num_to_words(rest))
    if n < 1_000_000:
        rest = n % 1000
        return _num_to_words(n // 1000) + ' thousand' + ('' if rest == 0 else ' ' + _num_to_words(rest))
    return str(n)  # give up on huge numbers


def naturalize_numbers(text: str) -> str:
    """
    Convert small standalone integers to words for more natural speech.
    Leaves large numbers, decimals, percentages, and times as-is.
    """
    def replace_num(m: re.Match) -> str:
        raw = m.group(0)
        n = int(raw.replace(',', ''))
        # Leave large numbers, years, and things like "stop 14" alone
        if n > 999 or raw.startswith('0'):
            return raw
        return _num_to_words(n)

    # Only convert isolated small integers (not inside IDs, versions, etc.)
    return re.sub(r'(?<!\w)(\d{1,3})(?!\w|%|:|\.|\d)', replace_num, text)


# ── Abbreviation expansion ─────────────────────────────────────────────────────

_ABBREVS = {
    r'\bAPI\b': 'A P I',
    r'\bAPIs\b': 'A P I s',
    r'\bUI\b': 'U I',
    r'\bUX\b': 'U X',
    r'\bURL\b': 'U R L',
    r'\bURLs\b': 'U R L s',
    r'\bSQL\b': 'S Q L',
    r'\bHTTP\b': 'H T T P',
    r'\bHTTPS\b': 'H T T P S',
    r'\bJSON\b': 'Jason',
    r'\bYAML\b': 'yam-ul',
    r'\bML\b': 'M L',
    r'\bAI\b': 'A I',
    r'\bRAG\b': 'rag',
    r'\bLLM\b': 'L L M',
    r'\bLLMs\b': 'L L M s',
    r'\bPR\b': 'P R',
    r'\bCI\b': 'C I',
    r'\bCD\b': 'C D',
    r'\be\.g\.\b': 'for example',
    r'\bi\.e\.\b': 'that is',
    r'\betc\.\b': 'and so on',
    r'\bvs\.\b': 'versus',
    r'\bAKA\b': 'also known as',
    r'\bFYI\b': 'for your info',
    r'\bETA\b': 'E T A',
    r'\bGPS\b': 'G P S',
    r'\bPTT\b': 'push to talk',
}


def expand_abbreviations(text: str) -> str:
    for pattern, replacement in _ABBREVS.items():
        text = re.sub(pattern, replacement, text)
    return text


# ── Pause insertion ────────────────────────────────────────────────────────────

def insert_pauses(text: str, style: str = 'natural') -> str:
    """
    Add SSML-style pause hints or punctuation for natural cadence.
    style='natural'  — uses commas and periods for pacing
    style='ssml'     — uses <break> tags (for ElevenLabs / Google TTS)
    """
    if style == 'ssml':
        # Add short breaks after list items and longer after sentences
        text = re.sub(r'\.\s+', '. <break time="400ms"/> ', text)
        text = re.sub(r',\s+', ', <break time="150ms"/> ', text)
        return text

    # Natural: ensure sentences end with proper punctuation
    text = re.sub(r'([a-z])\n([A-Z])', r'\1. \2', text)
    # Collapse multiple spaces
    text = re.sub(r'  +', ' ', text)
    return text


# ── Filler and hedge removal ───────────────────────────────────────────────────

_FILLERS = [
    r'\bCertainly[,!]?\s*',
    r'\bAbsolutely[,!]?\s*',
    r'\bOf course[,!]?\s*',
    r'\bGreat question[,!]?\s*',
    r'\bSure[,!]?\s*',
    r'\bDefinitely[,!]?\s*',
    r'\bI\'d be happy to\s+',
    r'\bI\'m glad you asked\s*[,.]?\s*',
    r'\bAs an AI[,]?\s*',
    r'\bAs a language model[,]?\s*',
]


def remove_fillers(text: str) -> str:
    """Strip sycophantic openers that sound hollow when spoken aloud."""
    for pattern in _FILLERS:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    # Clean up any resulting double spaces or leading whitespace
    text = re.sub(r'^\s+', '', text)
    text = re.sub(r'  +', ' ', text)
    # Capitalize first letter if we stripped the opener
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


# ── Sentence length check ─────────────────────────────────────────────────────

def trim_for_speech(text: str, max_chars: int = 600) -> str:
    """
    Hard trim for spoken output — very long responses need to be shortened.
    Cuts at a sentence boundary near max_chars.
    """
    if len(text) <= max_chars:
        return text
    # Find the last sentence end before the limit
    chunk = text[:max_chars]
    last_end = max(chunk.rfind('.'), chunk.rfind('!'), chunk.rfind('?'))
    if last_end > max_chars // 2:
        return text[:last_end + 1]
    return chunk + '...'


# ── Master pipeline ────────────────────────────────────────────────────────────

def prepare_for_speech(
    text: str,
    remove_sycophancy: bool = True,
    naturalize_nums: bool = True,
    ssml: bool = False,
    max_chars: int = 0,
) -> str:
    """
    Full pipeline. Run LLM output through this before handing to TTS.

    Order matters:
      1. Remove sycophantic openers
      2. Strip markdown
      3. Expand abbreviations
      4. Naturalize numbers
      5. Insert pauses
      6. Trim if needed
    """
    if remove_sycophancy:
        text = remove_fillers(text)
    text = strip_markdown(text)
    text = expand_abbreviations(text)
    if naturalize_nums:
        text = naturalize_numbers(text)
    text = insert_pauses(text, style='ssml' if ssml else 'natural')
    if max_chars > 0:
        text = trim_for_speech(text, max_chars)
    return text.strip()
