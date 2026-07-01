"""
Generic AI parser that can work with different providers (Mistral, Anthropic, OpenAI, etc.)
Uses a unified interface with provider-specific implementations.
"""

import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import requests


class AIProvider:
    """Base class for AI providers"""
    
    def __init__(self, api_key: str, base_url: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
    
    def parse_task(self, text: str, system_prompt: str) -> List[Dict[str, Any]]:
        """Parse text and return task information"""
        raise NotImplementedError

    def cleanify(self, note_text: str, system_prompt: str) -> str:
        """Tidy a note's markdown text via the LLM, returning raw model text.

        Mirrors `parse_task`'s HTTP setup but returns the raw model text rather
        than extracting a JSON list of task dicts. No JSON parsing is performed
        on the response.
        """
        raise NotImplementedError

    def _process_response(self, response_text: str) -> List[Dict[str, Any]]:
        """Process raw response text to extract task data"""
        # Try to extract JSON from the response
        # Sometimes models might include markdown code blocks
        if '```json' in response_text:
            json_start = response_text.find('```json') + 7
            json_end = response_text.find('```', json_start)
            response_text = response_text[json_start:json_end].strip()
        elif '```' in response_text:
            json_start = response_text.find('```') + 3
            json_end = response_text.find('```', json_start)
            response_text = response_text[json_start:json_end].strip()
        
        result = json.loads(response_text)
        
        # Handle both single task and multiple tasks
        if isinstance(result, dict):
            tasks = [result]
        else:
            tasks = result
        
        # Process deadline for each task - convert relative dates to absolute
        for task in tasks:
            if task.get('deadline'):
                deadline_str = task['deadline'].lower()
                now = datetime.now()
                
                if 'tomorrow' in deadline_str:
                    deadline = now + timedelta(days=1)
                    deadline = deadline.replace(hour=23, minute=59, second=0, microsecond=0)
                elif 'next week' in deadline_str:
                    deadline = now + timedelta(weeks=1)
                    deadline = deadline.replace(hour=23, minute=59, second=0, microsecond=0)
                elif 'next' in deadline_str and 'monday' in deadline_str:
                    days_ahead = 7 - now.weekday()
                    deadline = now + timedelta(days=days_ahead)
                    deadline = deadline.replace(hour=23, minute=59, second=0, microsecond=0)
                elif 'next' in deadline_str and 'friday' in deadline_str:
                    days_ahead = (4 - now.weekday() + 7) % 7
                    if days_ahead == 0:
                        days_ahead = 7
                    deadline = now + timedelta(days=days_ahead)
                    deadline = deadline.replace(hour=23, minute=59, second=0, microsecond=0)
                else:
                    deadline = datetime.fromisoformat(task['deadline'].replace('Z', '+00:00'))
                
                if deadline:
                    task['deadline'] = deadline.isoformat()
        
        return tasks


class OpenAIProvider(AIProvider):
    """OpenAI-compatible API provider (works with Mistral, OpenAI, etc.)"""
    
    def parse_task(self, text: str, system_prompt: str) -> List[Dict[str, Any]]:
        """Use OpenAI-compatible API to parse tasks"""
        if not self.api_key:
            # Fallback to simple parsing if no API key
            return [{
                'title': text[:100],
                'description': text,
                'space_id': None,
                'priority': 5,
                'deadline': None,
                'estimated_duration': 60
            }]
        
        # Add current date and time to the user message for context
        now = datetime.now()
        user_message = f"Current date and time: {now.strftime('%Y-%m-%d %H:%M')}.\n\nTask to parse:\n{text}"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        data = {
            "model": self.model or "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "max_tokens": 1024,
            "temperature": 0.3
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions" if self.base_url else "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=30
            )
            response.raise_for_status()
            response_data = response.json()
            
            # Extract the content from the response
            response_text = response_data['choices'][0]['message']['content']
            
            return self._process_response(response_text)
            
        except Exception as e:
            print(f"Error calling AI API: {e}")
            # Fallback to simple parsing
            return [{
                'title': text[:100],
                'description': text,
                'space_id': None,
                'priority': 5,
                'deadline': None,
                'estimated_duration': 60
            }]

    def cleanify(self, note_text: str, system_prompt: str) -> str:
        """Use OpenAI-compatible API to tidy a note. Returns raw model text."""
        if not self.api_key:
            # No API key: return the input unchanged (let the factory degrade).
            return note_text

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        data = {
            "model": self.model or "gpt-3.5-turbo",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": note_text}
            ],
            "max_tokens": 2048,
            "temperature": 0.3
        }

        response = requests.post(
            f"{self.base_url}/chat/completions" if self.base_url else "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=30
        )
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']


