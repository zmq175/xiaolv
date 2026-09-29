# ruff: noqa: F811 - imported pytest fixtures are intentionally requested by name
import pytest
from playwright.async_api import async_playwright, expect
from test_admin_browser import admin_url  # noqa: F401 - shared real server fixture
from test_admin_server import PASSWORD
from test_speech_reconciliation import scenario  # noqa: F401 - chat entry fixture


@pytest.mark.parametrize("width,height", [(1280, 800), (390, 844)])
async def test_browser_reconciles_speech_after_preview(admin_url, scenario, width, height):
    _, chat, calls, _ = scenario
    assert await chat("first") == "voice_unknown"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page(viewport={"width": width, "height": height})
            await page.goto(admin_url + "/admin/")
            await page.get_by_label("管理员密码", exact=True).fill(PASSWORD)
            await page.get_by_role("button", name="登录", exact=True).click()
            panel = page.get_by_role("region", name="语音费用核对")
            await panel.get_by_role("button", name="核对此笔费用").click()
            await panel.get_by_label("实际费用（人民币）").fill("0.02")
            await panel.get_by_label("核对凭据").fill("合成账单行1，已核对币种")
            await panel.get_by_role("button", name="预览核对").click()
            await expect(panel.get_by_text("确认金额：¥0.02", exact=True)).to_be_visible()
            assert await chat("before-confirm") == "budget_denied"
            assert await page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await panel.screenshot(path=f"artifacts/speech-reconcile-{width}.png")
            await panel.get_by_role("button", name="确认登记费用").click()
            await expect(panel.get_by_text("费用已核对", exact=True)).to_be_visible()
            await page.reload()
            panel = page.get_by_role("region", name="语音费用核对")
            await expect(panel.get_by_text("已核对 ¥0.020000", exact=True)).to_be_visible()
            assert await chat("after-confirm") == "voice_unknown"
            assert len(calls) == 2
        finally:
            await browser.close()


async def test_browser_retries_identical_reconciliation_after_lost_response(admin_url, scenario):
    _, chat, _, _ = scenario
    assert await chat("lost") == "voice_unknown"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            writes = []

            async def lose_first(route):
                writes.append((route.request.headers["idempotency-key"], route.request.post_data))
                if len(writes) == 1:
                    await route.fetch()
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/admin/api/speech-calls/*/reconcile", lose_first)
            await page.goto(admin_url + "/admin/")
            await page.get_by_label("管理员密码", exact=True).fill(PASSWORD)
            await page.get_by_role("button", name="登录", exact=True).click()
            panel = page.get_by_role("region", name="语音费用核对")
            await panel.get_by_role("button", name="核对此笔费用").click()
            await panel.get_by_label("实际费用（人民币）").fill("0.02")
            await panel.get_by_label("核对凭据").fill("synthetic invoice")
            await panel.get_by_role("button", name="预览核对").click()
            await panel.get_by_role("button", name="确认登记费用").click()
            await expect(panel.get_by_role("alert")).to_contain_text("无法确认")
            await expect(panel.get_by_role("button", name="确认登记费用")).to_be_disabled()
            await expect(panel.get_by_role("button", name="返回修改")).to_be_disabled()
            await panel.get_by_role("button", name="重试原核对").click()
            await expect(panel.get_by_text("费用已核对", exact=True)).to_be_visible()
            assert len(writes) == 2 and writes[0] == writes[1]
            assert await chat("after") == "voice_unknown"
            assert await chat("blocked") == "budget_denied"
        finally:
            await browser.close()


async def test_browser_recovers_reads_conflicts_and_paginates_actual_costs(admin_url, scenario):
    _, chat, _, _ = scenario
    assert await chat("a") == "voice_unknown"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await page.route("**/admin/api/speech-calls?*", lambda route: route.abort())
            await page.goto(admin_url + "/admin/")
            await page.get_by_label("管理员密码", exact=True).fill(PASSWORD)
            await page.get_by_role("button", name="登录", exact=True).click()
            panel = page.get_by_role("region", name="语音费用核对")
            await expect(panel.get_by_role("alert")).to_contain_text("无法读取")
            await page.unroute("**/admin/api/speech-calls?*")

            async def one_per_page(route):
                response = await route.fetch(url=route.request.url + "&limit=1")
                await route.fulfill(response=response)

            await page.route("**/admin/api/speech-calls?*", one_per_page)
            await panel.get_by_role("button", name="刷新费用").click()
            await panel.get_by_role("button", name="核对此笔费用").click()
            await panel.get_by_label("实际费用（人民币）").fill("0.02")
            await panel.get_by_label("核对凭据").fill("my invoice")
            await panel.get_by_role("button", name="预览核对").click()
            status = await page.evaluate("""async () => {
                const session = await fetch('/admin/api/session').then(r => r.json());
                const response = await fetch('/admin/api/speech-calls/speech:6:chat-1a/reconcile', {
                    method: 'POST', headers: {'Content-Type':'application/json',
                    'X-CSRF-Token':session.csrf_token, 'Idempotency-Key':'other-admin'},
                    body: JSON.stringify({charged_cny:'0.01', evidence:'other reviewed invoice'})
                }); return response.status;
            }""")
            assert status == 200
            await panel.get_by_role("button", name="确认登记费用").click()
            await expect(panel.get_by_role("alert")).to_contain_text("状态已变化")
            await expect(panel.get_by_text("已核对 ¥0.010000", exact=True)).to_be_visible()
            await expect(panel.get_by_role("button", name="重试原核对")).to_have_count(0)
            assert await chat("b") == "voice_unknown"
            await panel.get_by_role("button", name="刷新费用").click()
            await panel.get_by_role("button", name="加载更多费用").click()
            await expect(panel.get_by_text("speech:6:chat-1b", exact=True)).to_be_visible()
            await expect(panel.get_by_text("speech:6:chat-1a", exact=True)).to_be_visible()
        finally:
            await browser.close()
