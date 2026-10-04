# dzen-autopost

Серверная панель и API для общей очереди статей пяти каналов одного аккаунта Дзена.

**Статус: очередь работает; вход в Дзен, загрузчик и публикация не реализованы.** Записи заканчиваются `BLOCKED / DZEN_TRANSPORT_UNAVAILABLE`. Этот репозиторий не является готовым автопубликатором.

Размещённая панель: https://galvanize.ru/dz/ (вход по личному ключу нашего сервиса).

## Продолжение в другом чате

Начать с [полной актуальной инструкции](docs/DZEN_NEXT_CHAT.md), затем [контракта адаптера](docs/dzen-adapter-contract.md). Старые документы от 04.10 содержат историю; при расхождении актуален DZEN_NEXT_CHAT.md.

## Локальный запуск

Python 3.12 или 3.13, отдельное окружение. Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dzen.txt
.\.venv\Scripts\python.exe -m pytest tests/test_dzen_autopost.py -q
.\.venv\Scripts\python.exe scripts/run_dzen_autopost.py
```

Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dzen.txt
.venv/bin/python -m pytest tests/test_dzen_autopost.py -q
.venv/bin/python scripts/run_dzen_autopost.py
```

Адрес http://127.0.0.1:8765. Ключ создаётся в runtime-каталоге автоматически, не выводится в консоль. На Windows это `%LOCALAPPDATA%\DzenAutopostService\api-token.txt`. Серверный процесс использует отдельный runtime и порт 8766. Локальный запуск не авторизует Дзен.

## Возможности

- Пять каналов в server-derived config, общий account_key.
- SQLite-очередь, идемпотентность, изображения и структурированные блоки.
- Bearer API, HTTPS-клиент с префиксом /dz.
- Панель со статусом подключения и проверенным sandbox-предпросмотром.
- Read-only контракт будущего загрузчика без реализации или установки.
- 18 тестов; подтверждённая обработка текста и трёх изображений в собственной панели.

В репозитории нет API-токенов, cookies, SSH-ключей, пользовательской базы/очереди, профилей браузера и стороннего кода загрузчиков. Документированные ограничения инструментов нужно учитывать при продолжении; смена чата не отменяет их.
