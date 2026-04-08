"""
AI Agent для сбора, суммаризации и отправки новостей об ИИ в Telegram
Использует LangChain, RSS-ленты и Telegram Bot API
"""

import os
import asyncio
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

import feedparser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_community.llms import FakeListLLM
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Google Calendar imports
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from requests_oauthlib import OAuth2Session

# LangChain tool imports
from langchain_core.tools import Tool

# RSS ленты источников новостей об ИИ
AI_NEWS_RSS_FEEDS = [
    "https://www.artificialintelligence-news.com/feed/",
    "https://ai.googleblog.com/feeds/posts/default?alt=rss",
    "https://openai.com/blog/rss/",
    "https://www.venturebeat.com/category/ai/feed/",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
]


class GoogleCalendarAssistant:
    """Ассистент для создания мероприятий в Google Календаре"""
    
    def __init__(self, credentials_file: str = 'credentials.json', token_file: str = 'token.json'):
        """
        Инициализация ассистента Google Календаря
        
        Args:
            credentials_file: Путь к файлу с учетными данными OAuth2
            token_file: Путь к файлу с токеном доступа
        """
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.service = None
        self.SCOPES = ['https://www.googleapis.com/auth/calendar']
        self.llm_agent = None
        self._setup_langchain_agent()
    
    def _setup_langchain_agent(self):
        """Настройка LangChain агента с инструментом создания мероприятия"""
        
        # Создаем инструмент для создания мероприятия
        create_event_tool = Tool(
            name="create_calendar_event",
            description="Создает мероприятие в Google Календаре. Принимает JSON с полями: title (название), date (дата в формате YYYY-MM-DD), start_time (время начала в формате HH:MM), end_time (время окончания в формате HH:MM), description (описание)",
            func=self._create_event_from_json
        )
        
        self.tools = [create_event_tool]
    
    def _create_event_from_json(self, json_input: str) -> str:
        """
        Создание мероприятия из JSON строки (для использования в LangChain tool)
        
        Args:
            json_input: JSON строка с информацией о мероприятии
            
        Returns:
            Строка с результатом создания мероприятия
        """
        import json
        try:
            event_data = json.loads(json_input)
            
            # Конвертируем данные в формат для create_event
            if 'date' in event_data and isinstance(event_data['date'], str):
                from datetime import datetime
                event_data['date'] = datetime.strptime(event_data['date'], '%Y-%m-%d').date()
            
            result = self.create_event(event_data)
            
            if result:
                return f"Мероприятие '{result['title']}' успешно создано. Ссылка: {result['link']}"
            else:
                return "Ошибка при создании мероприятия"
                
        except json.JSONDecodeError as e:
            return f"Ошибка парсинга JSON: {e}"
        except Exception as e:
            return f"Ошибка: {e}"
    
    def authenticate(self) -> bool:
        """
        Аутентификация в Google Calendar API
        
        Returns:
            True если аутентификация успешна, иначе False
        """
        try:
            creds = None
            
            # Проверяем наличие сохраненного токена
            if os.path.exists(self.token_file):
                creds = Credentials.from_authorized_user_file(self.token_file, self.SCOPES)
            
            # Если токена нет или он недействителен, запрашиваем новый
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    # Для первого входа пользователю нужно будет пройти OAuth flow
                    # В production это делается через веб-интерфейс
                    print("Требуется авторизация Google Calendar.")
                    print(f"Пожалуйста, поместите файл '{self.credentials_file}' в рабочую директорию.")
                    return False
                
                # Сохраняем токен для будущего использования
                with open(self.token_file, 'w') as token:
                    token.write(creds.to_json())
            
            # Создаем сервис Google Calendar
            self.service = build('calendar', 'v3', credentials=creds)
            return True
            
        except Exception as e:
            print(f"Ошибка аутентификации Google Calendar: {e}")
            return False
    
    def parse_event_from_message(self, message: str) -> Optional[Dict[str, Any]]:
        """
        Извлечение информации о мероприятии из сообщения пользователя
        
        Args:
            message: Текст сообщения от пользователя
            
        Returns:
            Словарь с информацией о мероприятии или None если не найдено
        """
        event_data = {}
        
        # Ключевые слова для определения намерения создать мероприятие
        keywords = ['создай мероприятие', 'создай встречу', 'добавь в календарь', 
                    'мероприятие', 'встречу', 'событие']
        
        # Извлекаем название мероприятия - текст после ключевых слов до даты/времени
        title = None
        for keyword in keywords:
            if keyword in message.lower():
                idx = message.lower().find(keyword)
                # Берем текст после ключевого слова
                remaining_text = message[idx + len(keyword):].strip()
                
                # Пытаемся найти дату и обрезать текст до неё
                date_match = re.search(r'(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})', remaining_text)
                if date_match:
                    title = remaining_text[:date_match.start()].strip().strip("'\"").strip()
                else:
                    # Если даты нет, берем весь текст до времени
                    time_match = re.search(r'(\d{1,2}:\d{2})', remaining_text)
                    if time_match:
                        title = remaining_text[:time_match.start()].strip().strip("'\"").strip()
                    else:
                        title = remaining_text.strip().strip("'\"").strip()[:50]
                break
        
        if not title:
            # Пробуем извлечь текст в кавычках как название
            quoted_match = re.search(r'["\']([^"\']+)["\']', message)
            if quoted_match:
                title = quoted_match.group(1).strip()
        
        if not title:
            title = "Новое мероприятие"
        
        event_data['title'] = title
        
        # Извлекаем дату
        date_match = re.search(r'(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})', message)
        if date_match:
            date_str = date_match.group(1)
            try:
                # Пробуем разные форматы даты
                for fmt in ['%d.%m.%Y', '%d-%m-%Y', '%d/%m/%Y', '%d.%m.%y']:
                    try:
                        event_data['date'] = datetime.strptime(date_str, fmt).date()
                        break
                    except ValueError:
                        continue
            except:
                event_data['date'] = datetime.now().date()
        else:
            event_data['date'] = datetime.now().date()
        
        # Извлекаем время (начало и конец)
        time_pattern = r'(\d{1,2}:\d{2})\s*(?:[-–—]\s*(\d{1,2}:\d{2}))?'
        time_match = re.search(time_pattern, message)
        if time_match:
            event_data['start_time'] = time_match.group(1)
            event_data['end_time'] = time_match.group(2) if time_match.group(2) else None
        else:
            event_data['start_time'] = "10:00"
            event_data['end_time'] = None
        
        # Извлекаем длительность
        duration_match = re.search(r'на\s+(\d+)\s*(час(?:а|ов)?|минут(?:ы|))', message, re.IGNORECASE)
        if duration_match and not event_data['end_time']:
            duration_value = int(duration_match.group(1))
            unit = duration_match.group(2).lower() if duration_match.group(2) else 'час'
            
            start_datetime = datetime.strptime(f"{event_data['date']} {event_data['start_time']}", "%Y-%m-%d %H:%M")
            
            if 'минут' in unit:
                end_datetime = start_datetime + timedelta(minutes=duration_value)
            else:
                end_datetime = start_datetime + timedelta(hours=duration_value)
            
            event_data['end_time'] = end_datetime.strftime("%H:%M")
        
        # Если время окончания не указано, устанавливаем по умолчанию +1 час
        if not event_data['end_time']:
            start_datetime = datetime.strptime(f"{event_data['date']} {event_data['start_time']}", "%Y-%m-%d %H:%M")
            end_datetime = start_datetime + timedelta(hours=1)
            event_data['end_time'] = end_datetime.strftime("%H:%M")
        
        # Извлекаем описание (всё сообщение)
        event_data['description'] = message
        
        return event_data
    
    def create_event(self, event_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Создание мероприятия в Google Календаре
        
        Args:
            event_data: Словарь с информацией о мероприятии
            
        Returns:
            Информация о созданном мероприятии или None при ошибке
        """
        if not self.service:
            if not self.authenticate():
                return None
        
        try:
            # Форматируем дату и время для API
            start_date = event_data.get('date', datetime.now().date())
            start_time = event_data.get('start_time', '10:00')
            end_time = event_data.get('end_time', '11:00')
            
            start_datetime = datetime.strptime(f"{start_date} {start_time}", "%Y-%m-%d %H:%M")
            end_datetime = datetime.strptime(f"{start_date} {end_time}", "%Y-%m-%d %H:%M")
            
            # Создаем объект мероприятия
            event = {
                'summary': event_data.get('title', 'Новое мероприятие'),
                'description': event_data.get('description', ''),
                'start': {
                    'dateTime': start_datetime.isoformat(),
                    'timeZone': 'Europe/Moscow',  # Можно сделать настраиваемым
                },
                'end': {
                    'dateTime': end_datetime.isoformat(),
                    'timeZone': 'Europe/Moscow',
                },
            }
            
            # Создаем мероприятие в календаре
            created_event = self.service.events().insert(calendarId='primary', body=event).execute()
            
            return {
                'id': created_event.get('id'),
                'link': created_event.get('htmlLink'),
                'title': created_event.get('summary'),
                'start': created_event.get('start').get('dateTime'),
            }
            
        except HttpError as error:
            print(f"Ошибка при создании мероприятия: {error}")
            return None
        except Exception as e:
            print(f"Неожиданная ошибка: {e}")
            return None
    
    def create_agent_with_llm(self, llm):
        """
        Создание LangChain агента с LLM для обработки естественного языка
        
        Args:
            llm: Языковая модель (ChatOpenAI, ChatAnthropic и т.д.)
        
        Returns:
            None (агент сохраняется в self.llm_agent)
        """
        from langchain.agents import create_agent
        from langchain_core.prompts import ChatPromptTemplate
        
        # Создаем промпт для агента
        prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты помощник для создания мероприятий в Google Календаре.
Используй инструмент create_calendar_event для создания мероприятий.
Извлеки из сообщения пользователя информацию о мероприятии и передай её в формате JSON:
{{"title": "название", "date": "YYYY-MM-DD", "start_time": "HH:MM", "end_time": "HH:MM", "description": "описание"}}"""),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ])
        
        # Создаем агента
        agent = create_agent(
            llm=llm,
            tools=self.tools,
            prompt=prompt
        )
        
        self.llm_agent = agent
        return agent
    
    def process_message_with_agent(self, message: str) -> Optional[str]:
        """
        Обработка сообщения через LangChain агента
        
        Args:
            message: Текст сообщения от пользователя
            
        Returns:
            Результат выполнения или None если агент не инициализирован
        """
        if not self.llm_agent:
            return None
        
        try:
            from langchain.agents import AgentExecutor
            
            # Создаем executor для запуска агента
            agent_executor = AgentExecutor(
                agent=self.llm_agent,
                tools=self.tools,
                verbose=False
            )
            
            result = agent_executor.invoke({"input": message})
            return result.get("output", "Мероприятие создано")
        except Exception as e:
            print(f"Ошибка при обработке сообщения агентом: {e}")
            return None


