"""
Translation provider for subtitle segments using multiple AI models:
- OpenAI (GPT models)
- Google Gemini
- Anthropic Claude

Configure via environment variables or settings page.
"""
import os
from typing import Callable

# Load .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Language code to language name mapping
LANGUAGE_NAMES = {
    "ar": "Arabic", "es": "Spanish", "fr": "French", "hi": "Hindi",
    "ta": "Tamil", "te": "Telugu", "de": "German", "pt": "Portuguese",
    "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "it": "Italian",
    "ru": "Russian", "nl": "Dutch", "pl": "Polish", "tr": "Turkish",
    "vi": "Vietnamese", "th": "Thai", "id": "Indonesian",
}

# Available models
MODELS = {
    "openai": [
        "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4",
        "gpt-3.5-turbo", "gpt-3.5-turbo-16k"
    ],
    "gemini": [
        "gemini-2.0-flash-exp", "gemini-1.5-pro", "gemini-1.5-flash",
        "gemini-1.0-pro"
    ],
    "claude": [
        "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229", "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307"
    ]
}


def _translate_stub(_target_lang: str, text: str) -> str:
    """Return original text when no API key is configured."""
    return text


def _translate_openai(target_lang: str, text: str, model: str, api_key: str) -> str:
    """Translate using OpenAI GPT models."""
    if not text.strip():
        return text
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        language_name = LANGUAGE_NAMES.get(target_lang.lower(), target_lang.upper())
        
        prompt = f"""Translate the following subtitle text to {language_name}. 
Return only the translation, no explanations.
If the text has multiple lines, translate each line and preserve the line breaks.
Preserve tone, style, and meaning. Keep it concise and natural.

Text:
{text}

Translation:"""
        
        print(f"🔄 Translating to {language_name} using OpenAI {model}")
        print(f"📝 Original ({len(text)} chars, {text.count(chr(10))} line breaks): {repr(text[:100])}")
        
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": f"You are a professional translator for {language_name} subtitles."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=500,
        )
        
        translated = response.choices[0].message.content.strip()
        print(f"✅ Translated ({len(translated)} chars, {translated.count(chr(10))} line breaks): {repr(translated[:100])}")
        return translated if translated else text
        
    except Exception as e:
        print(f"❌ OpenAI translation error: {e}")
        return text


def _translate_gemini(target_lang: str, text: str, model: str, api_key: str) -> str:
    """Translate using Google Gemini."""
    if not text.strip():
        return text
    
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        client = genai.GenerativeModel(model)
        language_name = LANGUAGE_NAMES.get(target_lang.lower(), target_lang.upper())
        
        prompt = f"""Translate the following subtitle text to {language_name}. 
Return only the translation, no explanations.
If the text has multiple lines, translate each line and preserve the line breaks.
Preserve tone, style, and meaning. Keep it concise and natural.

Text:
{text}

Translation:"""
        
        print(f"🔄 Translating to {language_name} using Gemini {model}")
        print(f"📝 Original ({len(text)} chars, {text.count(chr(10))} line breaks): {repr(text[:100])}")
        
        response = client.generate_content(prompt)
        translated = response.text.strip()
        
        print(f"✅ Translated ({len(translated)} chars, {translated.count(chr(10))} line breaks): {repr(translated[:100])}")
        return translated if translated else text
        
    except Exception as e:
        print(f"❌ Gemini translation error: {e}")
        return text


def _translate_claude(target_lang: str, text: str, model: str, api_key: str) -> str:
    """Translate using Anthropic Claude."""
    if not text.strip():
        return text
    
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        language_name = LANGUAGE_NAMES.get(target_lang.lower(), target_lang.upper())
        
        prompt = f"""Translate the following subtitle text to {language_name}. 
Return only the translation, no explanations.
If the text has multiple lines, translate each line and preserve the line breaks.
Preserve tone, style, and meaning. Keep it concise and natural.

Text:
{text}

Translation:"""
        
        print(f"🔄 Translating to {language_name} using Claude {model}")
        print(f"📝 Original ({len(text)} chars, {text.count(chr(10))} line breaks): {repr(text[:100])}")
        
        response = client.messages.create(
            model=model,
            max_tokens=500,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}]
        )
        
        translated = response.content[0].text.strip()
        
        print(f"✅ Translated ({len(translated)} chars, {translated.count(chr(10))} line breaks): {repr(translated[:100])}")
        return translated if translated else text
        
    except Exception as e:
        print(f"❌ Claude translation error: {e}")
        return text


def get_translator(target_lang: str) -> Callable[[str], str]:
    """
    Return a translation function based on configured provider and model.
    Checks environment for:
    - TRANSLATION_PROVIDER: "openai", "gemini", or "claude"
    - TRANSLATION_MODEL: specific model name
    - API keys: OPENAI_API_KEY, GEMINI_API_KEY, CLAUDE_API_KEY
    """
    provider = os.environ.get("TRANSLATION_PROVIDER", "openai").lower()
    model = os.environ.get("TRANSLATION_MODEL", "")
    
    # Default models if not specified
    if not model:
        if provider == "gemini":
            model = "gemini-1.5-flash"
        elif provider == "claude":
            model = "claude-3-5-haiku-20241022"
        else:
            model = "gpt-4o-mini"
    
    # Get API key
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if api_key:
            print(f"✅ Using OpenAI {model} for translation")
            return lambda text: _translate_openai(target_lang, text, model, api_key)
    elif provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if api_key:
            print(f"✅ Using Gemini {model} for translation")
            return lambda text: _translate_gemini(target_lang, text, model, api_key)
    elif provider == "claude":
        api_key = os.environ.get("CLAUDE_API_KEY", "")
        if api_key:
            print(f"✅ Using Claude {model} for translation")
            return lambda text: _translate_claude(target_lang, text, model, api_key)
    
    print(f"⚠️  No API key found for {provider}. Using stub translation.")
    return lambda text: _translate_stub(target_lang, text)
