# RAG Ollama - Local AI Assistant

Production-ready RAG (Retrieval-Augmented Generation) система на Django для корпоративного использования в закрытом контуре. 100% локально, без облаков, без внешних API.

## Tech Stack

- **Backend:** Django 5.1 + Django REST Framework
- **LLM:** Ollama (mistral + nomic-embed-text)
- **Vector DB:** ChromaDB (persistent local storage)
- **Frontend:** Django Templates + HTMX + Alpine.js
- **Documents:** PDF, TXT, MD
- **Auth:** Django sessions + API key
- **Package Manager:** Poetry
- **Automation:** Makefile

---

## Quick Start

### Вариант 1. Docker + локальная Ollama (все на одном сервере)

Ollama поднимается в контейнере рядом с Django. Подходит когда GPU/CPU и Django на одной машине.

```bash
cd rag_ollama
cp .env.example .env

# С GPU (NVIDIA)
make up

# Без GPU (CPU only)
make up-cpu
```

Первый запуск занимает время -- скачиваются модели Ollama (mistral ~4GB, nomic-embed-text ~300MB).

Открыть: **http://localhost:8000**
Django Admin: **http://localhost:8000/admin/** (логин и пароль из `.env` → `DJANGO_SUPERUSER_USERNAME` / `DJANGO_SUPERUSER_PASSWORD`)

### Вариант 2. Docker + удалённая Ollama (Ollama на другом сервере)

Django в Docker-контейнере, а Ollama уже запущена на другом сервере в сети. Ollama локально НЕ запускается.

```bash
cd rag_ollama
cp .env.example .env
```

Отредактировать `.env` -- указать адрес удалённого сервера с Ollama:

```ini
OLLAMA_URL=http://192.168.1.100:11434
```

Убедиться, что на удалённом сервере Ollama доступна и модели загружены:

```bash
# Проверить доступность удалённой Ollama
make ollama-check-remote

# Если модели не загружены -- выполнить на сервере с Ollama:
# ssh user@192.168.1.100 "ollama pull mistral && ollama pull nomic-embed-text"
```

Запуск:

```bash
make up-external
```

Или напрямую:

```bash
docker compose -f docker-compose.external.yml up -d
```

### Вариант 3. Без Docker (локальная разработка)

```bash
cd rag_ollama

# Полная установка одной командой
make setup

# Или пошагово:
poetry install               # Установить зависимости
make env                     # Создать .env
make migrate                 # Миграции
make static                  # Собрать статику
make superuser               # Создать суперпользователя
```

Если Ollama на этой же машине:

```bash
# Отредактировать .env:
# OLLAMA_URL=http://localhost:11434

make ollama-serve &
make ollama-pull
make run
```

Если Ollama на удалённом сервере:

```bash
# Отредактировать .env:
# OLLAMA_URL=http://192.168.1.100:11434

make ollama-check-remote     # Проверить связь
make run
```

### Вариант 4. Через Open WebUI (Ollama за Open WebUI с API-ключами)

Если Ollama работает за Open WebUI, и доступ контролируется через API-ключи Open WebUI.
В этом режиме все запросы (chat, embeddings) идут через OpenAI-совместимый API Open WebUI,
а не напрямую в Ollama. Open WebUI выступает прокси и контролирует доступ по ключам.

```bash
cd rag_ollama
cp .env.example .env
```

Отредактировать `.env`:

```ini
LLM_BACKEND=openwebui
OPENWEBUI_URL=http://192.168.1.100:3000
OPENWEBUI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
EMBED_MODEL=nomic-embed-text
LLM_MODEL=mistral
```

API-ключ Open WebUI можно получить в интерфейсе: Settings -> Account -> API Keys.

Проверить подключение:

```bash
make owui-status             # Проверить связь и авторизацию
make owui-check-key          # Проверить валидность ключа
make owui-models             # Список доступных моделей
```

Запуск (Docker):

```bash
make up-external             # Поднимает только Django, без Ollama
```

Запуск (локально без Docker):

```bash
make setup
make run
```

---

## Makefile Commands

```bash
make help            # Показать все доступные команды
```

### Setup & Install

