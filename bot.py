import asyncio
import logging
from os import getenv
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
    )

from database import (
    init_db, User, VocabularyWord, async_session_maker, 
    get_user_words, get_user_words_count
    )
from sqlalchemy import select
from translator import detect_lang, translate_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

load_dotenv()
BOT_TOKEN = getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

router = Router()
dp.include_router(router)


MENU_BTNS = {'Пройти тест', 'Мой словарь', 'Моя статистика', 'Помощь'}


def get_main_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text='Пройти тест'),
            KeyboardButton(text='Мой словарь')],
            [KeyboardButton(text='Моя статистика'),
            KeyboardButton(text='Помощь')]
        ],
        resize_keyboard=True,
        input_field_placeholder='Выберите действие из меню'
    )
    return keyboard

@router.message(Command('start'))
async def cmd_start(message: Message):
    await message.answer(
        text='Привет! Я бот по изучению англиского языка',
        reply_markup=get_main_keyboard()
    )


@router.message(F.text == 'Мой словарь')
async def show_vocal(message: Message):
    telegram_id = message.from_user.id 
    words = await get_user_words(telegram_id, offset=0, limit=5)
    total_count = await get_user_words_count(telegram_id)

    if not words:
        await message.answer("Твой словарь пока пуст")
        return
    text = f'Твой словарь ({total_count} слов)\n\n'
    for i, word in enumerate(words, start=1):
        text += f'{i}. {word.original_text} -> {word.translate_text}\n'

    keyboard_buttons = []
    if total_count > 5:
        keyboard_buttons.append([
            InlineKeyboardButton(text='->Следующие', 
                                 callback_data="dict_page_1")
        ])
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons) if keyboard_buttons else None
    await message.answer(text, reply_markup=keyboard)

@router.message(F.text, ~F.text.stratswidth('/'))
async def handle_message(message: Message, state: FSMContext):
    text = message.text.strip()

    if text in MENU_BTNS:
        return

    if not text:
        return 
    
    loading_msg = await message.answer('Перевожу...')
    source_lang = await detect_lang(text)

    translated, target_lang = await translate_text(text, source_lang)

    await state.update_data(
        original=text,
        translated=translated,
        source_lang=source_lang,
        target_lang=target_lang
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='+ Добавить в словарь',
                              callback_data="add_to_dict")]
    ])
    await loading_msg.delete()
    await message.answer(
        text=f"Перевод: ({source_lang}->{target_lang}):\n\n({translated})",
        reply_markup=keyboard
    )

@router.callback_query(F.data == "add_to_dict")
async def process_add_to_dict(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    if not data.get('original'):
        await callback.answer("Данные устарели", show_alert=True)
        return
    user_telegram_id = callback.from_user.id
    async with async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == user_telegram_id)
            )
        user = result.scalar_one_or_none()
        if not user:
            user = User(telegram_id=user_telegram_id)
            session.add(user)
            await session.flush()

        new_word = VocabularyWord(
            user_id=user.id,
            original_text=data['original'],
            translate_text=data['translated'],
            source_lang=data['source_lang'],
            target_lang=data['target_lang']
        )
        session.add(new_word)
        await session.commit()
    
    await callback.message.edit_reply_markup(reply_markup=None)

    await callback.answer('Добавлено в словарь!', show_alert=True)
    await state.clear()



        

async def main():
    """ запуск процесса поллинга """
    logger = logging.getLogger(__name__)

    await init_db()

    logger.info('Бот готов к работе')
    
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())

