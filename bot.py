import asyncio
import os
from collections import defaultdict
from typing import Dict, List, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Импортируем библиотеку для парсинга Flashscore
from flashscore import FlashscoreApi

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ Токен не найден")
    exit(1)

# Глобальный кэш для результатов
match_data_cache: Dict[int, Dict] = {}

async def get_today_matches() -> Dict[str, List[Tuple[str, str, str]]]:
    """
    Получает матчи на сегодня через библиотеку fs-football-fork
    Возвращает: { 'Лига': [('Команда А - Команда Б', 'url', 'время'), ...], ... }
    """
    print("🔄 Начинаем парсинг Flashscore через библиотеку...")
    
    try:
        # Запускаем API в отдельном потоке, так как он синхронный
        api = FlashscoreApi()
        
        # Получаем матчи на сегодня
        today_matches = await asyncio.to_thread(api.get_today_matches)
        
        matches_by_league = defaultdict(list)
        
        for match in today_matches:
            try:
                # Загружаем полную информацию о матче
                await asyncio.to_thread(match.load_content)
                
                # Получаем названия команд и лиги
                home_team = getattr(match, 'home_team_name', '?')
                away_team = getattr(match, 'away_team_name', '?')
                league_name = getattr(match, 'league_name', 'Неизвестная лига')
                
                # Время матча
                match_time = getattr(match, 'time', '—')
                
                # URL матча (формируем из ID, если есть)
                match_id = getattr(match, 'match_id', '')
                match_url = f"https://www.flashscorekz.com/match/{match_id}/" if match_id else None
                
                if home_team and away_team and home_team != '?' and away_team != '?':
                    match_title = f"{home_team} - {away_team}"
                    matches_by_league[league_name].append((match_title, match_url, match_time))
                    
            except Exception as e:
                print(f"Ошибка при обработке матча: {e}")
                continue
        
        return dict(matches_by_league)
        
    except Exception as e:
        print(f"Ошибка при парсинге Flashscore: {e}")
        return {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветственное сообщение"""
    await update.message.reply_text(
        "⚽ Привет! Я бот для анализа футбольных матчей.\n\n"
        "Используй команду /today, чтобы увидеть все матчи на сегодня."
    )

async def today_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все лиги с матчами на сегодня"""
    user_id = update.effective_user.id
    loading_msg = await update.message.reply_text("🔄 Загружаю матчи на сегодня... (15-20 секунд)")
    
    # Запускаем парсинг в отдельном потоке
    matches = await get_today_matches()
    
    if not matches:
        await loading_msg.edit_text("❌ Не удалось загрузить матчи. Попробуйте позже.")
        return
    
    # Сохраняем в кэш
    match_data_cache[user_id] = matches
    
    # Создаём клавиатуру с лигами
    leagues = list(matches.keys())
    keyboard = []
    for i, league in enumerate(leagues):
        match_count = len(matches[league])
        button_text = f"{league} ({match_count})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"league_{i}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    total_matches = sum(len(m) for m in matches.values())
    
    await loading_msg.edit_text(
        f"✅ Найдено матчей: {total_matches}\n\n🏆 Выберите лигу:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия на кнопки"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    callback_data = query.data
    
    matches_by_league = match_data_cache.get(user_id)
    if not matches_by_league:
        await query.edit_message_text("❌ Данные устарели. Используйте /today для обновления.")
        return
    
    if callback_data.startswith("league_"):
        league_index = int(callback_data.split("_")[1])
        leagues = list(matches_by_league.keys())
        
        if league_index >= len(leagues):
            await query.edit_message_text("❌ Лига не найдена")
            return
        
        selected_league = leagues[league_index]
        matches = matches_by_league[selected_league]
        
        # Создаём клавиатуру с матчами
        keyboard = []
        for i, (match_title, _, match_time) in enumerate(matches):
            button_text = f"{match_title} — {match_time}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"match_{league_index}_{i}")])
        
        keyboard.append([InlineKeyboardButton("◀️ Назад к лигам", callback_data="back_to_leagues")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🏆 {selected_league} — {len(matches)} матчей\n\n"
            f"Выберите матч для просмотра статистики:",
            reply_markup=reply_markup
        )
    
    elif callback_data.startswith("match_"):
        parts = callback_data.split("_")
        league_index = int(parts[1])
        match_index = int(parts[2])
        
        leagues = list(matches_by_league.keys())
        if league_index < len(leagues):
            matches = matches_by_league[leagues[league_index]]
            if match_index < len(matches):
                match_url = matches[match_index][1]
                if match_url:
                    await query.edit_message_text(
                        f"🔗 Ссылка на матч: {match_url}\n\n"
                        f"Функция получения подробной статистики в разработке.\n"
                        f"Используйте /today для возврата к списку."
                    )
                    return
        
        await query.edit_message_text("❌ Не удалось получить ссылку на матч.")
    
    elif callback_data == "back_to_leagues":
        # Возврат к списку лиг
        leagues = list(matches_by_league.keys())
        keyboard = []
        for i, league in enumerate(leagues):
            match_count = len(matches_by_league[league])
            button_text = f"{league} ({match_count})"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"league_{i}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🏆 Выберите лигу:",
            reply_markup=reply_markup
        )

def main():
    """Запуск бота"""
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрируем команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today_matches))
    
    # Регистрируем обработчик кнопок
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("🚀 Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