| Command            | Description                                      |
|--------------------|--------------------------------------------------|
| `make install`     | Установить все зависимости через Poetry           |
| `make install-prod`| Установить только production-зависимости          |
| `make setup`       | Полная локальная настройка (install+env+migrate+static+superuser) |
| `make env`         | Создать .env из .env.example                      |

### Django

| Command            | Description                                      |
|--------------------|--------------------------------------------------|
| `make run`         | Запустить dev-сервер на 0.0.0.0:8000             |
| `make migrate`     | Выполнить миграции                                |
| `make migrations`  | Создать новые миграции                            |
| `make static`      | Собрать статические файлы                         |
| `make superuser`   | Создать суперпользователя                         |
| `make shell`       | Открыть Django shell (IPython)                    |

### Ollama

| Command                  | Description                                      |
|--------------------------|--------------------------------------------------|
| `make ollama-serve`      | Запустить Ollama сервер локально                  |
| `make ollama-pull`       | Скачать модели (mistral + nomic-embed-text)       |
| `make ollama-status`     | Проверить статус Ollama (читает OLLAMA_URL из .env)|
| `make ollama-check-remote`| Проверить доступность удалённой Ollama            |

### Open WebUI

| Command                  | Description                                      |
|--------------------------|--------------------------------------------------|
| `make owui-status`       | Проверить Open WebUI (связь + авторизация)        |
| `make owui-models`       | Список моделей в Open WebUI                       |
| `make owui-check-key`    | Проверить валидность API-ключа Open WebUI         |

### Docker

| Command                  | Description                                    |
|--------------------------|------------------------------------------------|
| `make up`                | Запустить все сервисы (GPU + Ollama)           |
| `make up-cpu`            | Запустить все сервисы (CPU + Ollama)           |
| `make up-external`       | Только Django, Ollama на удалённом сервере     |
| `make up-build`          | Пересобрать и запустить (GPU)                  |
| `make up-build-cpu`      | Пересобрать и запустить (CPU)                  |
| `make up-build-external` | Пересобрать и запустить (удалённая Ollama)     |
| `make down`              | Остановить все сервисы                         |
| `make down-external`     | Остановить Django (external compose)           |
| `make down-volumes`      | Остановить и удалить volumes (удаляет данные!) |
| `make logs`              | Логи всех сервисов                             |
| `make logs-ext`          | Логи (external compose)                        |
| `make logs-django`       | Логи Django                                    |
| `make logs-ollama`       | Логи Ollama                                    |
| `make ps`                | Показать запущенные контейнеры                 |
| `make restart`           | Перезапустить сервисы                          |
| `make rebuild`           | Полная пересборка                              |
| `make docker-shell`      | Shell внутри Django-контейнера                 |

### Development & Quality

| Command            | Description                                      |
|--------------------|--------------------------------------------------|
| `make lint`        | Проверить код линтером (ruff)                     |
| `make lint-fix`    | Автоисправление линтером                          |
| `make format`      | Форматирование кода (ruff format)                 |
| `make test`        | Запустить тесты (pytest)                          |
| `make check`       | Линтер + тесты                                    |

### Cleanup

| Command            | Description                                      |
|--------------------|--------------------------------------------------|
| `make clean`       | Удалить Python-кеш                                |
| `make clean-data`  | Удалить локальные данные (db, chroma, logs)        |
| `make clean-all`   | Удалить все (кеш + данные)                        |

---

## Структура проекта

```
rag_ollama/
├── manage.py                  # Django management
├── pyproject.toml             # Poetry (зависимости + конфиг)
├── poetry.lock                # Lockfile
├── Makefile                   # Автоматизация команд
├── docker-compose.yml         # Docker (GPU + Ollama)
├── docker-compose.cpu.yml     # Docker (CPU + Ollama)
├── docker-compose.external.yml# Docker (удалённая Ollama, только Django)
├── Dockerfile                 # Django container (Poetry-based)
├── entrypoint.sh              # Container entrypoint
├── .env.example               # Переменные окружения
│
├── rag_project/               # Django project config
│   ├── settings.py            # Настройки (prod-ready)
│   ├── urls.py                # Root URL conf
│   ├── wsgi.py                # WSGI (Gunicorn)
│   └── asgi.py                # ASGI
│
├── core/                      # Main Django app
│   ├── models.py              # Document, Chunk, ChatMessage
│   ├── views.py               # API + UI views
│   ├── serializers.py         # DRF serializers
│   ├── urls.py                # URL routing
│   ├── admin.py               # Django Admin config
│   ├── rag_pipeline.py        # RAG logic (extract, chunk, embed, search)
│   ├── authentication.py      # API Key auth
│   ├── middleware.py           # Request logging
│   └── exceptions.py          # Custom error handling
│
├── templates/core/            # Django Templates
│   ├── base.html              # Base layout (nav, stats, footer)
│   ├── index.html             # Chat interface
│   ├── docs.html              # Document management
│   └── partials/              # HTMX partial templates
│       ├── stats.html
│       ├── chat_messages.html
│       ├── chat_error.html
│       ├── chat_history.html
│       ├── upload_result.html
│       └── doc_list.html
│
└── static/core/css/
    └── main.css               # Responsive CSS (dark/light theme)
```

