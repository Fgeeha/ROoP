# RAG Ollama - Local AI Assistant

Production-ready RAG (Retrieval-Augmented Generation) система на Django для корпоративного использования в закрытом контуре. 100% локально, без облаков, без внешних API.

## Tech Stack

- **Backend:** Django 5.1 + Django REST Framework
- **LLM:** Ollama (gemma3:4b + bge-m3, подбираются под железо через `make models-recommend`)
- **Vector DB:** ChromaDB (persistent local storage)
- **Frontend:** Django Templates + HTMX + Alpine.js
- **Documents:** PDF, TXT, MD
- **Auth:** Django sessions + API key
- **Package Manager:** Poetry
- **Automation:** Makefile

---

## Quick Start

### Вариант 0. Готовый образ, без сборки

Django-образ публикуется в Docker Hub и GitHub Packages. Если не нужно менять код,
собирать его локально незачем:

```bash
cd rag_ollama
cp .env.example .env

make up-image            # GPU
make up-image-cpu        # CPU
make up-image-external   # удалённая Ollama
```

Эти цели делают `docker compose pull` и запускают с `--no-build`: сборка не
произойдёт даже если Dockerfile изменился. Какой образ брать — задаётся
`ROOP_IMAGE` в `.env` (по умолчанию `fgeeha/roop:latest`).
В production закрепляйтесь на теге версии или sha, а не на `latest`.

Варианты ниже собирают образ локально.

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

Первый запуск занимает время -- скачиваются модели Ollama (gemma3:4b ~3.3GB, bge-m3 ~1.2GB).
Подобрать модели под своё железо: `make models-recommend`.

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
# ssh user@192.168.1.100 "ollama pull gemma3:4b && ollama pull bge-m3"
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
make models-host
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
EMBED_MODEL=bge-m3
LLM_MODEL=gemma3:4b
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
| `make models-recommend`  | Подобрать модели под это железо (RAM/GPU)         |
| `make models`            | Скачать модели из `.env` в контейнер Ollama       |
| `make models-host`       | Скачать модели в Ollama, установленную на хосте   |
| `make models-list`       | Список моделей в контейнере Ollama                |
| `make ollama-ca`         | Собрать CA-bundle для pull за корпоративным прокси|
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
| `make pull-images`       | Скачать опубликованные образы, ничего не собирая |
| `make up-image`          | Запустить из готового образа, без сборки (GPU) |
| `make up-image-cpu`      | Запустить из готового образа, без сборки (CPU) |
| `make up-image-external` | Запустить из готового образа (удалённая Ollama)|
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

EMBED_MODEL=bge-m3
LLM_MODEL=gemma3:4b

# Таймаут запроса к Ollama, секунды. На CPU-машинах поднять при ошибках таймаута.
OLLAMA_REQUEST_TIMEOUT=300

# Ресурсные лимиты Ollama (только локальная Ollama в Docker)
OLLAMA_MAX_LOADED_MODELS=1      # не держать чат- и embedding-модель в RAM одновременно
OLLAMA_NUM_PARALLEL=1           # параллельные запросы умножают KV-кэш
OLLAMA_KEEP_ALIVE=5m
OLLAMA_CONTEXT_LENGTH=4096
OLLAMA_IMAGE_TAG=0.32.5         # версия образа закреплена намеренно

# Готовый образ Django для make up-image
ROOP_IMAGE=fgeeha/roop:latest

# Корпоративная сеть: CA-bundle для pull за TLS-инспекцией, путь ВНУТРИ контейнера
OLLAMA_SSL_CERT_FILE=
# HTTPS_PROXY=http://proxy.corp.local:3128
# NO_PROXY=localhost,127.0.0.1,ollama,postgres,django

# ChromaDB
CHROMA_PERSIST_DIR=/app/chroma_data
CHROMA_COLLECTION=rag_documents

# RAG — параметры качества и производительности
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
SEARCH_K=6                      # чанков на запрос
SEARCH_RELEVANCE_THRESHOLD=0.20 # 0.0 = без фильтрации; поднять при мусоре в ответах
EMBED_BATCH_SIZE=10             # снизить при нехватке памяти
MAX_CONTEXT_CHARS=0             # бюджет контекста в промпте; 0 = из OLLAMA_CONTEXT_LENGTH

