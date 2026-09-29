import asyncio
import signal
import socket
import sys
from pathlib import Path

import httpx2 as httpx
import pytest
from playwright.async_api import async_playwright, expect
from test_admin_server import PASSWORD, command, environment


@pytest.fixture
async def admin_url(database_url, tmp_path):
    secret = tmp_path / "admin.hash"
    assert (
        await command(
            "init-password",
            "--output",
            str(secret),
            "--password-stdin",
            stdin=(PASSWORD + "\n").encode(),
        )
    )[0] == 0
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "xiaolv.admin_server",
        "serve",
        env=environment(
            XIAOLV_ADMIN_DATABASE_URL=database_url,
            XIAOLV_ADMIN_PASSWORD_HASH_FILE=str(secret),
            XIAOLV_ADMIN_PORT=str(port),
        ),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with httpx.AsyncClient(trust_env=False) as http:
            async with asyncio.timeout(10):
                while True:
                    assert process.returncode is None
                    try:
                        await http.get(base + "/admin/api/session")
                        break
                    except httpx.ConnectError:
                        await asyncio.sleep(0.05)
        yield base
    finally:
        if process.returncode is None:
            process.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(process.communicate(), 10)
        except TimeoutError:
            process.kill()
            await process.communicate()


@pytest.mark.parametrize("width,height", [(1280, 800), (390, 844)])
async def test_browser_login_refresh_and_logout(admin_url, width, height):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": width, "height": height})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(admin_url + "/admin/")
            await expect(page.get_by_role("heading", name="登录管理台")).to_be_visible()
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            folder = Path("artifacts")
            folder.mkdir(exist_ok=True)
            await page.screenshot(path=str(folder / f"admin-login-{width}.png"), full_page=True)
            password = page.get_by_label("管理员密码", exact=True)
            await password.fill("wrong-password")
            await page.get_by_role("button", name="登录", exact=True).click()
            await expect(page.get_by_role("alert")).to_contain_text("密码不正确")
            await password.fill(PASSWORD)
            await page.get_by_role("button", name="登录", exact=True).click()
            await expect(page.get_by_role("heading", name="已登录管理台")).to_be_visible()
            assert await page.evaluate("localStorage.length + sessionStorage.length") == 0
            assert "xiaolv_admin" not in await page.evaluate("document.cookie")
            await page.reload()
            await expect(page.get_by_role("heading", name="已登录管理台")).to_be_visible()
            await page.get_by_role("button", name="退出登录").click()
            await expect(page.get_by_role("heading", name="登录管理台")).to_be_visible()
            await page.reload()
            await expect(page.get_by_role("heading", name="登录管理台")).to_be_visible()
            assert errors == []
        finally:
            await browser.close()


async def test_initial_connection_failure_can_be_retried(admin_url):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await page.route("**/admin/api/session", lambda route: route.abort())
            await page.goto(admin_url + "/admin/")
            await expect(page.get_by_role("alert")).to_contain_text("连接失败")
            retry = page.get_by_role("button", name="重新连接")
            await expect(retry).to_be_visible()
            await page.unroute("**/admin/api/session")
            await retry.click()
            await expect(page.get_by_label("管理员密码", exact=True)).to_be_visible()
        finally:
            await browser.close()


async def test_login_submission_is_disabled_until_response(admin_url):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        hold = asyncio.Event()
        try:
            page = await browser.new_page()
            await page.goto(admin_url + "/admin/")
            password = page.get_by_label("管理员密码", exact=True)
            await password.fill(PASSWORD)
            await password.press("Tab")
            await expect(page.get_by_role("button", name="登录", exact=True)).to_be_focused()

            async def delayed(route):
                await hold.wait()
                await route.continue_()

            await page.route("**/admin/api/login", delayed)
            await page.keyboard.press("Enter")
            await expect(page.get_by_role("button", name="正在登录…")).to_be_disabled()
            await expect(password).to_be_disabled()
            hold.set()
            await expect(page.get_by_role("heading", name="已登录管理台")).to_be_visible()
            await page.route("**/admin/api/logout", lambda route: route.abort())
            await page.get_by_role("button", name="退出登录").click()
            await expect(page.get_by_role("alert")).to_contain_text("无法确认退出结果")
            await expect(page.get_by_role("heading", name="已登录管理台")).to_be_visible()
            await page.unroute("**/admin/api/logout")
            await page.get_by_role("button", name="退出登录").click()
            await expect(page.get_by_role("heading", name="登录管理台")).to_be_visible()
        finally:
            hold.set()
            await browser.close()