class AINewsAgent:
    """Агент для сбора и суммаризации новостей об ИИ"""
    
    def __init__(self, llm=None):
        """
        Инициализация агента
        
        Args:
            llm: Языковая модель для суммаризации. Если None, используется заглушка.
        """
        self.llm = llm
        self.setup_summarization_chain()
    
    def setup_summarization_chain(self):
        """Настройка цепочки суммаризации"""
        
        if self.llm is None:
            # Используем заглушку если LLM не предоставлена
            self.llm = FakeListLLM(
                responses=[
                    "Это пример суммаризации новости. В реальном использовании подключите настоящую LLM."
                ]
            )
        
        # Промпт для суммаризации
        summarize_prompt = ChatPromptTemplate.from_messages([
            ("system", """Ты эксперт по искусственному интеллекту. 
Твоя задача - кратко суммаризировать новости об ИИ на русском языке.
Сделай краткое резюме (2-3 предложения) выделяя самое важное.
Будь точен и информативен."""),
            ("human", "Суммаризируй следующую новость:\n\n{news_text}"),
        ])
        
        # Цепочка суммаризации
        self.summarization_chain = (
            summarize_prompt 
            | self.llm 
            | StrOutputParser()
        )
    
    def fetch_news(self, max_articles_per_feed: int = 3) -> List[Dict[str, Any]]:
        """
        Сбор последних новостей из RSS лент
        
        Args:
            max_articles_per_feed: Максимальное количество статей с каждой ленты
            
        Returns:
            Список словарей с информацией о новостях
        """
        all_articles = []
        
        for feed_url in AI_NEWS_RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                
                for entry in feed.entries[:max_articles_per_feed]:
                    article = {
                        'title': entry.get('title', 'Без названия'),
                        'link': entry.get('link', ''),
                        'published': entry.get('published', 'Дата не указана'),
                        'source': feed.feed.get('title', 'Неизвестный источник'),
                        'summary': entry.get('summary', entry.get('description', '')),
                        'content': entry.get('content', [{}])[0].get('value', '') if entry.get('content') else ''
                    }
                    
                    # Объединяем summary и content для полного текста
                    full_text = article['summary']
                    if article['content'] and article['content'] != article['summary']:
                        full_text += f"\n\n{article['content']}"
                    
                    article['full_text'] = full_text
                    all_articles.append(article)
                    
            except Exception as e:
                print(f"Ошибка при получении ленты {feed_url}: {e}")
        
        return all_articles
    
    async def summarize_article(self, article: Dict[str, Any]) -> str:
        """
        Суммаризация одной статьи
        
        Args:
            article: Словарь с информацией о статье
            
        Returns:
            Суммаризированный текст
        """
        try:
            # Подготовка текста новости
            news_text = f"Заголовок: {article['title']}\n\n{article['full_text'][:2000]}"
            
            # Запуск суммаризации
            summary = await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: self.summarization_chain.invoke({"news_text": news_text})
            )
            
            return summary
        except Exception as e:
            return f"Ошибка при суммаризации: {e}"
    
    async def process_news(self, max_articles: int = 5) -> str:
        """
        Сбор и суммаризация новостей
        
        Args:
            max_articles: Максимальное количество статей для обработки
            
        Returns:
            Отформатированный текст со всеми суммаризированными новостями
        """
        print("Сбор новостей...")
        articles = self.fetch_news(max_articles_per_feed=2)
        
        if not articles:
            return "Не удалось получить новости. Проверьте подключение к интернету."
        
        # Ограничиваем количество статей
        articles = articles[:max_articles]
        
        print(f"Найдено {len(articles)} статей. Начинаем суммаризацию...")
        
        # Суммаризируем все статьи параллельно
        tasks = [self.summarize_article(article) for article in articles]
        summaries = await asyncio.gather(*tasks)
        
        # Формируем итоговый отчет
        report = f"🤖 Новости ИИ на {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        report += "=" * 50 + "\n\n"
        
        for i, (article, summary) in enumerate(zip(articles, summaries), 1):
            report += f"{i}. {article['title']}\n"
            report += f"Источник: {article['source']}\n"
            report += f"📝 {summary}\n"
            report += f"🔗 {article['link']}\n\n"
            report += "-" * 30 + "\n\n"
        
        return report


