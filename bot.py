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

# ============ ЗАГРУЗКА ТОКЕНА ============
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    print("❌ ОШИБКА: Токен не найден в переменных окружения")
    print("На Bothost добавьте переменную BOT_TOKEN в разделе 'Variables'")
    exit(1)

print("✅ Токен загружен")

# ============ ПАРСЕР FLASHSCORE ============
class FlashscoreMainParser:
    def __init__(self, headless=False):
        """Инициализация парсера с настройками браузера"""
        options = webdriver.ChromeOptions()
        
        if headless:
            options.add_argument('--headless')
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
        
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        prefs = {"profile.managed_default_content_settings.images": 2}
        options.add_experimental_option("prefs", prefs)
        
        # На Bothost ChromeDriver будет в PATH, можно без пути
        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 15)
    
    def get_today_matches(self) -> Dict[str, List[Tuple[str, str, str]]]:
        """Парсит главную страницу Flashscore"""
        print("🌐 Загружаем главную страницу Flashscore...")
        self.driver.get('https://www.flashscorekz.com/')
        
        try:
            self.wait.until(EC.presence_of_element_located((By.CLASS_NAME, "event__match")))
            print("✅ Страница загружена")
        except TimeoutException:
            print("❌ Не удалось загрузить страницу")
            return {}
        
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        matches_by_league = defaultdict(list)
        
        league_sections = soup.find_all('div', class_='headerLeague__wrapper')
        matches_section = soup.find_all('div', class_='event__match')
        
        print(f"\n📊 Найдено секций: {len(league_sections)}")
        print(f"🔍 Найдено матчей: {len(matches_section)}")
        
        for section in league_sections:
            country_name_elem = section.find('span', class_='headerLeague__category-text')
            if not country_name_elem:
                continue
            
            country_name = country_name_elem.get_text(strip=True)
            if not country_name or 'РЕКЛАМА' in country_name:
                continue
            
            league_name_elem = section.find('a', class_='headerLeague__title')
            if not league_name_elem:
                continue
            
            league_name = league_name_elem.get_text(strip=True)
            if not league_name or 'РЕКЛАМА' in league_name:
                continue
            
            print(f"  📌 {country_name} - {league_name}")
            
            for match in matches_section:
                try:
                    teams_home = match.find('div', class_='event__homeParticipant')
                    teams_away = match.find('div', class_='event__awayParticipant')
                    
                    if not teams_home or not teams_away:
                        continue
                    
                    home_elem = teams_home.find('span', class_='wcl-name_jjfMf')
                    away_elem = teams_away.find('span', class_='wcl-name_jjfMf')
                    
                    if not home_elem or not away_elem:
                        continue
                    
                    home = home_elem.get_text(strip=True)
                    away = away_elem.get_text(strip=True)
                    match_title = f"{home} - {away}"
                    
                    time_elem = match.find('div', class_='event__stage--block')
                    match_time = time_elem.get_text(strip=True) if time_elem else "—"
                    
                    link_elem = match.find('a', class_='eventRowLink')
                    if link_elem and link_elem.get('href'):
                        match_url = link_elem.get('href')
                        if not match_url.startswith('http'):
                            match_url = 'https://www.flashscorekz.com' + match_url
                    else:
                        match_url = None
                    
                    full_league_name = f"{country_name} - {league_name}"
                    matches_by_league[full_league_name].append((match_title, match_url, match_time))
                    
                except Exception as e:
                    continue
        
        print(f"\n✅ Найдено лиг: {len(matches_by_league)}")
        for league, matches in matches_by_league.items():
            print(f"  🏆 {league}: {len(matches)} матчей")
        
        return matches_by_league
    
    def get_match_url_by_selection(self, matches_by_league: Dict[str, List], 
                                   league_index: int, match_index: int) -> str:
        if not matches_by_league:
            return None
        leagues = list(matches_by_league.keys())
        if league_index >= len(leagues):
            return None
        matches = matches_by_league[leagues[league_index]]
        if match_index >= len(matches):
            return None
        return matches[match_index][1]
    
    def close(self):
        self.driver.quit()

# ============ TELEGRAM БОТ ============
match_data_cache = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚽ Привет! Я бот для анализа футбольных матчей.\n\n"
        "Используй команду /today, чтобы увидеть все матчи на сегодня."
    )

async def today_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все лиги с матчами на сегодня"""
    user_id = update.effective_user.id
    
    loading_msg = await update.message.reply_text("🔄 Загружаю матчи на сегодня... (15-20 секунд)")
    
    def run_parser():
        parser = FlashscoreMainParser(headless=True)
        matches = parser.get_today_matches()
        parser.close()
        return matches
    
    matches = await asyncio.to_thread(run_parser)
    
    if not matches:
        await loading_msg.edit_text("❌ Не удалось загрузить матчи. Попробуйте позже.")
        return
    
    match_data_cache[user_id] = matches
    
    leagues = list(matches.keys())
    keyboard = []
    for i, league in enumerate(leagues):
        match_count = len(matches[league])
        button_text = f"{league} ({match_count})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"league_{i}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await loading_msg.edit_text(
        text=f"✅ Найдено матчей: {sum(len(m) for m in matches.values())}\n\n🏆 Выберите лигу:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        
        keyboard = []
        for i, (match_title, _, match_time) in enumerate(matches):
            button_text = f"{match_title} — {match_time}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"match_{league_index}_{i}")])
        
        keyboard.append([InlineKeyboardButton("◀️ Назад к лигам", callback_data="back_to_leagues")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🏆 {selected_league} — {len(matches)} матчей\n\nВыберите матч:",
            reply_markup=reply_markup
        )
    
    elif callback_data.startswith("match_"):
        parts = callback_data.split("_")
        league_index = int(parts[1])
        match_index = int(parts[2])
        
        match_url = None
        leagues = list(matches_by_league.keys())
        if league_index < len(leagues):
            matches = matches_by_league[leagues[league_index]]
            if match_index < len(matches):
                match_url = matches[match_index][1]
        
        if match_url:
            await query.edit_message_text(f"🔗 Ссылка на матч: {match_url}")
        else:
            await query.edit_message_text("❌ Не удалось получить ссылку на матч.")
    
    elif callback_data == "back_to_leagues":
        leagues = list(matches_by_league.keys())
        keyboard = [[InlineKeyboardButton(f"{league} ({len(matches_by_league[league])})", callback_data=f"league_{i}")] 
                    for i, league in enumerate(leagues)]
        
        await query.edit_message_text("🏆 Выберите лигу:", reply_markup=InlineKeyboardMarkup(keyboard))

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("today", today_matches))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("🚀 Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()