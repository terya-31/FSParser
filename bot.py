import asyncio
import os
import requests
from collections import defaultdict
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ Токен не найден")
    exit(1)

def get_today_matches():
    """Получает матчи через API Flashscore"""
    url = "https://flashscore-api.com/api/v1/matches/today"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Accept-Language": "ru,en;q=0.9",
        "Referer": "https://www.flashscorekz.com/"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            return {}
        
        data = response.json()
        matches_by_league = defaultdict(list)
        
        for match in data.get('matches', []):
            league = match.get('league', {}).get('name', 'Неизвестная лига')
            country = match.get('league', {}).get('country', {}).get('name', '')
            home = match.get('home', {}).get('name', '')
            away = match.get('away', {}).get('name', '')
            time_str = match.get('time', '')
            match_id = match.get('id', '')
            
            if home and away:
                league_name = f"{country} - {league}" if country else league
                match_title = f"{home} - {away}"
                match_url = f"https://www.flashscorekz.com/match/{match_id}/"
                match_time = time_str if time_str else "—"
                matches_by_league[league_name].append((match_title, match_url, match_time))
        
        return matches_by_league
    except Exception as e:
        print(f"Ошибка API: {e}")
        return {}

cache = {}

async def start(update, context):
    await update.message.reply_text(
        "⚽ Привет! Я бот для анализа футбольных матчей.\n\n"
        "Используй команду /today, чтобы увидеть все матчи на сегодня."
    )

async def today_matches(update, context):
    user_id = update.effective_user.id
    msg = await update.message.reply_text("🔄 Загружаю матчи на сегодня...")
    
    matches = await asyncio.to_thread(get_today_matches)
    
    if not matches:
        await msg.edit_text("❌ Не удалось загрузить матчи. Попробуйте позже.")
        return
    
    cache[user_id] = matches
    
    keyboard = []
    for i, league in enumerate(matches.keys()):
        match_count = len(matches[league])
        button_text = f"{league} ({match_count})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"league_{i}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    total_matches = sum(len(m) for m in matches.values())
    await msg.edit_text(
        f"✅ Найдено матчей: {total_matches}\n\n🏆 Выберите лигу:",
        reply_markup=reply_markup
    )

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    callback_data = query.data
    matches = cache.get(user_id)
    
    if not matches:
        await query.edit_message_text("❌ Данные устарели. Используйте /today для обновления.")
        return
    
    if callback_data.startswith("league_"):
        league_index = int(callback_data.split("_")[1])
        leagues = list(matches.keys())
        
        if league_index >= len(leagues):
            await query.edit_message_text("❌ Лига не найдена")
            return
        
        selected_league = leagues[league_index]
        league_matches = matches[selected_league]
        
        keyboard = []
        for i, (match_title, _, match_time) in enumerate(league_matches):
            button_text = f"{match_title} — {match_time}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"match_{league_index}_{i}")])
        
        keyboard.append([InlineKeyboardButton("◀️ Назад к лигам", callback_data="back_to_leagues")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🏆 {selected_league} — {len(league_matches)} матчей\n\nВыберите матч:",
            reply_markup=reply_markup
        )
    
    elif callback_data.startswith("match_"):
        parts = callback_data.split("_")
        league_index = int(parts[1])
        match_index = int(parts[2])
        
        leagues = list(matches.keys())
        if league_index < len(leagues):
            league_matches = matches[leagues[league_index]]
            if match_index < len(league_matches):
                match_url = league_matches[match_index][1]
                if match_url:
                    await query.edit_message_text(f"🔗 Ссылка на матч: {match_url}")
                    return
        
        await query.edit_message_text("❌ Не удалось получить ссылку на матч.")
    
    elif callback_data == "back_to_leagues":
        keyboard = []
        for i, league in enumerate(matches.keys()):
            match_count = len(matches[league])
            button_text = f"{league} ({match_count})"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"league_{i}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🏆 Выберите лигу:",
            reply_markup=reply_markup
        )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today_matches))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("🚀 Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
