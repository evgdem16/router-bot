import os
import sys
import logging
import time
from logging.handlers import RotatingFileHandler
from playwright.sync_api import sync_playwright

# Настройка логирования в два источника: в консоль и в файл bot.log
log_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("WebAuth")
logger.setLevel(logging.INFO)

# Убираем дублирование логов, если они уже были настроены
if not logger.handlers:
    # НАСТРОЙКА РОТАЦИИ:
    # maxBytes=5*1024*1024 (5 Мегабайт)
    # backupCount=3 (хранить максимум 3 старых файла)
    file_handler = RotatingFileHandler(
        "/log/bot.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )
    file_handler.setFormatter(log_formatter)
    logger.addHandler(file_handler)

    # Handler для stdout (консоль Docker)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(log_formatter)
    logger.addHandler(stream_handler)

def get_content_frame(page):
    """
    Ищет фрейм, внутри которого находится рабочая область.
    Проверяет главный документ и все вложенные фреймы на наличие кнопки #Newbutton.
    """
    # Сначала проверяем саму главную страницу
    if page.locator("#Newbutton").count() > 0:
        return page

    # Если на главной нет, перебираем все фреймы на странице
    for frame in page.frames:
        try:
            if frame.locator("#Newbutton").count() > 0:
                logger.info(f"Рабочая область найдена во фрейме: name='{frame.name}', url='{frame.url}'")
                return frame
        except Exception:
            continue

    # Если кнопка 'New' еще не отрендерилась, попробуем вернуть фрейм по косвенным признакам (обычно в имени есть 'main' или 'content')
    for frame in page.frames:
        if "main" in frame.name.lower() or "content" in frame.name.lower() or "frame" in frame.name.lower():
            return frame

    return page

def check_and_add_dmz(target_frame):
    # Шаг 4: Проверяем, есть ли уже нужная запись (ищем внутри фрейма)
    logger.info("Проверка наличия записи '1_TR069_INTERNET_R_VID_10' во фрейме...")

    is_existing = False
    try:
        # Проверяем, существует ли элемент с нужным ID на странице в принципе
        # (используем локатор с таймаутом в 2 секунды, чтобы не ждать долго, если записи нет)
        target_cell = target_frame.locator("[id^='dmzInst_0_1']")

        count = target_cell.count()
        logger.info(f"Найдено потенциальных ячеек с записями DMZ: {count}")

        for i in range(count):
            cell_text = target_cell.nth(i).text_content()
            if cell_text:
                clean_text = cell_text.strip()
                logger.info(f"Текст в ячейке #{i}: '{clean_text}'")
                if "1_TR069_INTERNET_R_VID_10" in clean_text:
                    is_existing = True
                    break
    except Exception as e:
        logger.debug(f"Элементы таблицы еще не созданы или отсутствуют: {e}")

    if is_existing:
        logger.info("🎉 Запись '1_TR069_INTERNET_R_VID_10' уже существует в таблице. Завершаем работу.")
        return True

    logger.warning("❌ Запись не найдена. Начинаем процесс добавления...")

    # Шаг 5: Клик по кнопке 'New'
    logger.info("Нажатие на кнопку 'New' (#Newbutton)...")
    target_frame.wait_for_selector("#Newbutton", timeout=5000)
    target_frame.click("#Newbutton")

    # Шаг 6: Активация чекбокса DMZEnable
    logger.info("Активация чекбокса 'DMZEnable'...")
    target_frame.wait_for_selector("#DMZEnable", timeout=5000)
    if not target_frame.is_checked("#DMZEnable"):
        target_frame.check("#DMZEnable")

    # Шаг 7: Выбор в раскрывающемся списке DMZHostName
    logger.info("Выбор хоста в списке 'DMZHostName'...")
    target_frame.wait_for_selector("#DMZHostName", timeout=5000)
    target_frame.select_option("#DMZHostName", index=1)
    logger.info("Хост из выпадающего списка успешно выбран.")

    # Шаг 8: Клик на кнопку сохранения Apply
    logger.info("Нажатие на кнопку сохранения (#btnApply1)...")
    target_frame.wait_for_selector("#btnApply1", timeout=5000)
    target_frame.click("#btnApply1")

    logger.info("Ожидание сохранения настроек роутером...")
    time.sleep(4)

    # Шаг 9: Проверяем повторно, появилась ли запись
    if target_frame.locator("td:has-text('1_TR069_INTERNET_R_VID_10')").count() > 0:
        logger.info("✅ Изменения успешно сохранены! Запись появилась в таблице.")
        return True
    else:
        logger.error("🚨 Ошибка: Кнопка Apply была нажата, но запись в таблице так и не появилась.")
        return False

def run_iteration():
    target_url = os.getenv("ROUTER_URL")
    username = os.getenv("ROUTER_USERNAME")
    password = os.getenv("ROUTER_PASSWORD")

    with sync_playwright() as p:
        logger.info("Запуск Chromium...")
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context()
        page = context.new_page()

        logger.info(f"Переход на {target_url}...")
        try:
            page.goto(target_url, wait_until="networkidle")
        except Exception as e:
            logger.error(f"Не удалось загрузить страницу: {e}")
            browser.close()
            return

        # Авторизация
        try:
            page.wait_for_selector("#txt_Username", timeout=5000)
            page.fill("#txt_Username", username)
            page.fill("#txt_Password", password)

            button_selector = "#loginbutton >> visible=true"
            page.wait_for_selector(button_selector, timeout=5000)
            page.click(button_selector, force=True)
            logger.info("Форма авторизации отправлена.")
            time.sleep(3)
        except Exception as e:
            logger.error(f"Ошибка при авторизации: {e}")
            browser.close()
            return

        # Шаг 1: Клик по кнопке Advanced
        logger.info("Переход в меню 'Advanced' (#name_addconfig)...")
        try:
            page.wait_for_selector("#name_addconfig", timeout=10000)
            page.click("#name_addconfig")
            time.sleep(3)
        except Exception as e:
            logger.error(f"Не удалось войти в Advanced: {e}")
            page.screenshot(path="advanced_error.png")
            browser.close()
            return

        # Шаг 2: Клик по кнопке Forward Rules
        logger.info("Переход в подменю 'Forward Rules' (#name_forwardrules)...")
        try:
            page.wait_for_selector("#name_forwardrules", timeout=5000)
            page.click("#name_forwardrules")
            time.sleep(1)
        except Exception as e:
            logger.error(f"Не удалось найти Forward Rules: {e}")
            browser.close()
            return

        # Шаг 3: Клик по кнопке DMZ Function
        logger.info("Переход в раздел 'DMZ Function' (#dmz)...")
        try:
            page.wait_for_selector("#dmz", timeout=5000)
            page.click("#dmz")
            time.sleep(3)  # Даем фрейму контента полностью обновиться
        except Exception as e:
            logger.error(f"Не удалось найти DMZ Function: {e}")
            browser.close()
            return

        # Динамически определяем, в каком фрейме открылась страница DMZ
        target_frame = get_content_frame(page)

        # Выполнение шагов 4-9 внутри целевого фрейма
        time.sleep(3)
        success = check_and_add_dmz(target_frame)

        if not success:
            logger.warning("🔄 Попытка повторного поиска фрейма и добавления записи...")
            target_frame = get_content_frame(page)
            success = check_and_add_dmz(target_frame)

        if success:
            logger.info("🎉 Итерация успешно завершена. Цель достигнута.")
        else:
            logger.error("🛑 Не удалось добавить запись.")
            page.screenshot(path="final_failure.png")

        browser.close()

if __name__ == "__main__":
    logger.info("🚀 Бот успешно запущен и работает в циклическом режиме...")
    INTERVAL = 5 * 60  # 5 минут в секундах

    while True:
        logger.info("⏰ Начало запланированной проверки роутера...")
        run_iteration()
        logger.info(f"💤 Проверка завершена. Засыпаю на 5 минут...")
        time.sleep(INTERVAL)