async def test_real_login_limit_has_readable_feedback(admin_url):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await page.goto(admin_url + "/admin/")
            for _ in range(5):
                await page.get_by_label("管理员密码", exact=True).fill("wrong-password")
                await page.get_by_role("button", name="登录", exact=True).click()
                await expect(page.get_by_role("alert")).to_contain_text("密码不正确")
            await page.get_by_label("管理员密码", exact=True).fill(PASSWORD)
            await page.get_by_role("button", name="登录", exact=True).click()
            await expect(page.get_by_role("alert")).to_contain_text("尝试次数过多")
        finally:
            await browser.close()


async def test_missing_build_is_explicit_and_does_not_hide_api(database_url, tmp_path):
    from pwdlib import PasswordHash
    from sqlalchemy.ext.asyncio import create_async_engine

    from xiaolv.admin import AdminConfig, create_admin_app

    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        app = create_admin_app(
            engine,
            AdminConfig(PasswordHash.recommended().hash(PASSWORD), "http://127.0.0.1"),
            frontend_dir=tmp_path,
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as http:
            response = await http.get("/admin/")
            assert response.status_code == 503
            assert "未构建" in response.text
            assert (await http.get("/admin/api/session")).status_code == 401
    finally:
        await engine.dispose()


@pytest.mark.parametrize("width,height", [(1280, 800), (390, 844)])
async def test_browser_edits_draft_then_publishes(admin_url, width, height):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": width, "height": height})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            await page.goto(admin_url + "/admin/")
            await page.get_by_label("管理员密码", exact=True).fill(PASSWORD)
            await page.get_by_role("button", name="登录", exact=True).click()
            await expect(page.get_by_role("heading", name="机器人资料")).to_be_visible()
            await expect(page.get_by_text("尚未发布人设", exact=True)).to_be_visible()
            await page.get_by_label("名称", exact=True).fill("青禾")
            await page.get_by_label("别名", exact=True).fill("小青\n青禾同学")
            await page.get_by_label("人设", exact=True).fill("合成测试资料")
            await page.get_by_label("参与风格", exact=True).fill("有合适话题再接话")
            await page.get_by_label("回复风格", exact=True).fill("简短自然")
            await page.get_by_role("button", name="保存草稿", exact=True).click()
            await expect(page.get_by_text("草稿已保存", exact=True)).to_be_visible()
            await expect(page.get_by_text("尚未发布人设", exact=True)).to_be_visible()
            await page.reload()
            await expect(page.get_by_label("名称", exact=True)).to_have_value("青禾")
            await page.get_by_role("button", name="发布草稿", exact=True).click()
            await expect(page.get_by_text("已发布版本 1", exact=True)).to_be_visible()
            await page.get_by_label("名称", exact=True).fill("晚晴")
            await expect(page.get_by_role("button", name="发布草稿", exact=True)).to_be_disabled()
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await page.screenshot(path=f"artifacts/profile-editor-{width}.png", full_page=True)
            assert errors == []
        finally:
            await browser.close()


async def login_browser(page, admin_url):
    await page.goto(admin_url + "/admin/")
    await page.get_by_label("管理员密码", exact=True).fill(PASSWORD)
    await page.get_by_role("button", name="登录", exact=True).click()
    await expect(page.get_by_role("heading", name="机器人资料")).to_be_visible()


async def test_publish_lost_response_retries_same_operation(admin_url):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await login_browser(page, admin_url)
            await page.get_by_label("名称", exact=True).fill("青禾")
            await page.get_by_role("button", name="保存草稿", exact=True).click()
            await expect(page.get_by_text("草稿已保存", exact=True)).to_be_visible()
            keys = []

            async def lose_once(route):
                keys.append(route.request.headers["idempotency-key"])
                if len(keys) == 1:
                    response = await route.fetch()
                    assert response.status == 200
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/admin/api/profile/publish", lose_once)
            await page.get_by_role("button", name="发布草稿", exact=True).click()
            await expect(page.get_by_role("alert")).to_contain_text("结果尚未确认")
            await expect(page.get_by_label("名称", exact=True)).to_be_disabled()
            await page.get_by_role("button", name="重试原操作", exact=True).click()
            await expect(page.get_by_text("已发布版本 1", exact=True)).to_be_visible()
            assert len(keys) == 2 and keys[0] == keys[1]
            await page.reload()
            await expect(page.get_by_text("已发布版本 1", exact=True)).to_be_visible()
        finally:
            await browser.close()


async def test_concurrent_browser_edit_preserves_local_draft_until_explicit_reload(admin_url):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            context = await browser.new_context()
            first = await context.new_page()
            await login_browser(first, admin_url)
            await expect(first.get_by_label("名称", exact=True)).to_be_visible()
            second = await context.new_page()
            await second.goto(admin_url + "/admin/")
            await second.get_by_label("名称", exact=True).fill("本地未保存")
            await first.get_by_label("名称", exact=True).fill("最新草稿")
            await first.get_by_role("button", name="保存草稿", exact=True).click()
            await expect(first.get_by_text("草稿已保存", exact=True)).to_be_visible()
            await second.get_by_role("button", name="保存草稿", exact=True).click()
            await expect(second.get_by_role("alert")).to_contain_text("已被其他页面修改")
            await expect(second.get_by_label("名称", exact=True)).to_have_value("本地未保存")
            await second.get_by_role(
                "button", name="放弃本地修改并加载最新资料", exact=True
            ).click()
            await expect(second.get_by_label("名称", exact=True)).to_have_value("最新草稿")
        finally:
            await browser.close()


async def test_profile_validation_points_to_invalid_field(admin_url):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await login_browser(page, admin_url)
            await page.get_by_label("名称", exact=True).fill("青禾")
            aliases = page.get_by_label("别名", exact=True)
            await aliases.fill("\n".join(f"别名{i}" for i in range(33)))
            await page.get_by_role("button", name="保存草稿", exact=True).click()
            await expect(page.get_by_role("alert")).to_contain_text("请检查标记的字段")
            await expect(aliases).to_have_attribute("aria-invalid", "true")
            await expect(aliases).to_be_enabled()
            await aliases.fill("小青")
            await page.get_by_role("button", name="保存草稿", exact=True).click()
            await expect(page.get_by_text("草稿已保存", exact=True)).to_be_visible()
            await expect(aliases).not_to_have_attribute("aria-invalid", "true")
        finally:
            await browser.close()


async def test_profile_load_failure_offers_retry(admin_url):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await page.route("**/admin/api/profile", lambda route: route.abort())
            await login_browser(page, admin_url)
            await expect(page.get_by_role("alert")).to_contain_text("无法读取资料")
            await page.unroute("**/admin/api/profile")
            await page.get_by_role("button", name="重新读取资料", exact=True).click()
            await expect(page.get_by_label("名称", exact=True)).to_be_visible()
        finally:
            await browser.close()


async def test_profile_submit_disables_controls_and_expired_session_returns_to_login(admin_url):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        hold = asyncio.Event()
        try:
            page = await browser.new_page()
            await login_browser(page, admin_url)
            await page.get_by_label("名称", exact=True).fill("青禾")

            async def delayed(route):
                await hold.wait()
                await route.continue_()

            await page.route("**/admin/api/profile/draft", delayed)
            await page.get_by_role("button", name="保存草稿", exact=True).click()
            await expect(page.get_by_label("名称", exact=True)).to_be_disabled()
            await expect(page.get_by_role("button", name="保存草稿", exact=True)).to_be_disabled()
            hold.set()
            await expect(page.get_by_text("草稿已保存", exact=True)).to_be_visible()
            await page.context.clear_cookies()
            await page.get_by_label("名称", exact=True).fill("新名字")
            await page.get_by_role("button", name="保存草稿", exact=True).click()
            await expect(page.get_by_role("heading", name="登录管理台")).to_be_visible()
            await expect(page.get_by_role("heading", name="机器人资料")).not_to_be_visible()
        finally:
            hold.set()
            await browser.close()


async def test_profile_csrf_failure_has_session_recovery(admin_url):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await login_browser(page, admin_url)
            await page.get_by_label("名称", exact=True).fill("青禾")

            async def invalid_csrf(route):
                await route.continue_(headers={**route.request.headers, "x-csrf-token": "invalid"})

            await page.route("**/admin/api/profile/draft", invalid_csrf)
            await page.get_by_role("button", name="保存草稿", exact=True).click()
            await expect(page.get_by_role("alert")).to_contain_text("无法验证此次请求")
            await expect(page.get_by_role("button", name="重试原操作")).not_to_be_visible()
            await page.unroute("**/admin/api/profile/draft")
            await page.get_by_role(
                "button", name="刷新登录状态（放弃未保存内容）", exact=True
            ).click()
            await expect(page.get_by_label("名称", exact=True)).to_have_value("")
        finally:
            await browser.close()
