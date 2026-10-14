import asyncio
from langdetect import detect, LangDetectException
from deep_translator import GoogleTranslator

async def detect_lang(text):
    try:
        lang = await asyncio.to_thread(detect,text)
        return lang if lang in ['ru', 'en'] else 'en'

    
    except LangDetectException:
        return 'en'
    

async def translate_text(text, source_lang):
    target_lang = 'en' if source_lang == 'ru' else 'ru'
    try:
        translator = GoogleTranslator(
            source=source_lang, target=target_lang
            )
        translated = await asyncio.to_thread(translator.translate, 
                                             text)
        return translated, target_lang
    except Exception as e:
        print(f'Ошибка при переводе: {e}')
        return "Ошибка перевода", target_lang