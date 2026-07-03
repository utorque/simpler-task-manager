import os
from dotenv import load_dotenv

load_dotenv()

# Default fallback for the Cleanify prompt if the file is ever missing at
# startup (it is not expected to be, but Config must never crash app boot).
_NOTES_CLEANIFY_PROMPT_DEFAULT = (
    "You are a tidying assistant. Rewrite the note to make it more readable "
    "without changing its meaning, structured as: one '# Title' line, the "
    "note date in italics directly below it, '##' subtitles when the note "
    "covers several topics, key points in bold, and '-' bullets for details. "
    "Tidy punctuation, normalize line breaks and list formatting. Do not "
    "invent facts, summarize away specifics, or rename entities. If a "
    "section's intent is unclear, leave it unchanged rather than guessing. "
    "Output only the tidied note in markdown."
)


# Load the task-creation system prompt once on startup
def load_system_prompt():
    prompt_path = os.path.join(os.path.dirname(__file__), 'prompts', 'task_creation.md')
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return "You are a task parsing assistant. Extract task information and return JSON."


# Load the Cleanify system prompt once on startup (sibling to load_system_prompt).
# Loaded once at import time of config.py and cached on Config.NOTES_CLEANIFY_PROMPT;
# no per-request file reads on the hot path.
def load_notes_cleanify_prompt():
    prompt_path = os.path.join(os.path.dirname(__file__), 'prompts', 'notes_cleanify.md')
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return _NOTES_CLEANIFY_PROMPT_DEFAULT


_EMAIL_TO_TASK_PROMPT_DEFAULT = (
    "You are a task extraction assistant. The user message contains an email "
    "(subject then body). Derive the actionable task it asks of the recipient "
    "and return ONLY JSON with title, description, space_id, priority, "
    "deadline, estimated_duration."
)


def load_email_to_task_prompt():
    prompt_path = os.path.join(os.path.dirname(__file__), 'prompts', 'email_to_task.md')
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return _EMAIL_TO_TASK_PROMPT_DEFAULT


_TASK_SELECTION_PROMPT_DEFAULT = (
    "You are a task selection assistant. The user states what they want to "
    "work on; you are given a list of candidate TODO tasks with ids. Return "
    "ONLY a JSON array of the ids of the tasks matching the user's intent, "
    "e.g. [3, 12], or [] when nothing matches."
)


def load_task_selection_prompt():
    prompt_path = os.path.join(os.path.dirname(__file__), 'prompts', 'task_selection.md')
    try:
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return _TASK_SELECTION_PROMPT_DEFAULT

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = 'sqlite:///tasks.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # New generic AI configuration
    AI_API_KEY = os.getenv('AI_API_KEY')
    AI_API_BASE_URL = os.getenv('AI_API_BASE_URL', 'https://api.openai.com/v1/')
    AI_MODEL = os.getenv('AI_MODEL', 'gpt-3.5-turbo')
    APP_PASSWORD = os.getenv('APP_PASSWORD', 'admin')
    FLASK_ENV = os.getenv('FLASK_ENV', 'development')
    SYSTEM_PROMPT = load_system_prompt()
    NOTES_CLEANIFY_PROMPT = load_notes_cleanify_prompt()
    EMAIL_TO_TASK_PROMPT = load_email_to_task_prompt()
    TASK_SELECTION_PROMPT = load_task_selection_prompt()
