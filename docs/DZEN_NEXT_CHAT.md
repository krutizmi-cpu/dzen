# Передача сервиса Дзена другому чату — 5 октября 2026

Это актуальное состояние. Документ DZEN_HANDOFF_2026-10-04.md содержит историю и устаревшие сведения, которые не должны переопределять этот файл. Паролей, токенов, cookies и SSH-ключей здесь нет.

## Задача и главное ограничение

Пользователю нужен продукт, который принимает или пишет качественные статьи с иллюстрациями и автоматически загружает/публикует их в выбранный канал Дзена. Ручная загрузка не удовлетворяет запрос. Другие проекты должны использовать единый API. У пользователя ОДИН аккаунт с доступом к ПЯТИ каналам. Нельзя делать отдельный сервис для каждого канала.

Сейчас работают серверная панель, API, SQLite-очередь и предпросмотр. Авторизации в Дзен, сохранённой сессии Дзена, живого загрузчика и автопубликации нет. ArticleQueue.process_one() заканчивается BLOCKED / DZEN_TRANSPORT_UNAVAILABLE. Кнопка входа в Дзен недоступна. Статус NOT_CONFIGURED фиксирован, это не проверка пользовательского аккаунта. Постановка в очередь не означает создания черновика на площадке.

## Адреса, сервер и доступ

- Панель: https://galvanize.ru/dz/
- Health: https://galvanize.ru/dz/health
- API base: https://galvanize.ru/dz/api/v1/
- SSH alias в настроенной среде владельца: ai-projects-main. Другой компьютер может не иметь этого alias/SSH-ключа.
- systemd: dzen-autopost.service; пользователь dzen-autopost; loopback 127.0.0.1:8766.
- Код: /srv/projects/dzen-autopost/current → /srv/projects/dzen-autopost/releases/20261005-integration-ui.
- Данные: /var/lib/dzen-autopost; SQLite queue.sqlite3, media, ключ api-token.txt. Не удалять и не переносить их в Git.
- Ключ владельца локально: C:\Users\<USER>\AppData\Local\DzenAutopostService\galvanize-server-api-token.txt. На сервере: /var/lib/dzen-autopost/api-token.txt. Значения получать из защищённого файла, не из чата.
- Ключ API открывает НАШУ панель, он не является паролем/сессией Дзена. После перезагрузки вкладки требуется повторный ввод; ключ хранится только в JS-памяти страницы.
- Основная платформа /srv/galvanize-platform и galvanize-platform.service не относятся к этому сервису. Не заменять приложение и не перезапускать его ради /dz.
- nginx-маршрут /dz/ уже настроен. TLS существующего сайта, rate limit 5 запросов/с burst 15, POST 13m. Внутренний порт 8765 занят другим сервисом.
- Общий deploy lock: /var/lock/galvanize-platform-deploy.lock.
- Предыдущий release: /srv/projects/dzen-autopost/releases/20261004-dz-v1. У нового release .venv ссылается на .venv предыдущего; старый release НЕЛЬЗЯ удалять, пока эта зависимость не устранена.
- Откат кода: под deploy lock атомарно вернуть current на предыдущий release и перезапустить ТОЛЬКО dzen-autopost.service; проверить /dz/health и основной сайт. Указатель записан в /srv/backups/dzen-autopost-20261005-integration-ui/previous-release.txt. Данные оставить.
- Initial-deploy и одноразовый update_integration_20261005.py не являются универсальными скриптами очередной выкладки. Готовить новый release и новый план отката.

Чат с исходными серверными сведениями: <available-in-local-handoff> («00 — Оркестратор Galvanize»). Пользователь ранее разрешил этому чату запросить данные у него. Не пересылать секреты и не считать это разрешением всем будущим чатам отправлять сообщения без пользовательской авторизации.

## Каналы

Все привязаны к account_key=shared-dzen-account. ID взяты из ссылок пользователя; живые права агент не проверял.

| project_key | Канал | channel_id | Сайт проекта |
|---|---|---|---|
| galvanize | Galvanize | 6a2e548cf214f66a41b5faec | Galvanize.ru |
| ernest | Английский бульдог / Эрнест | 622e4a050e26331f271e5881 | Нет |
| lifeplay | LIFE PLAY | 6a7f29e5738ff054735000cf | Life-play.ru |
| krutizmi | KrutiZmi | 6a8067d72bc81f5f3179fbcd | KrutiZmi.ru |
| cdekarbat | Cdek Arbat | 6a80704ba055ec3603b2963d | Cdeklogic.ru |