class AnthropicProvider(AIProvider):
    """Anthropic Claude provider"""
    
    def __init__(self, api_key: str, base_url: Optional[str] = None, model: Optional[str] = None):
        super().__init__(api_key, base_url, model)
        try:
            from anthropic import Anthropic
            self.client = Anthropic(api_key=api_key, base_url=base_url)
        except ImportError:
            self.client = None
    
    def parse_task(self, text: str, system_prompt: str) -> List[Dict[str, Any]]:
        """Use Anthropic Claude to parse tasks"""
        if not self.api_key or not self.client:
            # Fallback to simple parsing if no API key or client not available
            return [{
                'title': text[:100],
                'description': text,
                'space_id': None,
                'priority': 5,
                'deadline': None,
                'estimated_duration': 60
            }]
        
        # Add current date and time to the user message for context
        now = datetime.now()
        user_message = f"Current date and time: {now.strftime('%Y-%m-%d %H:%M')}.\n\nTask to parse:\n{text}"
        
        try:
            response = self.client.messages.create(
                model=self.model or "claude-haiku-4-5",
                max_tokens=1024,
                temperature=0.3,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_message}
                ]
            )
            
            # Extract text from response
            response_text = response.content[0].text
            
            return self._process_response(response_text)
            
        except Exception as e:
            print(f"Error calling Anthropic API: {e}")
            # Fallback to simple parsing
            return [{
                'title': text[:100],
                'description': text,
                'space_id': None,
                'priority': 5,
                'deadline': None,
                'estimated_duration': 60
            }]

    def cleanify(self, note_text: str, system_prompt: str) -> str:
        """Use Anthropic Claude to tidy a note. Returns raw model text."""
        if not self.api_key or not self.client:
            # No API key / no client: return input unchanged (factory degrades).
            return note_text

        response = self.client.messages.create(
            model=self.model or "claude-haiku-4-5",
            max_tokens=2048,
            temperature=0.3,
            system=system_prompt,
            messages=[
                {"role": "user", "content": note_text}
            ]
        )
        return response.content[0].text


def get_ai_provider() -> AIProvider:
    """Get the appropriate AI provider based on environment variables"""
    api_key = os.getenv('AI_API_KEY')
    base_url = os.getenv('AI_API_BASE_URL', 'https://api.openai.com/v1/')
    model = os.getenv('AI_MODEL', 'gpt-3.5-turbo')
    
    # Check if it's an Anthropic URL
    if 'anthropic.com' in base_url:
        return AnthropicProvider(api_key=api_key, base_url=base_url, model=model)
    else:
        # Default to OpenAI-compatible provider (works with Mistral, OpenAI, etc.)
        return OpenAIProvider(api_key=api_key, base_url=base_url, model=model)


def parse_task_with_ai(text: str, system_prompt: str) -> List[Dict[str, Any]]:
    """
    Parse a text input using AI to extract task information.
    
    Returns a list of task dictionaries. Each dictionary contains:
    - title: Task title
    - description: Task description
    - space_id: Space ID (numeric) or None
    - priority: Priority level (0-10)
    - deadline: ISO format datetime string or None
    - estimated_duration: Duration in minutes
    
    Note: The AI may return multiple tasks if the input clearly describes
    multiple distinct tasks, but will prefer returning a single task.
    """
    provider = get_ai_provider()
    return provider.parse_task(text, system_prompt)


def email_to_task_with_ai(subject: str, body: str, system_prompt: str) -> List[Dict[str, Any]]:
    """
    Derive task draft(s) from an email via AI. Reuses the `parse_task` seam
    (same deliberate choice as promote-to-task: no new AI code path) with the
    dedicated email-to-task system prompt.

    Graceful degradation: on any exception or empty response, returns a single
    trivial draft (title = subject, description = first 500 chars of body).
    """
    text = f"Subject: {subject}\n\n{body or ''}"
    try:
        drafts = get_ai_provider().parse_task(text, system_prompt)
        if drafts:
            return drafts
    except Exception:
        pass
    return [{
        'title': (subject or 'Email task')[:500],
        'description': (body or '')[:500],
        'space_id': None,
        'priority': 5,
        'deadline': None,
        'estimated_duration': 60,
    }]


def cleanify_note_with_ai(note_text: str, system_prompt: str) -> str:
    """
    Tidy a note's markdown text via AI. Returns cleaned text on success.

    Graceful degradation: on ANY exception or empty/None response, returns the
    input `note_text` unchanged. No exception escapes to the caller.
    """
    try:
        result = get_ai_provider().cleanify(note_text, system_prompt)
        if not result:
            return note_text
        return result
    except Exception:
        return note_text