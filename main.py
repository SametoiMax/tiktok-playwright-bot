import asyncio
import random
import csv
import os
from datetime import datetime
from playwright.async_api import async_playwright
from collections import deque

CHROME_PATH = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
CHROME_USER_DATA = r"User Data"
PROFILE = "Default"
QUERY = "catsdogs"
MAX_VIEW_TABS = 10
SKIP_PERCENT = 12  # шанс скипа

visited_links = set()
video_queue = deque()

is_searching = True
search_page = None


def save_video_info(profile, query, watched, url, likes, comments, filename="tiktok_results.csv"):
    file_exists = os.path.isfile(filename)
    with open(filename, mode="a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file, delimiter=";")
        if not file_exists:
            writer.writerow(
                ["profile", "search string", "datetime", "view or skip", "url", "likes count", "comments count"])
        writer.writerow([
            profile,
            query,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "view" if watched else "skip",
            url,
            likes,
            comments
        ])


def parse_time(text):
    parts = text.strip().split(":")
    parts = list(map(int, parts))
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return 0


async def update_tab_title_with_time(page):
    old_percent = 0
    try:
        while True:
            time_elem = page.locator("xpath=//div[contains(@class, 'DivSeekBarTimeContainer')]").first
            time_text = await time_elem.inner_text()  # пример: "00:12 / 00:41"
            percent = None  # инициализируем, чтобы избежать ошибки, если "/" нет в строке

            if "/" in time_text:
                current_str, total_str = time_text.split("/")
                current = parse_time(current_str)
                total = parse_time(total_str)

                if total > 0:
                    percent = int((current / total) * 100)
                    title = f"({percent}%) ⏱ {time_text.strip()}"
                else:
                    title = f"(??%) ⏱ {time_text.strip()} "
                    await page.click("video")
            else:
                title = f"⏱ {time_text.strip()}"

            # Выход из цикла, если видео просмотрено
            if percent is not None and (percent >= 100 or percent < old_percent):
                break
            elif percent is not None and (percent == old_percent):
                await page.click("video")
            elif percent is not None:
                old_percent = percent

            await page.evaluate(f'document.title = `{title}`')
            await asyncio.sleep(2)

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"⚠️ Ошибка обновления заголовка: {e}")


async def watch_video(context, url):
    page = None
    try:
        page = await context.new_page()
        await page.evaluate("window.moveTo(0,0); window.resizeTo(screen.width, screen.height);")
        await page.goto(url, timeout=60000)

        like_elem = page.locator("xpath=//strong[@data-e2e='like-count']").first
        likes = await like_elem.inner_text()

        comment_elem = page.locator("xpath=//strong[@data-e2e='comment-count']").first
        comments = await comment_elem.inner_text()

        # 🎲 Рандом на пропуск
        SKIP = random.randint(1, 100) <= SKIP_PERCENT
        if SKIP:
            print(f"⏭ Видео пропущено {url} | ❤️ {likes} | 💬 {comments}")
        else:
            print(f"▶️ Смотрим: {url}  | ❤️ {likes} | 💬 {comments}")
            # Создаём задачу, которая завершится при 100% просмотре
            time_task = asyncio.create_task(update_tab_title_with_time(page))
            # Ждём завершения задачи (просмотр завершён)
            await time_task

        # Сохраняем результат
        save_video_info(PROFILE, QUERY, watched=not SKIP, url=url, likes=likes, comments=comments)

    except Exception as e:
        print(f"⚠️ Ошибка просмотра {url}: {e}")
    finally:
        if page:
            await page.close()


async def search_videos(context):
    global is_searching
    await asyncio.sleep(3)
    while True:

        added = 0

        # Получение всех ссылок на видео
        links = await search_page.locator(
            "xpath=//a[contains(@class, 'AVideoContainer') and contains(@href, '/video/')]"
        ).all()

        for link in links:
            href = await link.get_attribute("href")
            if href and not (href in video_queue or href in visited_links):
                video_queue.append(href)
                added += 1

        await update_search_title()
        print(
            f"🔁 Всего элементов: {len(links)} | Добавлено: {added} | Всего добавлено: {len(video_queue)}")

        no_more_results = await search_page.locator("xpath=//div[contains(@class,'DivNoMoreResultsContainer')]").count()
        if added == 0 and no_more_results > 0:
            print("🚫 Больше результатов нет. Завершаем поиск.")
            is_searching = False
            break

        await scroll_page(scrolls=10, delay=1)


async def scroll_page(scrolls=5, delay=2):
    await search_page.bring_to_front()
    for i in range(scrolls):
        await search_page.mouse.wheel(0, 3000)  # имитация прокрутки вниз
        await asyncio.sleep(delay)  # задержка на прогрузку контента


async def update_search_title():
    watched_total = len(visited_links)
    found_total = watched_total + len(video_queue)
    percent = int((watched_total / found_total) * 100) if found_total else 0
    try:
        await search_page.evaluate(
            f'document.title = "🔎 {QUERY} ({percent}%) {watched_total}/{found_total}"'
        )
    except Exception as e:
        print(f"⚠️ Ошибка обновления заголовка поиска: {e}")


async def consume_queue(context):
    global visited_links, video_queue
    tasks = set()

    while True:
        # Удаление завершённых задач
        tasks = {t for t in tasks if not t.done()}

        # Запуск новых задач, если есть место
        while len(tasks) < MAX_VIEW_TABS and video_queue:
            url = video_queue.popleft()
            visited_links.add(url)
            task = asyncio.create_task(watch_video(context, url))
            tasks.add(task)
            await update_search_title()
            await asyncio.sleep(2)

        await update_search_title()

        # Условие завершения
        if not is_searching and not video_queue and not tasks:
            break
        # если is_searching завершён, очередь пуста, но есть задачи
        if not is_searching and not video_queue and tasks:
            print("⌛ Ожидание завершения активных задач...")
            await asyncio.gather(*tasks)
            break

        await asyncio.sleep(1)


async def main():
    global search_page
    print(f"⚙️ Профиль: {PROFILE} | Поиск: {QUERY}")

    async with async_playwright() as p:
        try:
            context = await p.chromium.launch_persistent_context(
                f"{CHROME_USER_DATA}\\{PROFILE}",
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-session-crashed-bubble",
                ],
                executable_path=CHROME_PATH
            )

            await asyncio.sleep(1)
            for p in context.pages[1:]:
                await p.close()

            search_page = context.pages[0] if context.pages else await context.new_page()
            search_url = f"https://www.tiktok.com/search?q={QUERY}"
            await search_page.goto(search_url)

            print(f"✅ TikTok открыт по запросу: {QUERY}")

            await asyncio.gather(
                search_videos(context)
                , consume_queue(context)
            )

        except Exception as e:
            print(f"⚠️ Ошибка выполнения: {e}")

        finally:
            try:
                await context.close()
            except Exception as e:
                print(f"⚠️ Ошибка при закрытии контекста: {e}")

        print(f"✅ TikTok просмотрен по запросу: {QUERY}")


if __name__ == "__main__":
    asyncio.run(main())