Публичные адреса и имена в config/dzen-channels.json. Исходные пользовательские черновики НЕ созданы агентом; не перезаписывать их при тестировании. Их ID есть в исторической передаче.

## Состав кода

- product_kb/dzen_autopost.py: общая долговечная очередь, проверки статей/изображений, идемпотентность, локальное превью; живой транспорт отключён.
- product_kb/dzen_autopost_client.py: DzenQueueClient для loopback или HTTPS с префиксом /dz. С Дзеном не связывается.
- product_kb/dzen_integration.py: Protocol ArticleAdapter и read-only описание отсутствующего подключения. К воркеру не подключён.
- product_kb_api/dzen_autopost_service.py: FastAPI, Bearer auth, TrustedHost, ограничения запросов, root_path.
- product_kb_api/dzen_autopost_dashboard.html: форма, загрузка картинок, очередь, sandbox srcdoc предпросмотр, раздел состояния подключения.
- scripts/run_dzen_autopost.py: запуск на loopback.
- scripts/demo_dzen_queue.py: только локальная постановка оригинальной тестовой статьи в очередь; не публикация.
- config/dzen-channels.json: пять серверных привязок.
- tests/test_dzen_autopost.py: 18 тестов.
- sample/: оригинальная статья и три оригинальные PNG-схемы.
- docs/dzen-autopost-service.md: подробности API. docs/dzen-adapter-contract.md: контракт будущего адаптера.

У репозитория должен быть только этот сервис, документация и тестовые изображения. Не выгружать целиком исходную рабочую папку New project: там посторонние проекты и пользовательские файлы. Не включать runtime, журналы с секретами, SSH-файлы, сторонние клоны и браузерные профили.

## Локальный запуск и проверки

Python 3.12/3.13. Использовать отдельное окружение. На Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dzen.txt
.\.venv\Scripts\python.exe -m pytest tests/test_dzen_autopost.py -q
.\.venv\Scripts\python.exe scripts/run_dzen_autopost.py
```

По умолчанию адрес http://127.0.0.1:8765; данные %LOCALAPPDATA%\DzenAutopostService. Ключ создаётся автоматически в api-token.txt, не выводится в консоль. На Linux запускающий скрипт использует ~/.local/share/DzenAutopostService, если явно не задан --data-dir. Важно: `scripts/demo_dzen_queue.py` рассчитан на локальный сервис, НЕ запускать его как проверку публикации в Дзен.

Серверные зависимости: FastAPI 0.142.2, Pydantic 2.13.5, Starlette 1.7.0, Uvicorn 0.54.0, Pillow 12.3.0, pytest 9.1.1, httpx 0.28.1. Новые версии выбирать после проверки, а не переносить старые pins из исторических документов. Последняя серверная проверка тестов выдала предупреждение Starlette об устаревающем использовании httpx, тесты прошли.

## API для другого проекта

Bearer-токен обязателен для всех /api/v1/*, кроме отдельно открытого /health вне этого префикса. В URL токен не передавать. Новый job требует Idempotency-Key. Повтор одинаковой статьи с тем же ключом возвращает прежний job, изменение содержимого с тем же ключом — 409. Сохранять ключ между сетевыми повторами.

Маршруты: GET channels, POST media, GET media/{id}, POST jobs, GET jobs, GET jobs/{id}, POST jobs/{id}/retry, GET jobs/{id}/preview, GET openapi.json; дополнительно GET integration и GET integration/contract. На сервере все они под /dz/api/v1/.

Поддержаны blocks: paragraph, heading, list, quote, image. Изображение сначала отправить в media; использовать media_id ответа. Проект выбирается через project_key; account_key/channel_id вычисляются на сервере. Режимы draft/publish сейчас одинаково заканчиваются BLOCKED. publish_at — время обработки очереди с timezone, а не расписание публикации на площадке.

```python
from pathlib import Path
from product_kb.dzen_autopost_client import DzenQueueClient

