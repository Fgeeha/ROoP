# ROoP -- Примеры развертывания (Production)

Готовые docker-compose файлы для быстрого запуска ROoP в production.
Используют собранный образ `fgeeha/roop:latest` из Docker Hub -- ничего компилировать не нужно.

## Структура

```
examples/
  .env.example                   # Шаблон переменных окружения
  docker-compose.gpu.yml         # GPU (NVIDIA) + локальный Ollama
  docker-compose.cpu.yml         # CPU-only + локальный Ollama
  docker-compose.external.yml    # Удалённый Ollama / Open WebUI
```

## Быстрый старт

```bash
# 1. Скопируйте нужный compose-файл и .env
cp .env.example .env

# 2. Отредактируйте .env
nano .env

# 3. Запустите (выберите один из вариантов ниже)
docker compose -f docker-compose.gpu.yml up -d
```

Откройте `http://localhost:8000` в браузере.

---

## Описание compose-файлов

### docker-compose.gpu.yml

**Для серверов с NVIDIA GPU.**

| Сервис | Образ | Описание |
|---|---|---|
| `postgres` | `postgres:16-alpine` | База данных PostgreSQL. Данные хранятся в volume `postgres_data`. |
| `ollama` | `ollama/ollama:latest` | LLM-сервер с доступом к GPU через NVIDIA Container Toolkit. |
| `ollama-pull` | `ollama/ollama:latest` | Init-контейнер: автоматически скачивает модели `mistral` и `nomic-embed-text` при первом запуске. Завершается после загрузки. |
| `django` | `fgeeha/roop:latest` | Основное приложение ROoP. При старте: ожидает PostgreSQL, запускает миграции, создаёт суперпользователя, запускает Gunicorn. |

**Требования:** Docker, Docker Compose, NVIDIA GPU + nvidia-container-toolkit.

---

### docker-compose.cpu.yml

**Для серверов без GPU.** Аналогичен GPU-варианту, но без секции `deploy.resources.reservations.devices`. Ollama будет работать на CPU (медленнее, но функционально).

| Сервис | Образ | Описание |
|---|---|---|
| `postgres` | `postgres:16-alpine` | База данных PostgreSQL. |
| `ollama` | `ollama/ollama:latest` | LLM-сервер (CPU-only). |
| `ollama-pull` | `ollama/ollama:latest` | Загрузка моделей. |
| `django` | `fgeeha/roop:latest` | Основное приложение. |

**Требования:** Docker, Docker Compose.

---

### docker-compose.external.yml

**Ollama запущен на другом сервере** (или используется Open WebUI как прокси).
Этот файл не поднимает контейнер Ollama -- только PostgreSQL и Django.

| Сервис | Образ | Описание |
|---|---|---|
| `postgres` | `postgres:16-alpine` | База данных PostgreSQL. |
| `django` | `fgeeha/roop:latest` | Основное приложение. Подключается к удалённому Ollama по сети. |

В `.env` укажите адрес Ollama или Open WebUI:

```bash
# Вариант A: прямое подключение к Ollama
LLM_BACKEND=ollama
OLLAMA_URL=http://192.168.1.100:11434

# Вариант B: через Open WebUI
LLM_BACKEND=openwebui
OPENWEBUI_URL=http://192.168.1.100:3000
OPENWEBUI_API_KEY=sk-...
```

**Требования:** Docker, Docker Compose, доступ к удалённому Ollama/Open WebUI по сети.

---

## Описание сервисов

### postgres

PostgreSQL 16 (Alpine). Хранит пользователей, документы, историю чатов, shared-ссылки.

- **Volume:** `postgres_data` -- данные БД сохраняются между перезапусками.
- **Healthcheck:** `pg_isready` -- Django не запустится, пока БД не будет готова.
- **Переменные:** `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` -- берутся из `.env`.

### ollama

Локальный LLM-сервер. Генерирует ответы (модель `mistral`) и эмбеддинги (модель `nomic-embed-text`).

- **Volume:** `ollama_data` -- скачанные модели сохраняются между перезапусками.
- **Healthcheck:** проверяет `/api/tags` endpoint.
- **Порт:** `11434` (проброшен на хост для отладки, можно убрать в production).

### ollama-pull

Одноразовый init-контейнер. Подключается к `ollama` и скачивает нужные модели. После завершения останавливается (`restart: "no"`).

### django (ROoP)

Основное веб-приложение. При старте:

1. Ожидает доступность PostgreSQL (до 60 секунд).
2. Применяет Django-миграции (`manage.py migrate`).
3. Собирает статику (`manage.py collectstatic`).
4. Создаёт суперпользователя (если задан `DJANGO_SUPERUSER_USERNAME`).
5. Синхронизирует метаданные ChromaDB.
6. Запускает Gunicorn (3 workers, порт 8000).

- **Volumes:**
  - `chroma_data` -- векторная база ChromaDB
  - `media_data` -- загруженные документы (PDF, TXT, MD)
  - `log_data` -- логи приложения
- **Порт:** `8000`

---

## Переменные окружения (.env)

| Переменная | Описание | Пример |
|---|---|---|
| `SECRET_KEY` | Django secret key (обязательно сменить!) | `random-50-char-string` |
| `DEBUG` | Режим отладки | `False` |
| `ALLOWED_HOSTS` | Разрешённые хосты (через запятую) | `localhost,127.0.0.1,10.0.0.5` |
| `POSTGRES_DB` | Имя базы данных | `roop` |
| `POSTGRES_USER` | Пользователь БД | `roop` |
| `POSTGRES_PASSWORD` | Пароль БД (сменить!) | `strong-password` |
| `LLM_BACKEND` | Бэкенд LLM: `ollama` или `openwebui` | `ollama` |
| `OLLAMA_URL` | Адрес Ollama | `http://ollama:11434` |
| `OPENWEBUI_URL` | Адрес Open WebUI | `http://192.168.1.100:3000` |
| `OPENWEBUI_API_KEY` | API-ключ Open WebUI | `sk-...` |
| `EMBED_MODEL` | Модель для эмбеддингов | `nomic-embed-text` |
| `LLM_MODEL` | Модель для генерации | `mistral` |
| `EMAIL_HOST` | SMTP-сервер | `smtp.yandex.ru` |
| `EMAIL_PORT` | SMTP-порт (465=SSL, 587=TLS) | `465` |

Полный список см. в `.env.example`.

---

## Управление

```bash
# Статус сервисов
docker compose -f docker-compose.gpu.yml ps

# Логи Django
docker compose -f docker-compose.gpu.yml logs -f django

# Логи PostgreSQL
docker compose -f docker-compose.gpu.yml logs -f postgres

# Перезапуск Django (после изменения .env)
docker compose -f docker-compose.gpu.yml restart django

# Остановка всех сервисов
docker compose -f docker-compose.gpu.yml down

# Остановка с удалением данных (ОСТОРОЖНО!)
docker compose -f docker-compose.gpu.yml down -v

# Обновление образа до последней версии
docker compose -f docker-compose.gpu.yml pull django
docker compose -f docker-compose.gpu.yml up -d django

# Создание бэкапа БД
docker compose -f docker-compose.gpu.yml exec postgres \
  pg_dump -U roop roop > backup_$(date +%Y%m%d).sql

# Восстановление бэкапа
docker compose -f docker-compose.gpu.yml exec -T postgres \
  psql -U roop roop < backup_20250210.sql
```
