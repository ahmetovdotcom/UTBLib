# Обновление UTBLib + library на существующем сервере

Подготовлено 04.11.2026 для `/home/admtutor/projects/UTBLib` (ветка **main**) и
`/home/admtutor/projects/library` (ветка **audit**), сервер `10.0.1.17`.
Проверены Compose labels: UTBLib использует server + readers + circulation,
library — **docker-compose.yml**, а не docker-compose.prod.yml.

## Обновить Git, сохранив настройки прокси

Выполнить каждый блок целиком. При ошибке остановиться, не переходить к следующему.
Stash применяется без удаления; `git stash pop` без проверки не использовать.

```bash
cd /home/admtutor/projects/UTBLib
bash -e <<'SH'
test "$(git branch --show-current)" = main
saved=""
if ! git diff --quiet HEAD -- compose.server.yaml; then
  git stash push -m 'UTBLib proxy before student frontend' -- compose.server.yaml
  saved=$(git rev-parse refs/stash)
fi
git pull --ff-only origin main </dev/null
if [ -n "$saved" ]; then git stash apply "$saved"; fi
SH
```

```bash
cd /home/admtutor/projects/library
bash -e <<'SH'
test "$(git branch --show-current)" = audit
saved=""
if ! git diff --quiet HEAD -- docker-compose.yml; then
  git stash push -m 'library proxy before student frontend' -- docker-compose.yml
  saved=$(git rev-parse refs/stash)
fi
git pull --ff-only origin audit </dev/null
if [ -n "$saved" ]; then git stash apply "$saved"; fi
SH
```

## Применить релиз

```bash
cd /home/admtutor/projects/UTBLib
bash deploy/activate-student-frontend.sh /home/admtutor/projects/library
```

Обновление может занять несколько минут; сайты кратковременно перезапустятся.
Не запускать скрипт одновременно из двух терминалов. Не нужен повторный импорт
MARCSQL, очистка БД или перенос локальной БД.

Скрипт:

1. Проверяет ветки, конфигурацию AD/HTTPS и связь `library → utblib-web`.
2. Создаёт приватную папку `../frontend-release-<дата>-<суффикс>`, сохраняет оба
   PostgreSQL dump, проверяет оглавления, сохраняет env/Compose и прежние assets.
   Проверяется читаемость архивов, не полная пробная реставрация.
3. Экспортирует только опубликованные публичные новости/события и активные ресурсы
   старого library. На дату подготовки: **4 новости, 7 ресурсов, 4 изображения**.
   Черновики, договоры, персональные данные не экспортируются. Исходная БД остаётся.
   Если в старом репозитории появились опубликованные работы, экспорт остановится:
   права на их файлы нужно перенести отдельно.
4. Сохраняет общий случайный `STUDENT_BRIDGE_KEY` только в двух приватных env-файлах;
   согласованный существующий ключ повторно использует. Включает frontend, AD/LDAPS,
   production, secure cookie; сохраняет пароли, APP_KEY, БД и настройки AD.
5. Собирает frontend с Node 22 в отдельной папке без env/загрузок (host Node 18
   слишком старый), затем собирает Docker images до перезапуска.
6. Проверяет импорт, обновляет UTBLib с прежними overlays, переносит публикации
   одной транзакцией и обновляет library. Повторный импорт не создаёт дубли и
   не перезаписывает правки сотрудников. Конфликт с самостоятельной публикацией
   того же slug останавливает импорт. Действие `import_library_public` фиксируется
   в журнале с ID первого активного администратора UTBLib как исполнителя CLI.
7. Проверяет health, публичный каталог и подписанный API кабинета случайным
   несуществующим GUID, без чтения чужих данных.

Сеть `library_default` и алиас `utblib-web` уже заданы серверными правками Compose.
Скрипт не создаёт новую БД, не меняет volumes, не удаляет каталог/выдачи и
не открывает дополнительные порты. Локальный тестовый вход не входит в Git.

## Проверка после обновления

- `https://libstaff.kaztbu.edu.kz`: каталог, выдачи, читатели и их синхронизация.
- `https://elibrary.kaztbu.edu.kz`: каталог/наличие из UTBLib, новости и ресурсы.
- `/login`: настоящий университетский логин/пароль AD, затем `/dashboard` и `/dashboard/card`.
  Сверить билет и выдачи с карточкой того же человека в UTBLib. Проверка service bind
  AD на сервере прошла; вход с паролем студента выполняет владелец аккаунта.
- Публикации теперь редактируются в исходном разделе **«Сайт»** UTBLib. Старые
  административные страницы library в режиме frontend недоступны.

Если AD-вход проходит, но карточка не найдена, проверить связь `reader_identities`
с `source=active_directory`, `entity_type=ad_user`, `external_id=objectGUID`.
Совпадение ФИО/почты не заменяет связь. Вход не создаёт новый билет.

## Если шаг завершился ошибкой

Скрипт выводит этап и путь резервных копий. Не делать `down -v`, `reset --hard`,
очистку или импорт MARCSQL. До этапов update приложения не перезапускаются;
env уже может быть подготовлен. После исправления можно повторить скрипт.
При конфликте Git разобрать конфликт прокси до продолжения.

До релиза серверные коммиты: UTBLib `2f5a74d`, library `af3e430`.
Для отката кода нужны эти коммиты вместе с сохранёнными env, Compose и assets,
затем сборка тех же сервисов. Восстанавливать старые дампы поверх новых выдач нельзя:
это отдельная операция с потерей последующих изменений. Добавленные публикации
не мешают старому коду и сами по себе восстановления БД не требуют.
