import asyncio
import os
import time
from collections import defaultdict
from typing import Dict, List, Tuple

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ Токен не найден")
    exit(1)

class FlashscoreMainParser:
    def __init__(self, headless=True):
        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument('--headless')
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--user-agent=Mozilla/5.0')
        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 15)
    
    def get_today_matches(self):
        print("🌐 Загружаем Flashscore...")
        self.driver.get('https://www.flashscorekz.com/')
        try:
            self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "event__match")))
        except:
            return {}
        
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        matches_by_league = defaultdict(list)
        league_sections = soup.find_all('div', class_='headerLeague__wrapper')
        
        for section in league_sections:
            country = section.find('span', class_='headerLeague__category-text')
            league = section.find('a', class_='headerLeague__title')
            if not country or not league:
                continue
            
            country_name = country.get_text(strip=True)
            league_name = league.get_text(strip=True)
            full_name = f"{country_name} - {league_name}"
            
            for match in section.find_all('div', class_='event__match'):
                try:
                    home = match.find('div', class_='event__homeParticipant')
                    away = match.find('div', class_='event__awayParticipant')
                    if not home or not away:
                        continue
                    
                    home_team = home.find('span', class_='wcl-name_jjfMf')
                    away_team = away.find('span', class_='wcl-name_jjfMf')
                    if not home_team or not away_team:
                        continue
                    
                    time_elem = match.find('div', class_='event__stage--block')
                    match_time = time_elem.get_text(strip=True) if time_elem else "—"
                    
                    link = match.find('a', class_='eventRowLink')
                    url = link.get('href') if link else None
                    if url and not url.startswith('http'):
                        url = 'https://www.flashscorekz.com' + url
                    
                    matches_by_league[full_name].append((f"{home_team.text} - {away_team.text}", url, match_time))
                except:
                    continue
        
        self.driver.quit()
        return matches_by_league

cache = {}

async def start(update, context):
    await update.message.reply_text("⚽ Бот для матчей\n/today - матчи на сегодня")

async def today_matches(update, context):
    user_id = update.effective_user.id
    msg = await update.message.reply_text("🔄 Загружаю матчи...")
    
    def parse():
        p = FlashscoreMainParser(headless=True)
        return p.get_today_matches()
    
    matches = await asyncio.to_thread(parse)
    
    if not matches:
        await msg.edit_text("❌ Ошибка загрузки")
        return
    
    cache[user_id] = matches
    keyboard = [[InlineKeyboardButton(f"{l} ({len(matches[l])})", callback_data=f"l_{i}")] for i, l in enumerate(matches.keys())]
    await msg.edit_text(f"✅ {sum(len(m) for m in matches.values())} матчей\nВыберите лигу:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    
    matches = cache.get(user_id)
    if not matches:
        await query.edit_message_text("Данные устарели. /today")
        return
    
    if data.startswith("l_"):
        idx = int(data.split("_")[1])
        leagues = list(matches.keys())
        if idx >= len(leagues):
            return
        league = leagues[idx]
        league_matches = matches[league]
        keyboard = [[InlineKeyboardButton(f"{m[0]} ({m[2]})", callback_data=f"m_{idx}_{i}")] for i, m in enumerate(league_matches)]
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="back")])
        await query.edit_message_text(f"🏆 {league}\nВыберите матч:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("m_"):
        parts = data.split("_")
        league_idx = int(parts[1])
        match_idx = int(parts[2])
        leagues = list(matches.keys())
        if league_idx < len(leagues):
            m = matches[leagues[league_idx]][match_idx]
            if m[1]:
                await query.edit_message_text(f"🔗 {m[1]}")
                return
        await query.edit_message_text("❌ Ссылка не найдена")
    
    elif data == "back":
        keyboard = [[InlineKeyboardButton(f"{l} ({len(matches[l])})", callback_data=f"l_{i}")] for i, l in enumerate(matches.keys())]
        await query.edit_message_text("🏆 Выберите лигу:", reply_markup=InlineKeyboardMarkup(keyboard))

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today_matches))
    app.add_handler(CallbackQueryHandler(button))
    print("Бот запущен")
    app.run_polling()

if __name__ == "__main__":
    main()