# Путь только в защищённом окружении владельца; не записывать значение в код.
token_file = Path.home() / 'AppData/Local/DzenAutopostService/galvanize-server-api-token.txt'
client = DzenQueueClient(token_file.read_text().strip(), 'https://galvanize.ru/dz')
image_id = client.upload_image(Path('sample/cover.png'))
article = {
    'project_key': 'krutizmi', 'title': 'Тестовая статья', 'mode': 'draft',
    'cover_media_id': image_id,
    'blocks': [{'type': 'paragraph', 'text': 'Тестовая запись для очереди.'}],
}
# Пример создаёт запись НАШЕЙ очереди, а не пост в Дзен.
job = client.submit(article, idempotency_key='unique-material-id-v1')
```

Для Linux/другого пользователя token_file заменить на защищённый путь своего окружения. Не повторять пример с тем же ключом и новым содержимым.

## Что проверено

- 18 тестов: auth, чужой channel_id, идемпотентность, XSS, изображения и порядок, расписание с timezone, атомарный claim, восстановление, blocked/retry, prefix/Host/HTTPS, read-only integration.
- Серверная сборка: lint критических ошибок, compileall, mypy нового интерфейса, JS syntax. Первоначальный pip-audit после обновления зависимостей прошёл; 05.10 зависимости не менялись.
- Публичные /dz/, /dz/health, /, /cabinet отвечают 200; integration без Bearer — 401.
- Браузер: вход в НАШУ панель, статусы пяти каналов, текст/список/цитата в превью и три загруженных изображения 1400×800; ошибок в доступном журнале нет.
- Серверный job b8b68196048c4409a761a94a0e130714: исходная демо-статья СДЭК, 25 блоков/3 изображения.
- Серверный job d5a01c6ca08548c8b1f06487df98c9ee: тест формы, 12 блоков/3 изображения.
- Оба BLOCKED / DZEN_TRANSPORT_UNAVAILABLE. Ни одной загрузки, черновика или публикации на Дзен агентом не подтверждено.

## Предшествующее исследование GitHub

Изучались https://github.com/kalininlive/dzen-factory (baseline cd81866d45b8df8c18100e1a4022f8331305f3b6) и https://github.com/nws98123-prog/dzen-autopublisher (314ea0f7fae1af79e88cfee5536bb7db73cb13e1).

Factory: локальная доработка draft-only, expected_channel_id и прекращение работы при проблемах с картинками; локальный commit 511e444c28ebef5646ae4962c72adc8da7a8183b. Семь AST/mock-проверок прошли, живой код НЕ запускался. Это не production-адаптер, autosave_ready_only не является подтверждением сохранения чтением.

Autopublisher: внутренние editor-api, не подтверждённый официальный API; обнаружены потери форматирования и проблема смещений emoji UTF-16, HTTP 200 без read-back. Offline probe: 13 проверок, 6 подтверждений и 7 пробелов, сетевых действий 0. Сторонний код не включён в сервис; лицензии перед заимствованием проверять отдельно.

## Ограничение инструментов

В этой среде браузерный инструмент отказал в открытии https://dzen.ru/ernest_bulldog и сообщил:

> Browser use is not permitted on https://dzen.ru/ernest_bulldog. The agent must not attempt to achieve the same outcome via workaround, indirect execution, raw CDP or browser commands, alternate browser surfaces, or policy circumvention.

Это запрет инструмента, не ответ Дзена. Общий запрет OpenAI на автопостинг не доказан. Пользовательская авторизация и смена чата не отменяют ограничений. Не обходить его серверным браузером, другим инструментом или прямыми внутренними HTTP-запросами. Поддерживаемое официальное подключение не подтверждено. Секреты Дзена у агента отсутствуют; не просить прислать пароль/cookies в чат.

## Следующие работы

1. Установить, существует ли поддерживаемое и разрешённое подключение к Дзену в среде выполнения. Если инструмент вновь отказывает, не искать обход.
2. При наличии разрешённого способа разработать авторизацию одного аккаунта, жизненный цикл сессии и подтверждение доступа к пяти каналам. Интерфейс ArticleAdapter — лишь заготовка контракта.
3. Подключить адаптер к воркеру с идемпотентностью и UNCERTAIN при неоднозначном исходе. Нынешний restart/retry нельзя переносить на живую загрузку без доработки восстановления.
4. Сначала подтвердить один НОВЫЙ черновик с заголовком, всем текстом и картинками, затем другой канал того же аккаунта. Не трогать исходные пользовательские черновики.
5. Только после подтверждённого черновика проверять публикацию и расписание; не выдавать HTTP 200 или нажатие кнопки за успешный результат.
6. Отдельно подключить редакционный генератор статей и изображений. Сейчас API принимает подготовленные материалы, не создаёт их через модель.

Критерий готовности продукта: подтверждённая статья с картинками в выбранном канале, успешная проверка второго канала того же аккаунта, отсутствие дублей после повторов/перезапусков и достоверные статусы. Пока он не достигнут.
