# ROoP — Rag-Ollama-On-Premises

[![CI](https://github.com/Fgeeha/ROoP/actions/workflows/ci.yml/badge.svg)](https://github.com/Fgeeha/ROoP/actions/workflows/ci.yml)

100% локальная RAG-система: Django + ChromaDB + Ollama. Никаких облаков, никаких внешних API.

---

## Установка

**Что нужно заранее:** Docker и Docker Compose.

```bash
# 1. Скопировать репозиторий
git clone https://github.com/Fgeeha/ROoP.git
cd ROoP/rag_ollama

# 2. Создать .env и задать пароль администратора
cp .env.example .env
# Открыть .env и заполнить обязательные поля (см. таблицу ниже)

# 3. Запустить
make up-cpu        # CPU-машина (ноутбук, сервер без GPU)
# make up          # NVIDIA GPU
```

Первый запуск занимает несколько минут: скачиваются модели Ollama
(mistral ~4 GB, nomic-embed-text ~300 MB).

Открыть браузер: **http://localhost:8000**

Подробные варианты запуска (удалённый Ollama, Open WebUI, без Docker) — см. [`rag_ollama/README.md`](rag_ollama/README.md).

---

## Конфигурация

Все параметры задаются в `rag_ollama/.env`. Для начала достаточно задать три обязательных поля:

| Переменная | Обязательно | Дефолт | Когда менять |
|---|---|---|---|
| `DJANGO_SUPERUSER_PASSWORD` | **Да** | — | Задать перед первым запуском. Генерация: `python3 -c "import secrets; print(secrets.token_urlsafe(24))"` |
| `SECRET_KEY` | **Да** | `django-insecure-...` | Заменить на случайную строку длиной 50+ символов |
| `POSTGRES_PASSWORD` | **Да** | `change-me-in-production` | Задать надёжный пароль |
| `OLLAMA_REQUEST_TIMEOUT` | Нет | `300` | Поднять (напр. `600`) если индексация большого файла падает с ошибкой таймаута на слабой CPU-машине |
| `EMBED_BATCH_SIZE` | Нет | `10` | Снизить (напр. `5`) при нехватке памяти во время индексации |
| `SEARCH_K` | Нет | `6` | Поднять, если ответы неполные; снизить, если медленно |
| `SEARCH_RELEVANCE_THRESHOLD` | Нет | `0.20` | Поднять (напр. `0.35`) если в ответы попадает нерелевантный контекст; подбирается под свой корпус |
| `API_KEY` | Нет | `your-secret-api-key-change-me` | Задать при использовании REST API |

Полный список всех переменных — в [`rag_ollama/.env.example`](rag_ollama/.env.example).

---

## Troubleshooting

**Документ завис в статусе «Индексируется» или показывает «Ошибка»** — это значит, что индексация прервалась (сервер был перезапущен или закончилась память). Удалите документ через интерфейс и загрузите его снова. При следующем запуске сервиса зависшие документы автоматически переводятся в состояние ошибки.

**Другие проблемы** — см. раздел Troubleshooting в [`rag_ollama/README.md`](rag_ollama/README.md).
