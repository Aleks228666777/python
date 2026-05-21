import sqlite3
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler
from deep_translator import GoogleTranslator
from gtts import gTTS

TOKEN = ''
DB_NAME = 'bot_data.db'

INPUT_TEXT, INPUT_LANG = range(2)

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS vocabulary 
                          (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, original TEXT, translated TEXT)''')
        conn.commit()

def save_word(user_id, original, translated):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO vocabulary (user_id, original, translated) VALUES (?, ?, ?)', (user_id, original, translated))
        conn.commit()

def get_vocabulary(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT id, original, translated FROM vocabulary WHERE user_id = ? ORDER BY id DESC LIMIT 25', (user_id,))
        return cursor.fetchall()

def delete_word(word_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM vocabulary WHERE id = ?', (word_id,))
        conn.commit()

def clear_vocabulary(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM vocabulary WHERE user_id = ?', (user_id,))
        conn.commit()

def get_language_code(lang_name_ru):
    lang_name_ru = lang_name_ru.lower().strip()
    try:
        supported = GoogleTranslator().get_supported_languages(as_dict=True)
        lang_en = GoogleTranslator(source='ru', target='en').translate(lang_name_ru).lower().strip()
        
        if lang_en == 'chinese':
            return 'zh-CN'
            
        if lang_en in supported:
            return supported[lang_en]
            
        for name, code in supported.items():
            if lang_en in name:
                return code
        return None
    except:
        return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите текст для перевода:")
    return INPUT_TEXT

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['source_text'] = update.message.text
    await update.message.reply_text("Введите язык перевода (например: русский, английский, китайский):")
    return INPUT_LANG

async def handle_translation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_lang_input = update.message.text.lower().strip()
    source_text = context.user_data.get('source_text')
    lang_code = get_language_code(user_lang_input) or user_lang_input

    try:
        translated = GoogleTranslator(source='auto', target=lang_code).translate(source_text)
        context.user_data['last_translation'] = translated
        context.user_data['last_lang_code'] = lang_code
        output_message = f"Результат ({user_lang_input}):\n\n{translated}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Озвучить", callback_data="tts")],
            [InlineKeyboardButton("Добавить в избранное", callback_data="save_word")]
        ])
        await update.message.reply_text(output_message, reply_markup=keyboard)
        await update.message.reply_text("Введите новый текст или используйте /fav")
        return INPUT_TEXT
    except Exception:
        await update.message.reply_text("Не удалось найти язык попробуйте ввести точнее:")
        return INPUT_LANG

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query 
    await query.answer()
    user_id = update.effective_user.id

    if query.data == "save_word":
        original = context.user_data.get('source_text')
        text = context.user_data.get('last_translation')
        save_word(user_id, original, text)
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Озвучить", callback_data="tts")]]))
        await query.message.reply_text("Добавлено в избранное")
    
    elif query.data == "tts":
        text = context.user_data.get('last_translation')
        lang = context.user_data.get('last_lang_code')
        if not text: return
        file_path = f"voice_{user_id}.mp3"
        try:
            tts = gTTS(text=text, lang=lang, slow=False)
            tts.save(file_path)
            with open(file_path, 'rb') as audio:
                await query.message.reply_voice(voice=audio)
            os.remove(file_path)
        except:
            await query.message.reply_text("Озвучка недоступна")

async def show_vocabulary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    words = get_vocabulary(update.effective_user.id)
    if not words:
        await update.message.reply_text("Список пуст")
        return
    
    msg = "Ваше избранное:\n" + "-" * 10 + "\n"
    fav_map = {}
    for idx, (w_id, orig, tran) in enumerate(words, 1):
        msg += f"{idx}. Оригинал: {orig}\nПеревод: {tran}\n" + "-" * 10 + "\n"
        fav_map[idx] = w_id
    
    context.user_data['fav_map'] = fav_map
    msg += "\nДля удаления одного: /del [номер]\nДля очистки всего: /clear"
    await update.message.reply_text(msg)

async def delete_by_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Укажите номер записи для удаления например: /del 1")
        return
    try:
        idx = int(context.args[0])
        fav_map = context.user_data.get('fav_map', {})
        word_id = fav_map.get(idx)
        if word_id:
            delete_word(word_id)
            del fav_map[idx]
            await update.message.reply_text(f"Запись {idx} удалена")
        else:
            await update.message.reply_text("Запись не найдена сначала введите /fav")
    except (ValueError, IndexError):
        await update.message.reply_text("Пожалуйста введите корректный номер после /del")

async def clear_by_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_vocabulary(update.effective_user.id)
    await update.message.reply_text("Список избранного полностью очищен")

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            INPUT_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)],
            INPUT_LANG: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_translation)]
        },
        fallbacks=[CommandHandler("start", start), CommandHandler("fav", show_vocabulary)],
        allow_reentry=True
    )
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(CommandHandler("fav", show_vocabulary))
    app.add_handler(CommandHandler("del", delete_by_command))
    app.add_handler(CommandHandler("clear", clear_by_command))
    app.run_polling()

if __name__ == '__main__':
    main()
