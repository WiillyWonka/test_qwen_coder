"""
AI Agent для сбора, суммаризации и отправки новостей об ИИ в Telegram
Использует LangChain, RSS-ленты и Telegram Bot API
"""

import os
import asyncio
from datetime import datetime
from typing import List, Dict, Any

import feedparser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_community.llms import FakeListLLM
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# RSS ленты источников новостей об ИИ
AI_NEWS_RSS_FEEDS = [
    "https://www.artificialintelligence-news.com/feed/",
    "https://ai.googleblog.com/feeds/posts/default?alt=rss",
    "https://openai.com/blog/rss/",
    "https://www.venturebeat.com/category/ai/feed/",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
]


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
    
    def __init__(self, token: str, agent: AINewsAgent):
        """
        Инициализация бота
        
        Args:
            token: Токен Telegram бота
            agent: Экземпляр AINewsAgent
        """
        self.token = token
        self.agent = agent
        self.application = None
        self.subscribers = set()
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        await update.message.reply_text(
            "👋 Привет! Я бот для новостей об ИИ.\n\n"
            "Команды:\n"
            "/news - Получить последние новости об ИИ\n"
            "/subscribe - Подписаться на ежедневные новости\n"
            "/unsubscribe - Отписаться от новостей\n"
            "/help - Помощь"
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /help"""
        await update.message.reply_text(
            "📚 Помощь:\n\n"
            "Этот бот собирает последние новости в области искусственного интеллекта,\n"
            "суммаризирует их и отправляет вам.\n\n"
            "Используйте /news для получения новостей вручную,\n"
            "или /subscribe для автоматической ежедневной рассылки."
        )
    
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
    # from langchain_openai import ChatOpenAI
    # return ChatOpenAI(
    #     model="deepseek-chat",  # или "deepseek-coder" для кодерской версии
    #     temperature=0.3,
    #     api_key=os.getenv("DEEPSEEK_API_KEY"),
    #     base_url="https://api.deepseek.com/v1"
    # )
    
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
    
    # Создание и запуск бота
    bot = TelegramBot(token=telegram_token, agent=agent)
    bot.run()


if __name__ == "__main__":
    asyncio.run(main())
