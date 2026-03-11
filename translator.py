"""
Translation provider for subtitle segments using ChatGPT (OpenAI API).
Translate English segment text to a target language.
Set OPENAI_API_KEY environment variable to enable translation.
"""
import os
from typing import Callable

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, will use environment variables only

# OpenAI API key from environment
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Debug: Print if API key is loaded (first 10 chars only for security)
if OPENAI_API_KEY:
    print(f"✅ OpenAI API key loaded: {OPENAI_API_KEY[:10]}...")
else:
    print("⚠️  OPENAI_API_KEY not found. Translation will return original text.")

# Language code to language name mapping for ChatGPT
LANGUAGE_NAMES = {
    "ar": "Arabic",
    "es": "Spanish",
    "fr": "French",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "de": "German",
    "pt": "Portuguese",
    "zh": "Chinese",
    "ja": "Japanese",
    "ko": "Korean",
    "it": "Italian",
    "ru": "Russian",
    "nl": "Dutch",
    "pl": "Polish",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "th": "Thai",
    "id": "Indonesian",
}


def _translate_stub(_target_lang: str, text: str) -> str:
    """Stub: return original text when OpenAI API key is not configured."""
    return text


def _translate_chatgpt(target_lang: str, text: str) -> str:
    """Translate text using ChatGPT (OpenAI API)."""
    if not text.strip():
        return text
    
    # Check API key dynamically from environment
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print(f"⚠️  No API key found. Returning original text: {text[:50]}...")
        return text
    
    try:
        from openai import OpenAI
        
        client = OpenAI(api_key=api_key)
        
        # Get language name, fallback to code if not found
        language_name = LANGUAGE_NAMES.get(target_lang.lower(), target_lang.upper())
        
        # Create translation prompt
        prompt = f"""Translate the following English subtitle text to {language_name}. 
Return only the translation, no explanations or additional text.
Preserve the tone, style, and meaning. Keep it concise and natural.

English text: {text}

Translation:"""
        
        # Get model from settings, default to gpt-4o-mini
        model = os.environ.get("GPT_MODEL", "gpt-4o-mini")
        
        print(f"🔄 Translating to {language_name} using {model}: {text[:50]}...")
        print(f"🔑 API Key (first 10 chars): {api_key[:10]}...")
        
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": f"You are a professional translator specializing in subtitle translation from English to {language_name}."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,  # Lower temperature for more consistent translations
            max_tokens=500,
        )
        
        translated = response.choices[0].message.content.strip()
        print(f"✅ Translated: {translated[:100]}...")
        print(f"📊 Original: {text[:100]}")
        print(f"📊 Translated length: {len(translated)}, Original length: {len(text)}")
        return translated if translated else text
        
    except ImportError as e:
        print(f"⚠️  OpenAI package not installed: {e}")
        print("   Install with: pip install openai")
        return text
    except Exception as e:
        print(f"❌ Translation error: {type(e).__name__}: {e}")
        print(f"   Error details: {str(e)}")
        import traceback
        traceback.print_exc()
        return text


def get_translator(target_lang: str) -> Callable[[str], str]:
    """
    Return a callable that translates English text to target_lang using ChatGPT.
    translate(english_text) -> translated_text
    
    Requires OPENAI_API_KEY environment variable to be set.
    """
    # Check API key dynamically (in case .env was loaded after module import)
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if api_key:
        model = os.environ.get("GPT_MODEL", "gpt-4o-mini")
        print(f"✅ Using ChatGPT ({model}) translation for {target_lang}")
        return lambda text: _translate_chatgpt(target_lang, text)
    else:
        print(f"⚠️  No OPENAI_API_KEY found. Using stub translation for {target_lang}")
        return lambda text: _translate_stub(target_lang, text)