# Загрузка файлов
MAX_UPLOAD_SIZE=26214400        # жёсткий лимит на документ, БАЙТЫ (25 МиБ)

# Gunicorn (Docker). Встроенная ChromaDB требует ровно один процесс.
GUNICORN_WORKERS=1
GUNICORN_THREADS=4

# API key (только заголовок Authorization: Api-Key <key>)
API_KEY=your-secret-api-key-change-me

# Публичные ссылки: срок жизни новой ссылки в днях, 0 = бессрочно
SHARE_LINK_TTL_DAYS=30

# Logging
LOG_LEVEL=INFO
```

### Выбор моделей

Значения по умолчанию (`gemma3:4b` + `bge-m3`) рассчитаны на машину с 16 ГБ RAM
без GPU. Подобрать под конкретное железо:

```bash
make models-recommend    # смотрит RAM, ядра, VRAM и печатает строки для .env
make models              # скачивает LLM_MODEL и EMBED_MODEL из .env
make models-list         # что уже загружено
```

Скрипт считает бюджет памяти так: при наличии NVIDIA GPU — VRAM минус 1 ГБ;
без GPU — RAM минус 4.5 ГБ на остальной стек (Django, ChromaDB, PostgreSQL, ОС),
но не более 6 ГБ. Верхняя граница на CPU стоит намеренно: там ограничивает не
память, а скорость генерации — 7B-модель на процессоре отвечает минутами.

**Чат-модель**

| Модель | Размер | Когда |
|---|---|---|
| `gemma3:1b` | 0.8 ГБ | меньше 6 ГБ RAM, качество ответов заметно ниже |
| `llama3.2:3b` | 2.0 ГБ | 8 ГБ RAM; по-русски слабее gemma3 |
| `gemma3:4b` | 3.3 ГБ | **по умолчанию**: 16 ГБ RAM или GPU от 6 ГБ |
| `qwen2.5:7b` | 4.7 ГБ | GPU от 8 ГБ |
| `gemma3:12b` | 8.2 ГБ | GPU от 12 ГБ |

**Embedding-модель**

| Модель | Размер | Размерность | Когда |
|---|---|---|---|
| `embeddinggemma` | 0.6 ГБ | 768 | мало памяти |
| `bge-m3` | 1.2 ГБ | 1024 | **по умолчанию**: мультиязычная, контекст 8192 |

Предыдущее значение по умолчанию, `nomic-embed-text`, обучено только на
английском и хуже ищет по русским документам. Оно продолжает работать, но для
новых установок не рекомендуется.

> **Смена `EMBED_MODEL` требует полной переиндексации.** Размерность векторов у
> моделей разная, и ChromaDB вернёт ошибку размерности при попытке дописать
> новые векторы в старую коллекцию. Порядок: задать новое `CHROMA_COLLECTION`,
> перезапустить, затем
> `make docker-manage CMD="reindex_documents --status completed"`.
> Смена `LLM_MODEL` переиндексации не требует.

### Бюджет контекста

Ollama молча обрезает промпт, который не влез в `OLLAMA_CONTEXT_LENGTH`. Без
ограничения на стороне Django поднятый `SEARCH_K` приводил бы к ответу,
построенному по части найденного контекста, причём ни в интерфейсе, ни в API не
было бы признака, что остальное отброшено.

`MAX_CONTEXT_CHARS` задаёт, сколько символов найденного контекста разрешено
положить в промпт. Чанки добавляются по убыванию релевантности, пока бюджет не
исчерпан; не поместившиеся отсекаются и **не попадают в список источников** —
показывать источник, по которому ответ не строился, было бы неверно. Факт
отсечения пишется в лог и возвращается в API-ответе полем `context_truncated`.
Первый чанк добавляется всегда: ответ вообще без контекста хуже, чем промпт,
немного вышедший за бюджет.

По умолчанию (`MAX_CONTEXT_CHARS=0`) бюджет считается из
`OLLAMA_CONTEXT_LENGTH`: из окна вычитается резерв на ответ, инструкцию и сам
вопрос, остаток переводится в символы по консервативной оценке 2.5 символа на
токен (кириллица дороже латиницы). При окне 4096 это 7040 символов.

Штатной конфигурации этого хватает впритык: `SEARCH_K=6` × `CHUNK_SIZE=1000`
плюс разделители — 6035 символов. Поднимая `SEARCH_K` или `CHUNK_SIZE`,
поднимайте и `OLLAMA_CONTEXT_LENGTH` — иначе лишние чанки будут отсекаться, и
`SEARCH_K` перестанет что-либо менять. Помните, что большее окно означает
больший KV-кэш и расход памяти.

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
make models

# В Docker
docker exec -it roop-ollama ollama pull gemma3:4b
docker exec -it roop-ollama ollama pull bge-m3
```

