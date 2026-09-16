# Proxy PC — рабочие материалы

Папка в репозитории [Slavam63/SlavamMatrix](https://github.com/Slavam63/SlavamMatrix).

## Содержимое

| Файл | Назначение |
|------|------------|
| `BYULLETEN-dorabotki-ProxyPC.txt` | Бюллетень доработки 16.09.2026 |
| `INSTALL-ProxyPC-INSTRUKCIYA.txt` | Инструкция установки на стационарный ПК |
| `app/ProxyPC.ps1` | Актуальный скрипт после доработки (ноутбук SLAVAM63) |
| `app/ProxyPC.vbs` | Запуск toggle через wscript (если используется) |

## Полный комплект установки (бинарь gost, иконки, Install-*.ps1)

Лежит на Яндекс.Диске (не в git из‑за размера `gost.exe` и локальных путей):

`C:\Users\slava\Yandex.Disk\МВИ\Виртуальные машины\Прокси-сервер\FrankfurtProxy`

## Важно

- VPS: Aeza Frankfurt `185.125.103.179`
- Cursor + Proxy PC: только `http://127.0.0.1:8080` пока Proxy PC ON; при OFF ключи `http.proxy*` удаляются
- Не писать в Cursor `socks5://127.0.0.1:1080`
- Один VPN-клиент за раз (Bebra / Happ / Amnezia / Proxy PC)
- SSH-ключи и пароли Outline в этот репозиторий не класть

## Проверка после включения Proxy PC

1. Системный прокси Windows: `127.0.0.1:8080`
2. `curl -x http://127.0.0.1:8080 https://api.ipify.org` → IP VPS
3. Полный перезапуск Cursor → чат «привет»