---

## Django Models

### Document
| Field             | Type          | Description            |
|-------------------|---------------|------------------------|
| filename          | CharField     | Уникальное имя файла   |
| original_filename | CharField     | Оригинальное имя       |
| file_path         | CharField     | Путь к файлу           |
| file_type         | CharField     | pdf / txt / md         |
| size              | BigIntegerField| Размер в байтах       |
| status            | CharField     | pending/processing/completed/error |
| uploaded_at       | DateTimeField | Дата загрузки          |
| processed_at      | DateTimeField | Дата обработки         |

### Chunk
| Field       | Type        | Description              |
|-------------|-------------|--------------------------|
| document    | ForeignKey  | Связь с Document         |
| content     | TextField   | Текст чанка              |
| chunk_index | IntegerField| Порядковый номер         |
| chroma_id   | CharField   | ID в ChromaDB            |
| metadata    | JSONField   | Метаданные               |

### ChatMessage
| Field    | Type      | Description           |
|----------|-----------|----------------------|
| role     | CharField | user / assistant      |
| content  | TextField | Текст сообщения       |
| sources  | JSONField | Источники (для AI)    |

---

## API Endpoints (Django REST Framework)

Все API endpoints требуют аутентификации: Django session или API key.

### Authentication

```bash
# API Key передаётся только в заголовке Authorization
curl -H "Authorization: Api-Key your-secret-api-key-change-me" http://localhost:8000/api/stats/
```

### Endpoints

| Method | URL                  | Description              |
|--------|---------------------|--------------------------|
| POST   | /api/upload/        | Загрузить документ       |
| POST   | /api/chat/          | Задать вопрос            |
| GET    | /api/docs/          | Список документов        |
| DELETE | /api/docs/{id}/     | Удалить документ         |
| POST   | /api/docs/{id}/reindex/ | Переиндексировать документ |
| GET    | /api/stats/         | Статистика системы       |
| GET    | /api/chat/history/  | История чата             |
| POST   | /api/chat/clear/    | Очистить историю         |

### Примеры

```bash
# Загрузить документ
curl -X POST http://localhost:8000/api/upload/ \
  -H "Authorization: Api-Key your-secret-api-key-change-me" \
  -F "file=@document.pdf"

# Задать вопрос
curl -X POST http://localhost:8000/api/chat/ \
  -H "Authorization: Api-Key your-secret-api-key-change-me" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is described in the document?"}'

# Получить список документов
curl http://localhost:8000/api/docs/ \
  -H "Authorization: Api-Key your-secret-api-key-change-me"

# Статистика
curl http://localhost:8000/api/stats/ \
  -H "Authorization: Api-Key your-secret-api-key-change-me"

# Удалить документ
curl -X DELETE http://localhost:8000/api/docs/1/ \
  -H "Authorization: Api-Key your-secret-api-key-change-me"

# Переиндексировать документ (файл уже на сервере, повторная загрузка не нужна)
curl -X POST http://localhost:8000/api/docs/1/reindex/ \
  -H "Authorization: Api-Key your-secret-api-key-change-me"
```

Переиндексация отвечает `202` при постановке в очередь, `409` если документ уже
обрабатывается или исходный файл отсутствует на диске, `503` при переполненной
очереди. Старые чанки документа удаляются из ChromaDB и PostgreSQL до запуска —
повторный запуск не дублирует индекс.