class TelegramBot:
    """Telegram бот для отправки новостей"""
    
    def __init__(self, token: str, agent: AINewsAgent, calendar_assistant: Optional[GoogleCalendarAssistant] = None):
        """
        Инициализация бота
        
        Args:
            token: Токен Telegram бота
            agent: Экземпляр AINewsAgent
            calendar_assistant: Экземпляр GoogleCalendarAssistant (опционально)
        """
        self.token = token
        self.agent = agent
        self.calendar_assistant = calendar_assistant
        self.application = None
        self.subscribers = set()
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        help_text = "👋 Привет! Я бот для новостей об ИИ.\n\n"
        help_text += "Команды:\n"
        help_text += "/news - Получить последние новости об ИИ\n"
        help_text += "/subscribe - Подписаться на ежедневные новости\n"
        help_text += "/unsubscribe - Отписаться от новостей\n"
        help_text += "/help - Помощь\n"
        
        if self.calendar_assistant:
            help_text += "\n📅 Календарь:\n"
            help_text += "Просто напишите сообщение в формате:\n"
            help_text += "\"Создай мероприятие 'Встреча с командой' 25.12.2024 в 15:00 на 2 часа\"\n"
        
        await update.message.reply_text(help_text)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help"""
        help_text = "📚 Помощь:\n\n"
        help_text += "Этот бот собирает последние новости в области искусственного интеллекта,\n"
        help_text += "суммаризирует их и отправляет вам.\n\n"
        help_text += "Используйте /news для получения новостей вручную,\n"
        help_text += "или /subscribe для автоматической ежедневной рассылки.\n\n"
        
        if self.calendar_assistant:
            help_text += "📅 Создание мероприятий в Google Календаре:\n"
            help_text += "Отправьте сообщение в свободной форме, например:\n"
            help_text += "• \"Создай встречу с коллегами завтра в 14:00\"\n"
            help_text += "• \"Добавь в календарь собеседование 15.01.2025 на 30 минут\"\n"
            help_text += "• \"Мероприятие 'Презентация проекта' 20.12.2024 10:00-11:30\"\n"
        
        await update.message.reply_text(help_text)
    
    async def news_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /news"""
        await update.message.reply_text("⏳ Загружаю последние новости об ИИ...")
        
        try:
            report = await self.agent.process_news(max_articles=5)
            
            # Telegram имеет ограничение на длину сообщения (4096 символов)
            if len(report) > 4000:
                # Разбиваем на несколько сообщений
                chunks = [report[i:i+4000] for i in range(0, len(report), 4000)]
                for chunk in chunks:
                    await update.message.reply_text(chunk)
            else:
                await update.message.reply_text(report)
                
        except Exception as e:
            await update.message.reply_text(f"❌ Произошла ошибка: {e}")
    
    async def subscribe_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /subscribe"""
        user_id = update.effective_user.id
        self.subscribers.add(user_id)
        await update.message.reply_text(
            "✅ Вы подписаны на ежедневные новости об ИИ!\n"
            "Новости будут приходить каждый день в 9:00."
        )
    
    async def unsubscribe_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /unsubscribe"""
        user_id = update.effective_user.id
        self.subscribers.discard(user_id)
        await update.message.reply_text(
            "❌ Вы отписались от новостей об ИИ."
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Обработчик текстовых сообщений для создания мероприятий в календаре через LangChain агента и tool
        """
        if not self.calendar_assistant:
            return
        
        message_text = update.message.text
        
        # Проверяем, содержит ли сообщение ключевые слова для создания мероприятия
        calendar_keywords = ['создай', 'добавь в календарь', 'мероприятие', 'встречу', 'событие']
        
        if any(keyword in message_text.lower() for keyword in calendar_keywords):
            await update.message.reply_text("⏳ Обрабатываю запрос на создание мероприятия...")
            
            try:
                # Пытаемся использовать LangChain агента если он доступен
                result = None
                if self.calendar_assistant.llm_agent:
                    result = self.calendar_assistant.process_message_with_agent(message_text)
                
                # Если агент не вернул результат или не инициализирован, используем прямой парсинг
                if not result:
                    # Извлекаем информацию о мероприятии из сообщения
                    event_data = self.calendar_assistant.parse_event_from_message(message_text)
                    
                    if event_data:
                        # Формируем подтверждение для пользователя
                        confirm_text = f"📅 Планируется создание мероприятия:\n\n"
                        confirm_text += f"📌 Название: {event_data.get('title', 'Не указано')}\n"
                        confirm_text += f"📅 Дата: {event_data.get('date', datetime.now().date())}\n"
                        confirm_text += f"⏰ Время: {event_data.get('start_time', 'Не указано')} - {event_data.get('end_time', 'Не указано')}\n\n"
                        
                        await update.message.reply_text(confirm_text)
                        
                        # Создаем мероприятие в Google Календаре
                        created_event = self.calendar_assistant.create_event(event_data)
                        
                        if created_event:
                            success_text = f"✅ Мероприятие успешно создано!\n\n"
                            success_text += f"📌 {created_event['title']}\n"
                            success_text += f"🔗 Ссылка: {created_event['link']}"
                            await update.message.reply_text(success_text)
                        else:
                            await update.message.reply_text(
                                "❌ Не удалось создать мероприятие. "
                                "Убедитесь, что файл credentials.json настроен правильно."
                            )
                    else:
                        await update.message.reply_text(
                            "❌ Не удалось распознать информацию о мероприятии. "
                            "Попробуйте указать название, дату и время более явно."
                        )
                else:
                    # Результат от LangChain агента
                    await update.message.reply_text(result)
                    
            except Exception as e:
                await update.message.reply_text(f"❌ Произошла ошибка: {e}")
    
    async def send_daily_news(self, context: ContextTypes.DEFAULT_TYPE):
        """Отправка ежедневных новостей подписчикам"""
        if not self.subscribers:
            return
        
        print("Отправка ежедневных новостей подписчикам...")
        report = await self.agent.process_news(max_articles=5)
        
        for user_id in self.subscribers:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=report,
                    parse_mode='HTML'
                )
            except Exception as e:
                print(f"Ошибка отправки пользователю {user_id}: {e}")
                # Удаляем пользователя из подписчиков если произошла ошибка
                self.subscribers.discard(user_id)
    
    def run(self):
        """Запуск бота"""
        # Создание приложения
        self.application = Application.builder().token(self.token).build()
        
        # Добавление обработчиков команд
        self.application.add_handler(CommandHandler("start", self.start_command))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("news", self.news_command))
        self.application.add_handler(CommandHandler("subscribe", self.subscribe_command))
        self.application.add_handler(CommandHandler("unsubscribe", self.unsubscribe_command))
        
        # Добавление обработчика текстовых сообщений для календаря
        if self.calendar_assistant:
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
        # Планирование ежедневной рассылки в 9:00
        self.application.job_queue.run_daily(
            self.send_daily_news,
            time=datetime.strptime("09:00", "%H:%M").time()
        )
        
        print("Бот запущен...")
        # Запуск бота
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


def create_llm():
    """
    Создание языковой модели
    
    Для использования реальной LLM раскомментируйте нужный код:
    - OpenAI
    - Anthropic Claude
    - Ollama (локальная)
    - DeepSeek
    """
    
    # ВАРИАНТ 1: OpenAI GPT
    # from langchain_openai import ChatOpenAI
    # return ChatOpenAI(
    #     model="gpt-3.5-turbo",
    #     temperature=0.3,
    #     api_key=os.getenv("OPENAI_API_KEY")
    # )
    
    # ВАРИАНТ 2: Anthropic Claude
    # from langchain_anthropic import ChatAnthropic
    # return ChatAnthropic(
    #     model="claude-3-haiku-20240307",
    #     temperature=0.3,
    #     api_key=os.getenv("ANTHROPIC_API_KEY")
    # )
    
    # ВАРИАНТ 3: Ollama (локальная модель)
    # from langchain_ollama import ChatOllama
    # return ChatOllama(
    #     model="llama3",
    #     temperature=0.3,
    #     base_url="http://localhost:11434"
    # )
    
    # ВАРИАНТ 4: DeepSeek (API-совместим с OpenAI)
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model="deepseek-chat",  # или "deepseek-coder" для кодерской версии
        temperature=0.3,
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com/v1"
    )
    
    # По умолчанию используем заглушку (для тестирования)
    return None


async def main():
    """Основная функция для запуска агента"""
    
    # Проверка наличия токена Telegram
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not telegram_token:
        print("❌ Ошибка: Не найден токен Telegram бота!")
        print("Пожалуйста, установите переменную окружения TELEGRAM_BOT_TOKEN")
        print("\nКак получить токен:")
        print("1. Откройте @BotFather в Telegram")
        print("2. Создайте нового бота командой /newbot")
        print("3. Скопируйте полученный токен")
        print("4. Установите переменную окружения: export TELEGRAM_BOT_TOKEN='ваш_токен'")
        return
    
    # Создание LLM
    llm = create_llm()
    
    # Создание агента
    agent = AINewsAgent(llm=llm)
    
    # Создание ассистента Google Календаря (опционально)
    calendar_assistant = None
    if os.path.exists('credentials.json'):
        calendar_assistant = GoogleCalendarAssistant(
            credentials_file='credentials.json',
            token_file='token.json'
        )
        print("✅ Google Calendar ассистент инициализирован.")
        
        # Инициализируем LangChain агента с LLM для обработки естественного языка
        if llm:
            calendar_assistant.create_agent_with_llm(llm)
            print("✅ LangChain агент для календаря инициализирован.")
    else:
        print("⚠️  Файл credentials.json не найден. Функция создания мероприятий в календаре будет недоступна.")
        print("   Для включения создайте проект в Google Cloud Console и получите OAuth2 credentials.")
    
    # Создание и запуск бота
    bot = TelegramBot(token=telegram_token, agent=agent, calendar_assistant=calendar_assistant)
    bot.run()


if __name__ == "__main__":
    asyncio.run(main())
