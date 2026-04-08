# LangChain Agent для Google Calendar

## Обзор

Этот модуль добавляет возможность создания мероприятий в Google Календаре через **LangChain агента** с использованием **tool** (инструмента).

## Архитектура

### Компоненты:

1. **GoogleCalendarAssistant** - основной класс для работы с календарем
2. **LangChain Tool** - инструмент `create_calendar_event` для создания мероприятий
3. **LangChain Agent** - агент на основе LLM для обработки естественного языка
4. **TelegramBot** - интеграция с Telegram для получения команд от пользователя

## Как это работает

### 1. Создание инструмента (Tool)

```python
from langchain_core.tools import Tool

create_event_tool = Tool(
    name="create_calendar_event",
    description="Создает мероприятие в Google Календаре. Принимает JSON с полями: title, date, start_time, end_time, description",
    func=calendar_assistant._create_event_from_json
)
```

### 2. Инициализация агента с LLM

```python
from langchain.agents import create_agent
from langchain_core.prompts import ChatPromptTemplate

prompt = ChatPromptTemplate.from_messages([
    ("system", "Ты помощник для создания мероприятий в Google Календаре..."),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

agent = create_agent(
    llm=llm,  # ChatOpenAI, ChatAnthropic и т.д.
    tools=[create_event_tool],
    prompt=prompt
)
```

### 3. Обработка сообщения пользователя

```python
from langchain.agents import AgentExecutor

agent_executor = AgentExecutor(
    agent=agent,
    tools=[create_event_tool],
    verbose=False
)

result = agent_executor.invoke({"input": "Создай встречу завтра в 15:00"})
```

## Примеры использования

### Прямой вызов инструмента:

```python
import json
from ai_news_agent import GoogleCalendarAssistant

calendar = GoogleCalendarAssistant()

# JSON вход для инструмента
event_json = json.dumps({
    "title": "Командная встреча",
    "date": "2024-12-25",
    "start_time": "15:00",
    "end_time": "16:00",
    "description": "Обсуждение проекта"
})

result = calendar._create_event_from_json(event_json)
print(result)  # "Мероприятие 'Командная встреча' успешно создано..."
```

### Через LangChain агента:

```python
from langchain_openai import ChatOpenAI
from ai_news_agent import GoogleCalendarAssistant

# Создаем ассистента
calendar = GoogleCalendarAssistant()

# Инициализируем LLM
llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0.3)

# Создаем агента
calendar.create_agent_with_llm(llm)

# Обрабатываем сообщение пользователя
message = "Создай встречу с командой 25 декабря в 15:00 на 1 час"
result = calendar.process_message_with_agent(message)
print(result)
```

### Через Telegram бота:

Пользователь отправляет сообщение:
```
Создай мероприятие "Обед с коллегами" 26.12.2024 в 13:00 на 2 часа
```

Бот:
1. Распознает ключевые слова
2. Если LLM агент доступен - использует его
3. Если нет - использует прямой парсинг
4. Показывает подтверждение
5. Создает мероприятие в Google Calendar
6. Отправляет ссылку на мероприятие

## Настройка

### 1. Установите зависимости:

```bash
pip install -r requirements.txt
```

### 2. Получите OAuth2 credentials от Google:

1. Откройте [Google Cloud Console](https://console.cloud.google.com/)
2. Создайте новый проект
3. Включите Google Calendar API
4. Создайте OAuth2 credentials
5. Скачайте файл `credentials.json`

### 3. Настройте переменные окружения:

```bash
export TELEGRAM_BOT_TOKEN="your_telegram_bot_token"
export DEEPSEEK_API_KEY="your_api_key"  # или другой LLM провайдер
```

### 4. Запустите бота:

```bash
python ai_news_agent.py
```

## Формат данных инструмента

Инструмент принимает JSON со следующими полями:

```json
{
  "title": "Название мероприятия",
  "date": "YYYY-MM-DD",
  "start_time": "HH:MM",
  "end_time": "HH:MM",
  "description": "Описание мероприятия"
}
```

## Преимущества подхода с LangChain

1. **Гибкость** - агент может обрабатывать разнообразные формулировки
2. **Расширяемость** - легко добавить новые инструменты
3. **Интеллектуальность** - LLM понимает контекст и извлекает сущности
4. **Отладка** - встроенный verbose режим для отладки

## Альтернативный режим (без LLM)

Если LLM не доступна, используется прямой парсинг с помощью регулярных выражений:

```python
event_data = calendar.parse_event_from_message(
    "Создай встречу 25.12.2024 в 15:00"
)
calendar.create_event(event_data)
```

Это обеспечивает работу базового функционала даже без подключения к LLM.