Массовая переиндексация выполняется командой `manage.py reindex_documents`
(`--status error|completed`, `--id N`, `--dry-run`). ChromaDB работает встроенным
клиентом и допускает одного писателя, поэтому **веб-сервис нужно остановить**
перед запуском команды.

---

## Настройки (.env)

Полный шаблон — в `.env.example`. Ключевые переменные:

```ini
# Django (обязательно сменить в production)
SECRET_KEY=django-insecure-change-me-in-production-abcdef123456
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0

# Суперпользователь (создаётся автоматически при первом старте контейнера)
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=change-me-before-first-run   # ОБЯЗАТЕЛЬНО изменить!
DJANGO_SUPERUSER_EMAIL=admin@localhost

# LLM Backend: "ollama" (прямое подключение) или "openwebui" (через Open WebUI)
LLM_BACKEND=ollama
OLLAMA_URL=http://ollama:11434
# OLLAMA_URL=http://localhost:11434        # локальная разработка
# OLLAMA_URL=http://192.168.1.100:11434    # удалённый сервер

EMBED_MODEL=nomic-embed-text
LLM_MODEL=mistral

# Таймаут запроса к Ollama, секунды. На CPU-машинах поднять при ошибках таймаута.
OLLAMA_REQUEST_TIMEOUT=300

# Ресурсные лимиты Ollama (только локальная Ollama в Docker)
OLLAMA_MAX_LOADED_MODELS=1      # не держать чат- и embedding-модель в RAM одновременно
OLLAMA_NUM_PARALLEL=1           # параллельные запросы умножают KV-кэш
OLLAMA_KEEP_ALIVE=5m
OLLAMA_CONTEXT_LENGTH=4096

# ChromaDB
CHROMA_PERSIST_DIR=/app/chroma_data
CHROMA_COLLECTION=rag_documents

# RAG — параметры качества и производительности
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
SEARCH_K=6                      # чанков на запрос
SEARCH_RELEVANCE_THRESHOLD=0.20 # 0.0 = без фильтрации; поднять при мусоре в ответах
EMBED_BATCH_SIZE=10             # снизить при нехватке памяти

# Загрузка файлов
MAX_UPLOAD_SIZE=26214400        # жёсткий лимит на документ, БАЙТЫ (25 МиБ)

# Gunicorn (Docker). Встроенная ChromaDB требует ровно один процесс.
GUNICORN_WORKERS=1
GUNICORN_THREADS=4

# API key (только заголовок Authorization: Api-Key <key>)
API_KEY=your-secret-api-key-change-me

# Logging
LOG_LEVEL=INFO
```

### Ограничения ресурсов на слабой машине (16 ГБ RAM)

Три группы настроек, которые определяют устойчивость системы:

| Настройка | По умолчанию | Зачем |
|---|---|---|
| `GUNICORN_WORKERS` | `1` | ChromaDB работает встроенно в процессе Django. Несколько процессов держали бы каждый свою копию HNSW-индекса и писали бы в один каталог одновременно — это риск повреждения индекса, а не только расход памяти. Масштабируйтесь через `GUNICORN_THREADS`. |
| `OLLAMA_NUM_PARALLEL` | `1` | Каждый параллельный запрос к Ollama умножает KV-кэш. На 16 ГБ это основной путь к OOM. |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Иначе чат-модель и embedding-модель занимают память одновременно. |
| `MAX_UPLOAD_SIZE` | `26214400` (25 МиБ) | Жёсткий лимит на документ. Проверяется до старта индексации. |

Индексация документов **сериализована**: одновременно обрабатывается ровно один документ,
остальные ждут в очереди (максимум 100 задач). Это исключает ситуацию, когда N
одновременных загрузок держат в памяти N наборов текста, чанков и векторов сразу.

При переполнении очереди загрузка отклоняется с кодом `503`; загруженный файл
сохраняется, документ помечается статусом «Ошибка» — его можно переиндексировать позже.

#### Доступ к PostgreSQL с хоста