### `ollama pull` падает с `x509: certificate signed by unknown authority`

```text
Error: pull model manifest: Get "https://registry.ollama.ai/v2/library/...":
tls: failed to verify certificate: x509: certificate signed by unknown authority
```

Типичная корпоративная сеть: шлюз расшифровывает TLS и подписывает соединения
своим корневым сертификатом. В браузере всё открывается, потому что этот
сертификат установлен в системе — но внутри контейнера Ollama его нет, там
только штатный набор корневых сертификатов образа.

Проверить, что дело именно в этом:

```bash
docker exec -it roop-ollama sh -c \
  'wget -qO- https://registry.ollama.ai/v2/ 2>&1 | head -3'
```

**Решение — добавить корпоративный CA в контейнер.** Нужен файл корневого
сертификата в формате PEM. Обычно он уже лежит в системе
(`/usr/local/share/ca-certificates/`), либо его выдаёт служба поддержки, либо
его можно выгрузить из браузера: замок в адресной строке -> сведения о
сертификате -> корневой в цепочке -> экспорт в PEM/CRT.

```bash
make ollama-ca CA=/usr/local/share/ca-certificates/corp-root.crt
```

Цель склеивает системный набор сертификатов с корпоративным в
`certs/ca-bundle.crt`. Каталог `certs/` уже смонтирован в контейнер как
`/certs` — остаётся указать путь **внутри контейнера** в `.env`:

```ini
OLLAMA_SSL_CERT_FILE=/certs/ca-bundle.crt
```

```bash
make down && make up-cpu && make models
```

Важно использовать именно склеенный bundle, а не один корпоративный
сертификат: `SSL_CERT_FILE` **заменяет** набор корневых сертификатов целиком,
и с одним CA перестанет проверяться всё остальное.

**Если вместо подмены TLS используется обычный HTTP-прокси**, сертификат не
нужен — достаточно прописать в `.env`:

```ini
HTTPS_PROXY=http://proxy.corp.local:3128
HTTP_PROXY=http://proxy.corp.local:3128
NO_PROXY=localhost,127.0.0.1,ollama,postgres,django
```

Переменные пробрасываются в сервисы `ollama` и `ollama-pull`. `NO_PROXY`
обязателен: без него Django пойдёт к Ollama через внешний прокси.

**Если ни то ни другое недоступно**, модели переносятся файлами с машины, где
`pull` работает. Самый короткий вариант — скачать на хосте и скопировать в
volume:

```bash
make models-host        # pull на хосте, где сертификат уже в системе

docker compose -f docker-compose.cpu.yml stop ollama
docker run --rm \
  -v rag_ollama_ollama_data:/dst \
  -v "$HOME/.ollama/models":/src:ro \
  alpine sh -c 'mkdir -p /dst/models && cp -a /src/. /dst/models/'
docker compose -f docker-compose.cpu.yml start ollama
```

Имя volume уточните через `docker volume ls` — оно зависит от имени проекта
Compose.

Полностью изолированный контур, выборочный перенос отдельных моделей, перенос
Docker-образов и импорт из GGUF описаны отдельно:
[`doc/offline-models.md`](../doc/offline-models.md).

### Django не стартует

```bash
make logs-django                                  # Логи
docker exec -it roop-django python manage.py migrate  # Миграции
docker exec -it roop-django python manage.py createsuperuser
```

### ChromaDB ошибки

```bash
# Сбросить коллекцию (удалит все embeddings!)
docker exec -it roop-django python manage.py shell -c "
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
