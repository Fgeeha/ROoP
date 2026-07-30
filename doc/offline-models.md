# Модели Ollama без доступа к сети

Как получить модели, если `ollama pull` внутри контейнера не работает: закрытый
контур, корпоративный прокси с подменой TLS, машина вообще без интернета.

Документ описывает четыре способа, от самого простого к самому трудоёмкому.
Выбирайте первый, который применим в вашей ситуации.

| Способ | Когда подходит | Что нужно |
|---|---|---|
| [1. Pull на хосте](#способ-1--скачать-на-хосте-и-скопировать-в-volume) | Браузер и хост работают, падает только контейнер | Ollama на хосте |
| [2. Донорская машина](#способ-2--донорская-машина-с-чистым-каталогом) | Есть другая машина с доступом | Docker на донорской машине |
| [3. Выборочный перенос](#способ-3--выборочный-перенос-из-существующего-каталога) | На донорской машине уже много моделей | Docker, python3 |
| [4. GGUF-файл](#способ-4--импорт-из-gguf-последний-вариант) | Доступен только браузер | Файл GGUF |

Перед переносом моделей: если проблема в TLS-инспекции корпоративного прокси,
её обычно проще решить сертификатом — см. `make ollama-ca` и раздел
[`ollama pull` падает с `x509`](../rag_ollama/README.md#ollama-pull-падает-с-x509-certificate-signed-by-unknown-authority)
в README. Перенос файлов нужен, когда сертификат недоступен или реестр
`registry.ollama.ai` заблокирован целиком.

---

## Что именно нужно перенести

Это две независимые вещи, и без сети нужны обе:

**Модели** — веса, которые скачивает `ollama pull`. Лежат в Docker-volume
`rag_ollama_ollama_data`, внутри контейнера — в `/root/.ollama/models`.
Штатный набор для ROoP:

| Модель | Роль | Размер |
|---|---|---|
| `gemma3:4b` | чат-модель (`LLM_MODEL`) | 3,3 ГБ |
| `bge-m3` | embedding-модель (`EMBED_MODEL`) | 1,2 ГБ |

Подобрать другую пару под конкретное железо: `make models-recommend`. Если
меняете `EMBED_MODEL`, помните, что на уже проиндексированной установке
потребуется новая коллекция ChromaDB и полная переиндексация.

**Docker-образы** — `fgeeha/roop`, `ollama/ollama`, `postgres:16-alpine`.
Нужны, только если на рабочей машине нет доступа и к реестрам образов; см.
[перенос образов](#перенос-docker-образов).

---

## Как устроено хранилище моделей

Знать структуру нужно для способа 3.

```text
models/
├── blobs/
│   ├── sha256-dec52a44...   # веса, самый большой файл
│   ├── sha256-be595b49...   # config
│   ├── sha256-7339fa41...   # лицензия
│   └── sha256-9371364b...   # параметры
└── manifests/
    └── registry.ollama.ai/
        └── library/
            ├── gemma3/4b
            └── bge-m3/latest
```

Манифест — небольшой JSON со списком цифровых отпечатков нужных блобов
(здесь сокращённый манифест `gemma3:4b`):

```json
{
  "schemaVersion": 2,
  "config": { "digest": "sha256:b6ae5839...", "size": 489 },
  "layers": [
    { "mediaType": "application/vnd.ollama.image.model",    "digest": "sha256:aeda25e6...", "size": 3338792448 },
    { "mediaType": "application/vnd.ollama.image.template",  "digest": "sha256:e0a42594...", "size": 358 },
    { "mediaType": "application/vnd.ollama.image.license",   "digest": "sha256:dd084c7d...", "size": 8432 },
    { "mediaType": "application/vnd.ollama.image.params",    "digest": "sha256:3116c522...", "size": 77 }
  ]
}
```

Весь объём модели — в одном слое `image.model`; остальные слои весят вместе
меньше десяти килобайт, но без них модель неработоспособна: в `image.template`
лежит шаблон промпта, в `image.params` — стоп-токены и параметры генерации.

Два следствия:

* Блобы адресуются по содержимому, поэтому каталоги моделей можно **сливать**:
  повторный файл — это тот же файл, конфликтов не бывает.
* Модель без тега (`bge-m3`) хранится в каталоге `latest`, с тегом
  (`gemma3:4b`) — в каталоге `4b`. Это важно при сборке пути к манифесту.

---

## Способ 1 — скачать на хосте и скопировать в volume

Подходит, когда `ollama pull` падает только внутри контейнера, а на хосте
работает. Обычно так и бывает за корпоративным прокси: корневой сертификат
шлюза установлен в системе (поэтому работает браузер), но в образе Ollama его
нет.

Установите Ollama на хост, если её нет: <https://ollama.com/download>.

```bash
cd rag_ollama
make models-host        # прочитает LLM_MODEL и EMBED_MODEL из .env
```

Затем скопируйте скачанное в volume. Контейнер на время копирования лучше
остановить:

```bash
docker compose -f docker-compose.cpu.yml stop ollama

docker run --rm \
  -v rag_ollama_ollama_data:/dst \
  -v "$HOME/.ollama/models":/src:ro \
  alpine sh -c 'mkdir -p /dst/models && cp -a /src/. /dst/models/'

docker compose -f docker-compose.cpu.yml start ollama
make models-list
```

Volume монтируется в контейнер как `/root/.ollama`, поэтому модели идут в
`/dst/models`, а не в корень `/dst`.

> Имя volume зависит от имени проекта Compose. Для каталога `rag_ollama` это
> `rag_ollama_ollama_data`. Проверить: `docker volume ls | grep ollama`.

Способ копирует **все** модели с хоста. Если их там много, а перенести нужно
две — см. способ 3.

---

## Способ 2 — донорская машина с чистым каталогом

Полный офлайн: на рабочей машине сети нет вообще, есть другая машина с
доступом. Самый предсказуемый вариант, потому что каталог собирается с нуля и
содержит ровно то, что нужно.

**На машине с доступом:**

```bash
mkdir -p ~/roop-models

docker run -d --name ollama-donor \
  -v ~/roop-models:/root/.ollama \
  ollama/ollama:0.32.5

docker exec ollama-donor ollama pull gemma3:4b
docker exec ollama-donor ollama pull bge-m3
docker exec ollama-donor ollama list

docker rm -f ollama-donor

tar cf roop-models.tar -C ~/roop-models/models .
```

Архив без сжатия намеренно: веса моделей уже сжаты, `gzip` потратит время и
почти ничего не сэкономит. Ожидаемый размер для штатной пары — около 4,5 ГБ.

Файлы в `~/roop-models` создаст root — процесс Ollama в контейнере работает от
него. Права `755`/`644`, поэтому `tar` от обычного пользователя их прочитает, а
вот удалять каталог потом придётся через `sudo`.

Переносите `roop-models.tar` на рабочую машину любым разрешённым способом.

**На рабочей машине:**

```bash
cd rag_ollama
docker compose -f docker-compose.cpu.yml stop ollama    # если уже запущено

docker run --rm \
  -v rag_ollama_ollama_data:/dst \
  -v "$PWD":/in:ro \
  alpine sh -c 'mkdir -p /dst/models && tar xf /in/roop-models.tar -C /dst/models'
```

Если volume ещё не существует, создайте его заранее — `docker volume create
rag_ollama_ollama_data` — либо один раз запустите стек, чтобы Compose создал
volume сам.

Дальше — [запуск без сети](#запуск-без-сети) и [проверка](#проверка-после-переноса).

---

## Способ 3 — выборочный перенос из существующего каталога

Когда на донорской машине уже стоит Ollama с десятком моделей, а переносить
нужно две. Скрипт читает манифест каждой модели и копирует только те блобы, на
которые он ссылается.

**На машине с доступом:**

```bash
STAGE=~/roop-models-export
SRC=~/.ollama/models
mkdir -p "$STAGE/blobs"

for MODEL in gemma3:4b bge-m3; do
  NAME=${MODEL%%:*}
  case "$MODEL" in *:*) TAG=${MODEL#*:} ;; *) TAG=latest ;; esac
  MAN="$SRC/manifests/registry.ollama.ai/library/$NAME/$TAG"

  if [ ! -f "$MAN" ]; then
    echo "Нет манифеста для $MODEL — сначала: ollama pull $MODEL" >&2
    exit 1
  fi

  mkdir -p "$STAGE/manifests/registry.ollama.ai/library/$NAME"
  cp "$MAN" "$STAGE/manifests/registry.ollama.ai/library/$NAME/$TAG"

  python3 -c "
import json, sys
m = json.load(open(sys.argv[1]))
for d in [m['config']['digest']] + [l['digest'] for l in m['layers']]:
    print(d.replace(':', '-'))
" "$MAN" | while read -r BLOB; do
    [ -f "$STAGE/blobs/$BLOB" ] || cp "$SRC/blobs/$BLOB" "$STAGE/blobs/$BLOB"
  done
done

du -sh "$STAGE"
tar cf roop-models.tar -C "$STAGE" .
```

Проверка `[ -f ... ]` перед копированием нужна не для корректности, а для
скорости: разные модели часто ссылаются на одни и те же блобы параметров и
лицензий, и повторно копировать их незачем.

Импорт на рабочей машине — тот же, что в способе 2.

---

## Перенос Docker-образов

Нужен, если на рабочей машине недоступны и Docker Hub с GHCR. Иначе достаточно
`make pull-images`.

**На машине с доступом:**

```bash
docker pull fgeeha/roop:latest
docker pull ollama/ollama:0.32.5
docker pull postgres:16-alpine

docker save \
  fgeeha/roop:latest \
  ollama/ollama:0.32.5 \
  postgres:16-alpine \
  | gzip > roop-images.tar.gz
```

Около 5,5 ГБ без сжатия. Здесь `gzip` уместен, в отличие от моделей: слои
образов в выводе `docker save` не сжаты.

Тег Ollama берите тот же, что в `.env` (`OLLAMA_IMAGE_TAG`). В production
закрепляйтесь на версии образа ROoP, а не на `latest`, — тогда и переносите
именно её.

**На рабочей машине:**

```bash
gunzip -c roop-images.tar.gz | docker load
docker images | grep -E 'roop|ollama|postgres'
```

---

## Запуск без сети

Одна деталь, о которую легко споткнуться: в Compose есть сервис `ollama-pull`,
который на старте пытается скачать модели из реестра. Без сети он упадёт.
Критичным это не является — у сервиса `restart: "no"`, остальной стек
поднимется, — но в логах будет ошибка, а `make up-image*` вообще начинается с
`docker compose pull` и упадёт раньше.

Поэтому запускайте нужные сервисы по именам:

```bash
cd rag_ollama
docker compose -f docker-compose.cpu.yml up -d --no-build postgres ollama django

# GPU-режим:
# docker compose up -d --no-build postgres ollama django
```

Проверьте, что в `.env` значения совпадают с тем, что фактически перенесено:

```ini
LLM_MODEL=gemma3:4b
EMBED_MODEL=bge-m3
OLLAMA_IMAGE_TAG=0.32.5
ROOP_IMAGE=fgeeha/roop:latest
```

Несовпадение `LLM_MODEL` с именем перенесённой модели даёт ошибку «модель не
найдена» уже при первом запросе, а не при старте, — сверьте заранее.

---

## Проверка после переноса

```bash
# 1. Ollama видит модели
docker exec roop-ollama ollama list

# 2. Чат-модель отвечает
docker exec roop-ollama ollama run gemma3:4b "Ответь одним словом: работает?"

# 3. Embedding-модель считает векторы (ROoP использует /api/embed)
docker exec roop-ollama curl -s http://localhost:11434/api/embed \
  -d '{"model":"bge-m3","input":"проверка"}' | head -c 120
```

Третья проверка — самая важная: без неё ошибка embedding-модели обнаружится
только при индексации первого документа. Ответ должен начинаться с
`{"model":"bge-m3","embeddings":[[`.

Затем откройте http://localhost:8000, загрузите небольшой документ и задайте по
нему вопрос — это проверяет всю цепочку целиком.

---

## Частые ошибки

**`ollama list` пустой после копирования.** Модели попали не туда: volume
монтируется как `/root/.ollama`, значит целевой путь — `/dst/models`, а не
`/dst`. Проверьте:

```bash
docker exec roop-ollama ls /root/.ollama/models
```

**`Error: model 'gemma3:4b' not found`, хотя `ollama list` её показывает.**
Расхождение имени: в `.env` указан тег, которого нет. `ollama list` печатает
имя ровно в том виде, в котором его ждёт `LLM_MODEL`.

**`ollama pull` на уже перенесённую модель падает с ошибкой сети.** Так и
должно быть: `pull` всегда сверяет манифест с реестром. На локальную модель это
не влияет — `ollama run`, генерация и embeddings работают полностью офлайн.
Поэтому `make models` в закрытом контуре запускать не нужно, а сервис
`ollama-pull` в Compose лучше не поднимать (см. выше).

**Не хватает места.** Перенос требует места дважды: под архив и под
распакованные блобы. Для штатной пары моделей это примерно 9 ГБ на время
операции. Архив можно удалить сразу после успешной проверки.

**Права на файлы.** Копирование через контейнер `alpine` выполняется от root,
как и сам процесс Ollama в контейнере, — права совпадают. Если копировали
как-то иначе, проверьте владельца: `docker exec roop-ollama ls -la
/root/.ollama/models/blobs | head`.

---

## Способ 4 — импорт из GGUF (последний вариант)

Когда доступен только браузер, а реестр Ollama закрыт: скачать файл GGUF
вручную (например, с Hugging Face) и импортировать его.

```bash
# 1. Скачать GGUF браузером, например gemma-3-4b-it-Q4_K_M.gguf

# 2. Положить файл и Modelfile в контейнер
printf 'FROM /tmp/gemma-3-4b-it-Q4_K_M.gguf\n' > Modelfile
docker cp gemma-3-4b-it-Q4_K_M.gguf roop-ollama:/tmp/
docker cp Modelfile roop-ollama:/tmp/

# 3. Создать модель под тем именем, которое ждёт .env
docker exec roop-ollama ollama create gemma3:4b -f /tmp/Modelfile
docker exec roop-ollama rm /tmp/gemma-3-4b-it-Q4_K_M.gguf
```

Почему это последний вариант:

* Из «голого» GGUF Ollama выводит шаблон промпта по метаданным файла. Для
  известных архитектур это работает, для остальных шаблон и стоп-токены
  придётся прописать в `Modelfile` вручную (`TEMPLATE`, `PARAMETER stop`).
  Неверный шаблон не ломает запуск — он молча портит качество ответов.
* Для embedding-модели способ подходит хуже: важна не только архитектура, но и
  совпадение размерности векторов с тем, чем индексировалась коллекция
  ChromaDB. `bge-m3` даёт 1024, и коллекция, созданная другой моделью, начнёт
  отклонять запись с ошибкой размерности.
* Квантование в имени файла (`Q4_K_M`, `Q8_0`) определяет и размер, и качество.
  Штатным моделям ROoP соответствует Q4_K_M.

Если открыт хотя бы `hf.co`, проще обойтись без файлов вручную — Ollama умеет
тянуть модели напрямую:

```bash
docker exec roop-ollama ollama pull hf.co/<repo>/<файл>:Q4_K_M
```

---

## См. также

* [`rag_ollama/README.md`](../rag_ollama/README.md) — Troubleshooting, в том
  числе разбор ошибки `x509` и настройка корпоративного прокси.
* `make models-recommend` — подбор пары моделей под конкретное железо.
* `make help` — полный список целей Makefile.