Штатные Compose-конфигурации намеренно **не публикуют** порт PostgreSQL наружу —
Django обращается к базе по имени сервиса внутри Docker network. Если нужен доступ
с хоста (psql, GUI-клиент, дамп), используйте override только для разработки:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev-ports.yml up -d
# порт хоста можно переопределить: POSTGRES_HOST_PORT=55432
```

---

## Django Admin

Django Admin доступен по адресу: **http://localhost:8000/admin/**

Функциональность:
- Просмотр и управление документами
- Просмотр чанков с поиском по содержимому
- История чата
- Фильтры по статусу, типу файла, дате
- Поиск по имени файла и содержимому

---

## Troubleshooting

### Документ завис в статусе «Обрабатывается» или показывает «Ошибка индексации»

При перезапуске сервиса (или OOM-kill) документы в статусе «Обрабатывается» автоматически
переводятся в «Ошибка» с сообщением «Индексация прервана — переиндексируйте».
Удалите документ и загрузите снова.

Если индексация падает с ошибкой таймаута на слабой CPU-машине — поднять `OLLAMA_REQUEST_TIMEOUT`
в `.env` (напр. `600`) и перезапустить сервис.

### «Файл слишком большой»

Размер документа превышает `MAX_UPLOAD_SIZE` (по умолчанию 25 МиБ). Либо разбейте
документ на части, либо поднимите лимит в `.env` — с учётом того, что в пике
индексация занимает в несколько раз больше памяти, чем сам файл.

### «Очередь индексации переполнена»

Одновременно индексируется один документ, очередь ограничена 100 задачами.
Файл сохранён, но не проиндексирован. Дождитесь завершения текущих задач,
затем удалите документ и загрузите его повторно.

### Ollama не запускается

```bash
make ollama-status        # Проверить статус
make logs-ollama          # Docker логи Ollama
make restart              # Перезапустить все
```

### Модели не загружены

```bash
# Локально
make ollama-pull

# В Docker
docker exec -it rag-ollama ollama pull mistral
docker exec -it rag-ollama ollama pull nomic-embed-text
```

### Django не стартует

```bash
make logs-django                                  # Логи
docker exec -it rag-django python manage.py migrate  # Миграции
docker exec -it rag-django python manage.py createsuperuser
```

### ChromaDB ошибки

```bash
# Сбросить коллекцию (удалит все embeddings!)
docker exec -it rag-django python manage.py shell -c "
from core.rag_pipeline import RAGPipeline
p = RAGPipeline.get_instance()
p._chroma_client.delete_collection('rag_documents')
print('Collection deleted')
"
```

### Нет GPU / Docker GPU error

```bash
make up-cpu               # CPU-версия
```

### Удалённая Ollama не отвечает

```bash
# Проверить доступность
make ollama-check-remote

# Проверить, что Ollama слушает на всех интерфейсах (на сервере с Ollama):
# По умолчанию Ollama слушает только 127.0.0.1.
# Для доступа из сети задать переменную перед запуском:
#   OLLAMA_HOST=0.0.0.0:11434 ollama serve
# Или в systemd unit:
#   Environment="OLLAMA_HOST=0.0.0.0:11434"

# Проверить firewall на сервере с Ollama:
#   sudo ufw allow 11434/tcp
#   # или
#   sudo iptables -A INPUT -p tcp --dport 11434 -j ACCEPT

# Проверить модели на удалённом сервере:
#   curl http://192.168.1.100:11434/api/tags
```

### Open WebUI не отвечает / ошибка авторизации

```bash
# Полная проверка: связь + авторизация
make owui-status

# Проверить только ключ
make owui-check-key

# Список моделей
make owui-models
```

Типичные причины ошибок:
- **401/403** -- неверный API-ключ. Получить новый: Open WebUI -> Settings -> Account -> API Keys
- **Connection refused** -- Open WebUI не запущен или firewall блокирует порт 3000
- **Модель не найдена** -- убедиться, что модель загружена в Ollama, к которой подключён Open WebUI
- **OPENWEBUI_API_KEY пуст** -- Open WebUI требует ключ; без него запросы отклоняются

---

## Системные требования

- **OS:** Ubuntu 20.04+ / любой Linux
- **RAM:** минимум 8GB (рекомендуется 16GB)
- **Disk:** 10GB+ для моделей Ollama
- **GPU:** опционально (NVIDIA с CUDA для ускорения)
- **Docker:** 20.10+, Docker Compose v2
- **Python:** 3.11+
- **Poetry:** 1.8+
