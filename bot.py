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

from states import TestStates
from database import save_results, get_test_result, TestResult
import random

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

load_dotenv()
BOT_TOKEN = getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

router = Router()
dp.include_router(router)


MENU_BTNS = {'Пройти тест', 'Мой словарь', 'Моя статистика', 'Помощь'}
FALLBACK_WORDS = [
    {"original": "apple", "translated": "яблоко"}, {"original": "book", "translated": "книга"},
    {"original": "cat", "translated": "кот"}, {"original": "dog", "translated": "собака"},
    {"original": "sun", "translated": "солнце"}, {"original": "water", "translated": "вода"},
    {"original": "house", "translated": "дом"}, {"original": "car", "translated": "машина"},
    {"original": "tree", "translated": "дерево"}, {"original": "friend", "translated": "друг"},
    {"original": "time", "translated": "время"}, {"original": "work", "translated": "работа"}
]

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


@router.message(F.text == 'Пройти тест')
async def start_test_menu(message:Message, state: FSMContext):
    await state.set_state(TestStates.choosing_category) 
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='По словарю',
                              callback_data='test_dict')],
        [InlineKeyboardButton(text='Случайные слова',
                              callback_data='test_random')]                      
    ])
    await message.answer('Выберите категорию: ',
                         reply_markup=keyboard)
    



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

# CALLBACK QUERY

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

@router.callback_query(F.data.startswith('dict_page_'))
async def handle_pagination(callback: CallbackQuery):
    page = int(callback.data.split('_')[-1])
    offset = page * 5
    telegram_id = callback.from_user.id
    words = await get_user_words(telegram_id, offset=offset, limit=5)
    total_count = await get_user_words_count(telegram_id)
    if not words:
        await callback.answer('Больше слов нет', show_alert=True)
    
    text = f'Твой словарь: ({page+1} страница)\n\n'
    for i, word in enumerate(words, start=offset + 1):
        text += f'{i}. {word.original_text} - {word.translate_text}\n'
    
    keyboard_buttons = []
    nav_row = []

    if page > 0 :
        nav_row.append(InlineKeyboardButton(text='<--Назад', 
                       callback_data=f'dict_page_{page-1}'))
    if offset+5 < total_count:
        nav_row.append(InlineKeyboardButton(text='Вперед-->', 
                       callback_data=f'dict_page_{page+1}'))
    if nav_row:
        keyboard_buttons.append(nav_row)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await callback.message.edit_text(text=text, 
                                     reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith('test_'), 
                       TestStates.choosing_category)
async def generate_test(callback:CallbackQuery, state:FSMContext):
    category = callback.data.split('_')[-1]
    words_pool = []
    if category == 'dict':
        user_words = await get_user_words(callback.from_user.id,
                                          offset=0, limit=100) 
        words_pool = [{'original': w.original_text,
                       'translated': w.translate_text}
                       for w in user_words] 
    if category == 'random' or len(words_pool) < 4:
        words_pool = FALLBACK_WORDS.copy()

    if len(words_pool) < 4:
        await callback.message.edit_text('Недостаточно слов')
        await state.clear()
        return

    random.shuffle(words_pool)
    questions = words_pool[:5]

    await state.update_data(
        questions=questions,
        current_q_index=0,
        score=0,
        category=category
    )
    await state.set_state(TestStates.in_test)

    # первый вопрос
    await send_question(callback.message, state)
    await callback.answer()

async def send_question(message: Message, state: FSMContext):
    data = await state.get_data()
    questions = data['questions']
    current_idx = data['current_q_index']

    if current_idx >= len(questions):
        await finish_test(message, state)
        return
    
    question = questions[current_idx]
    correct_answer = question['translated']

    all_translations = [w['translated'] for w in questions
                        if w['translated'] != correct_answer]
    random.shuffle(all_translations)
    options = [correct_answer] + all_translations[:3]
    random.shuffle(options)

    await state.update_data(
        current_options=options, correct_answer=correct_answer
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=opt, callback_data=f'answer_{i}')]
                              for i, opt in enumerate(options)
    ])

    await message.answer(
        f'Вопрос: {current_idx+1} из {len(questions)}\n\n'
        f'{question['original']} - как переводится?',
        reply_markup=keyboard
    )

@router.callback_query(F.data.startswith('answer_'), TestStates.in_test)
async def check_answer(callback:CallbackQuery, state:FSMContext):
    data = await state.get_data()
    selected_idx = int(callback.data.split('_')[-1])
    selected_answer = data['current_options'][selected_idx]
    correct_answer = data['correct_answer']
    is_correct = (selected_answer == correct_answer)
    new_score = data['score'] + (1 if is_correct else 0)
    await state.update_data(score=new_score)
    emoji = '✅' if is_correct else '❌'
    await callback.message.edit_text(
        f'{emoji}'
    )
    await callback.answer()

    await asyncio.sleep(2)
    await callback.message.delete()

    await state.update_data(current_q_index=data['current_q_index']+1)
    await send_question(callback.message, state)

async def finish_test(message:Message, state: FSMContext):
    data = await state.get_data()
    score = data['score']
    total = len(data['questions'])

    await save_results(message.from_user.id, score, total)
    await state.clear()

    await message.answer(
        f'Тест завершен'
        f'Результат: {score} из {total}',
        reply_markup=get_main_keyboard()
    )

async def main():
    """ запуск процесса поллинга """
    logger = logging.getLogger(__name__)

    await init_db()

    logger.info('Бот готов к работе')
    
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())

