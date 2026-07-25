"""Two-to-three-word titles for new chat threads.

Chainlit names a thread after the user's first message VERBATIM
(`emitter.init_thread` -> `data_layer.update_thread(name=<whole message>)`),
so the history sidebar fills up with paragraphs that all start the same way.
This module turns that first message into a short title; the Chainlit wiring
lives in `chainlit_app.auto_name_thread`, which persists it once the turn is
over — after Chainlit's own naming, otherwise the verbatim name wins the race.

UI-free and provider-agnostic: it only needs an object with `stream_chat`
(chat/providers.py's LLMClient), so the logic stays plain-pytest testable.
Never raises — a title is a nicety, and a dead title model must not take a
conversation down with it: the model's answer is cleaned, and anything
unusable falls back to the first words of the user's own message.
"""

MAX_WORDS = 3
MAX_CHARS = 40
# A title is a handful of tokens; the cap keeps a stray "let me explain..."
# from costing a full reply's worth of generation.
TITLE_MAX_TOKENS = 64
# The model only needs the gist of the opening message to name the chat.
SEED_MAX_CHARS = 2000

SYSTEM_PROMPT = (
    'You name chat conversations. Given the first message of a chat, reply '
    'with a title of two or three words that says what the conversation is '
    'about. Write it in the language of the message. Reply with the title '
    'ONLY — no quotes, no punctuation, no explanation, no trailing period.'
)

USER_TEMPLATE = 'First message of the chat:\n\n{seed}\n\nTitle:'

# Wrappers and stray punctuation models put around a title.
_STRIP_CHARS = ' \t\r\n"\'`«»*_#.:;,!?…-–—'
_LABEL_PREFIXES = ('title:', 'titre:', 'chat title:', 'conversation title:')


def seed_text(content) -> str:
    """The part of the first message the namer looks at (trimmed, bounded)."""
    if not isinstance(content, str):
        return ''
    return content.strip()[:SEED_MAX_CHARS]


def build_messages(seed: str) -> list[dict]:
    """Canonical (OpenAI-style) history for the naming call — one user turn."""
    return [{'role': 'user', 'content': USER_TEMPLATE.format(seed=seed)}]


def _words(text: str) -> list[str]:
    """Up to MAX_WORDS words, each stripped of decoration; stops at the
    first line break so a chatty model's second line is ignored."""
    first_line = next((line for line in text.splitlines() if line.strip()), '')
    lowered = first_line.strip().lower()
    for prefix in _LABEL_PREFIXES:
        if lowered.startswith(prefix):
            first_line = first_line.strip()[len(prefix):]
            break
    words = []
    for raw in first_line.split():
        word = raw.strip(_STRIP_CHARS)
        if word:
            words.append(word)
        if len(words) == MAX_WORDS:
            break
    return words


def _assemble(words: list[str]) -> str:
    """Join words into a title, bounded by MAX_CHARS on a word boundary and
    starting with a capital (the rest of the casing is left alone, so
    acronyms and product names survive)."""
    title = ''
    for word in words:
        candidate = f'{title} {word}'.strip()
        if title and len(candidate) > MAX_CHARS:
            break
        title = candidate
    title = title[:MAX_CHARS].strip(_STRIP_CHARS)
    if title and title[0].islower():
        title = title[0].upper() + title[1:]
    return title


def clean_title(raw) -> str:
    """A model answer reduced to a two-to-three word title ('' if there is
    nothing usable in it)."""
    if not isinstance(raw, str):
        return ''
    return _assemble(_words(raw))


def fallback_title(seed: str) -> str:
    """Title from the user's own opening words — used when the model is
    unavailable or answers with nothing usable."""
    return _assemble(_words(seed))


async def generate_title(llm, model: str, content) -> str | None:
    """Short title for a chat that opens with `content`, or None when there
    is nothing to name it after (empty first message)."""
    seed = seed_text(content)
    if not seed:
        return None
    raw = ''
    try:
        result = await llm.stream_chat(
            model=model, system=SYSTEM_PROMPT, messages=build_messages(seed))
        raw = getattr(result, 'text', '') or ''
    except Exception as e:  # a title is never worth failing the turn over
        print(f'[assistant] chat naming unavailable: {e}')
    return clean_title(raw) or fallback_title(seed) or None
