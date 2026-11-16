# -*- coding: utf-8 -*-
from datetime import datetime

from playwright.async_api import Playwright, async_playwright, Page
import os
import asyncio
import re
import time

from conf import LOCAL_CHROME_PATH
from utils.base_social_media import set_init_script
from utils.log import douyin_logger


def upload_headless() -> bool:
    """上传时是否无窗口跑（默认是）。

    抖音上传是网页自动化，没必要弹 Chrome 窗口。需要盯界面调试时设
    ``DOUYIN_UPLOAD_HEADED=1`` 即可恢复有界面。
    """
    value = os.environ.get("DOUYIN_UPLOAD_HEADED", "").strip().lower()
    return value not in ("1", "true", "yes", "on")


def upload_dry_run() -> bool:
    """是否只完成到“发布”按钮之前（不真的发布）。

    由 ``video_mover.upload.dry_run`` 经环境变量 ``DOUYIN_UPLOAD_DRY_RUN`` 传入。
    """
    value = os.environ.get("DOUYIN_UPLOAD_DRY_RUN", "").strip().lower()
    return value in ("1", "true", "yes", "on")


# 登录/扫码页面的特征（抖音改版过几次：旧代码只认“手机号登录”，新版扫码/手机号
# 表单里这些文字不在 innerText 里（placeholder 不算正文），必须直接找元素）。
_LOGIN_TEXT_MARKERS = ("扫码登录", "手机号登录", "验证码登录", "立即登录")
_LOGIN_INPUT_SELECTORS = ('input[name="normal-input"]', 'input[name="web-login-area-code-input"]')


async def _looks_like_login_page(page) -> bool:
    for text in _LOGIN_TEXT_MARKERS:
        try:
            node = page.get_by_text(text).first
            if await node.count() and await node.is_visible():
                return True
        except Exception:
            continue
    for selector in _LOGIN_INPUT_SELECTORS:
        try:
            node = page.locator(selector).first
            if await node.count() and await node.is_visible():
                return True
        except Exception:
            continue
    return False


# 抖音风控会比对“sessionid 的签发设备”和“正在使用它的浏览器”是否同一台。
# Playwright 的 headless Chromium 默认 UA 是
#   ...HeadlessChrome/158.0.8127.18 Safari/537.36
# 服务器一看就知道是无头浏览器，于是把这个 session 判成可疑并强制登出 ——
# 这正是发布几次之后 cookie 就失效的元凶（stealth.min.js 只改 JS 层，
# 屏蔽不了 HTTP 头里的 UA）。所以所有抖音上下文统一用真 Chrome 的 UA/视口/语言/时区。
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
)


# Chromium 的 UA 伪造了，但 **客户端提示（Client Hints）** 还是暴露真实身份：实测
#   sec-ch-ua: "Chromium";v="158", "Not.A/Brand";v="24", "HeadlessChrome";v="158"
# 服务端只要读这个头就知道是无头浏览器，所以必须一起覆盖。
DESKTOP_CH_UA = '"Google Chrome";v="157", "Chromium";v="157", "Not.A/Brand";v="24"'


def context_options() -> dict:
    """抖音浏览器上下文统一参数（UA/客户端提示/视口/语言/时区/DPR）。"""
    return {
        "user_agent": os.environ.get("DOUYIN_UPLOAD_UA", DESKTOP_UA),
        "viewport": {"width": 1920, "height": 1080},
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "device_scale_factor": 1,
        "extra_http_headers": {
            "sec-ch-ua": DESKTOP_CH_UA,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
    }


def launch_options(headless: bool, executable_path: str | None = None) -> dict:
    """Chromium 启动参数：关掉 AutomationControlled，避免 navigator.webdriver。"""
    options: dict = {
        "headless": headless,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if executable_path:
        options["executable_path"] = executable_path
    return options


async def cookie_auth(account_file):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(**launch_options(headless=True))
        context = await browser.new_context(storage_state=account_file, **context_options())
        context = await set_init_script(context)
        # 创建一个新的页面
        page = await context.new_page()
        # 访问指定的 URL
        await page.goto("https://creator.douyin.com/creator-micro/content/upload")
        ok = True
        try:
            await page.wait_for_url("https://creator.douyin.com/creator-micro/content/upload", timeout=8000)
        except:
            douyin_logger.warning("[+] cookie 失效（未进入上传页）")
            ok = False
        if ok:
            await page.wait_for_timeout(2000)
            if await _looks_like_login_page(page):
                douyin_logger.warning("[+] cookie 失效（页面是登录/扫码页）")
                ok = False
        await context.close()
        await browser.close()
        if ok:
            douyin_logger.info("[+] cookie 有效")
        return ok


async def douyin_setup(account_file, handle=False):
    if not os.path.exists(account_file) or not await cookie_auth(account_file):
        if not handle:
            # Todo alert message
            return False
        douyin_logger.info('[+] cookie文件不存在或已失效，即将自动打开浏览器，请扫码登录，登陆后会自动生成cookie文件')
        await douyin_cookie_gen(account_file)
    return True


async def douyin_cookie_gen(account_file):
    """扫码登录并把 session 存成 storage_state。

    以前这里是 ``await page.pause()``：必须手动在 Playwright Inspector 里点
    “继续”才会执行保存，直接关窗口就白登录了。现在改成**自动检测登录成功**
    （轮询 cookie + 进上传页确认不是登录页），检测到就保存，最多等 5 分钟。
    """
    async with async_playwright() as playwright:
        # 用和上传时完全一致的 UA/视口/语言/时区登录，
        # 这样抖音记录的“设备”就是之后发布用的那个设备。
        browser = await playwright.chromium.launch(**launch_options(headless=False))
        context = await browser.new_context(**context_options())
        context = await set_init_script(context)
        page = await context.new_page()
        await page.goto("https://creator.douyin.com/")
        douyin_logger.info(
            "[+] 请在弹出的窗口里扫码/手机号登录，登录成功后会自动保存 cookie"
            "（最多等 5 分钟，然后窗口会自己关掉）"
        )
        logged_in = False
        deadline = time.time() + 300
        while time.time() < deadline:
            try:
                cookies = {c["name"]: c["value"] for c in await context.cookies()}
                if cookies.get("sessionid") and cookies.get("sid_guard"):
                    await page.goto(
                        "https://creator.douyin.com/creator-micro/content/upload",
                        timeout=20000,
                    )
                    if "creator-micro" in page.url and not await _looks_like_login_page(page):
                        logged_in = True
                        break
            except Exception:  # 页面在跳转/重载，下一轮再看
                pass
            await asyncio.sleep(2)

        if not logged_in:
            await context.close()
            await browser.close()
            raise RuntimeError(
                "登录超时：5 分钟内没检测到登录成功。重新运行 "
                "python Upload/cli_main.py douyin <账号名> login 再试一次。"
            )
        await context.storage_state(path=account_file)
        douyin_logger.success(f"[+] 已保存登录状态到 {account_file}")
        await context.close()
        await browser.close()


class DouYinVideo(object):
    def __init__(self, title, file_path, tags, publish_date: datetime, account_file,
                 thumbnail_path=None, horizontal_cover_path=None, hot_tags: int = 0):
        self.title = title  # 视频标题
        self.file_path = file_path
        self.tags = tags
        self.publish_date = publish_date
        self.account_file = account_file
        self.date_format = '%Y年%m月%d日 %H:%M'
        self.local_executable_path = LOCAL_CHROME_PATH
        self.thumbnail_path = thumbnail_path
        self.horizontal_cover_path = horizontal_cover_path
        self.hot_tags = max(0, int(hot_tags or 0))

    async def set_schedule_time_douyin(self, page, publish_date):
        # 选择包含特定文本内容的 label 元素
        label_element = page.locator("[class^='radio']:has-text('定时发布')")
        # 在选中的 label 元素下点击 checkbox
        await label_element.click()
        await asyncio.sleep(1)
        publish_date_hour = publish_date.strftime("%Y-%m-%d %H:%M")

        await asyncio.sleep(1)
        await page.locator('.semi-input[placeholder="日期和时间"]').click()
        await page.keyboard.press("Control+KeyA")
        await page.keyboard.type(str(publish_date_hour))
        await page.keyboard.press("Enter")

        await asyncio.sleep(1)

    async def handle_upload_error(self, page):
        douyin_logger.info('视频出错了，重新上传中')
        await page.locator('div.progress-div [class^="upload-btn-input"]').set_input_files(self.file_path)

    async def _dismiss_guides(self, page) -> None:
        """关掉新手引导浮层。

        创作者中心会弹“视频预览功能”之类的气泡（带一个“我知道了”按钮），
        它会盖住底部按钮，导致“发布”点了没反应（本机实测：点了几十次都没发出去）。
        """
        # 创作者中心会弹不止一种浮层：
        #   * “视频预览功能 … [我知道了]”
        #   * “Hi，我是发文助手 …” （右侧面板，会拦住“发布”按钮的点击）
        for text in ("我知道了", "知道了", "暂不需要", "关闭", "取消", "暂不", "以后再说", "跳过"):
            try:
                button = page.get_by_text(text, exact=True)
                if await button.count():
                    await button.first.click(timeout=1500)
                    douyin_logger.info(f"  [-] 关掉浮层：{text}")
                    await asyncio.sleep(0.4)
            except Exception:
                continue
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

    async def _sms_modal_visible(self, page) -> bool:
        """发布时抖音可能要求“短信验证码”（为确保是本人操作账号）。"""
        for text in ("接收短信验证码", "请输入当前手机号", "选择其他验证方式"):
            try:
                if await page.get_by_text(text, exact=False).count():
                    return True
            except Exception:
                continue
        return False

    async def _wait_for_manual_code(self, page, timeout_seconds: int = 600) -> bool:
        """等人工在窗口里填验证码（只在有界面模式下有意义）。"""
        douyin_logger.warning(
            "  [-] 抖音要求短信验证码：请在打开的浏览器窗口里输入手机收到的验证码，"
            f"最多等你 {timeout_seconds // 60} 分钟，输入完脚本会自动继续"
        )
        deadline = time.time() + timeout_seconds
        last_note = 0.0
        while time.time() < deadline:
            if not await self._sms_modal_visible(page):
                douyin_logger.info("  [-] 验证码已通过，继续发布")
                return True
            if time.time() - last_note > 30:
                douyin_logger.info("  [-] 仍在等待验证码输入…")
                last_note = time.time()
            await asyncio.sleep(3)
        return False

    async def _already_on_manage(self, page, timeout_seconds: float = 0) -> bool:
        """是否已经跳到作品管理页（=发布成功）。

        只用 URL 判断，不依赖 locator：验证码通过后抖音会自己跳转，此时再拿旧
        locator 去 evaluate 会等导航结束而超时（实测把成功误报成失败）。
        """
        if timeout_seconds:
            try:
                await page.wait_for_url(
                    "**/creator-micro/content/manage**", timeout=int(timeout_seconds * 1000))
            except Exception:
                pass
        try:
            return "creator-micro/content/manage" in page.url
        except Exception:
            return False

    async def _click_publish(self, page, publish_button) -> None:
        """点“发布”：浮层挡住时关浮层再改用元素点击。"""
        try:
            await publish_button.first.click(timeout=8000)
            return
        except Exception:
            pass
        try:
            douyin_logger.warning("  [-] 发布按钮被浮层挡住，改用元素点击")
            await self._dismiss_guides(page)
            await publish_button.first.evaluate("el => el.click()")
        except Exception:
            # evaluate 也可能因为“正好在导航”超时，交给后面的 URL 判断
            douyin_logger.info("  [-] 元素点击超时，直接检查页面是否已跳转")

    async def publish_video(self, page) -> None:
        """点“发布”并确认结果；最多试 3 次，失败就报错，不无限重试。

        以前这里是 `while True` 死循环，且只认跳转到 content/manage 为成功；
        遇到引导浮层遮住按钮时就永远在循环里狂点发布。
        """
        await self._dismiss_guides(page)
        # 封面/作品还在“检测中”时点发布经常毫无反应（实测点完 20 秒不动），先等它跑完
        for _ in range(30):
            try:
                body = await page.locator("body").inner_text()
            except Exception:
                break
            if "封面检测中" not in body and "快速检测中" not in body:
                break
            douyin_logger.info("  [-] 等平台检测完成…")
            await asyncio.sleep(2)
        # 有的账号发布前就被要求先做短信验证（弹窗直接挡在上面）
        if await self._sms_modal_visible(page):
            if upload_headless():
                raise RuntimeError(
                    "抖音要求短信验证码，但当前是无窗口模式，没法人工输入。"
                    "请用有界面模式重跑：set DOUYIN_UPLOAD_HEADED=1 && "
                    "python Upload/douyin_upload.py"
                )
            if not await self._wait_for_manual_code(page):
                raise RuntimeError("等待短信验证码超时（10 分钟），本次不发布")
            await self._dismiss_guides(page)

        publish_button = page.get_by_role('button', name="发布", exact=True)
        if not await publish_button.count():
            raise RuntimeError("抖音发布未成功：页面上找不到“发布”按钮（引导浮层？）")
        # 只点一次。重复点发布在抖音风控里是明显的机器特征（旧代码曾经 while True
        # 狂点几十次），点完没反应就截图、报错、交给人工，不再自己重试。
        await self._click_publish(page, publish_button)
        if await self._already_on_manage(page, 20):
            douyin_logger.success("  [-]视频发布成功")
            return

        # 点完发布才冒出验证码弹窗的情况：等人工输入，通过后抖音通常自己就发布了
        if await self._sms_modal_visible(page):
            if upload_headless():
                raise RuntimeError(
                    "抖音要求短信验证码才能发布；无窗口模式无法输入。"
                    "请用 set DOUYIN_UPLOAD_HEADED=1 重跑，在窗口里输入验证码。"
                )
            if await self._wait_for_manual_code(page):
                if await self._already_on_manage(page, 30):
                    douyin_logger.success("  [-]视频发布成功（验证码通过）")
                    return
                await self._click_publish(page, publish_button)
                if await self._already_on_manage(page, 30):
                    douyin_logger.success("  [-]视频发布成功（验证码通过）")
                    return
            raise RuntimeError("短信验证码通过后仍未发布成功，请到创作者中心手动确认")

        # 点完没跳转：把页面上可能的原因（toast/提示）一起记下来
        try:
            body = await page.locator("body").inner_text()
            hints = [l.strip() for l in body.splitlines()
                     if any(k in l for k in ("请", "失败", "不能", "稍后", "检测", "封面"))][:5]
            if hints:
                douyin_logger.warning(f"  [-] 发布未跳转，页面提示: {hints}")
        except Exception:
            pass
        shot = str(self.file_path) + ".publish_failed.png"
        try:
            await page.screenshot(path=shot, full_page=True)
        except Exception:
            shot = "(截图失败)"
        raise RuntimeError(
            "抖音发布未成功：点击“发布”后 20 秒内没有跳转到作品管理页"
            f"（截图: {shot}）。为避免触发风控，已停止重试。"
        )

    async def upload(self, playwright: Playwright) -> None:
        # 使用 Chromium 浏览器启动一个浏览器实例（默认无窗口，见 upload_headless）
        headless = upload_headless()
        browser = await playwright.chromium.launch(
            **launch_options(headless, self.local_executable_path)
        )
        # 创建一个浏览器上下文：cookie 用 storage_state，其余指纹用统一参数
        context = await browser.new_context(
            storage_state=f"{self.account_file}", **context_options()
        )
        context = await set_init_script(context)

        # 创建一个新的页面
        page = await context.new_page()
        # 访问指定的 URL
        await page.goto("https://creator.douyin.com/creator-micro/content/upload")
        douyin_logger.info(f'[+]正在上传-------{self.title}.mp4')
        # 等待页面跳转到指定的 URL，没进入，则自动等待到超时
        douyin_logger.info(f'[-] 正在打开主页...')
        await page.wait_for_url("https://creator.douyin.com/creator-micro/content/upload")
        # 点击 "上传视频" 按钮
        await page.locator("div[class^='container'] input").set_input_files(self.file_path)

        # 等待页面跳转到指定的 URL 2025.01.08修改在原有基础上兼容两种页面
        while True:
            try:
                # 尝试等待第一个 URL
                await page.wait_for_url(
                    "https://creator.douyin.com/creator-micro/content/publish?enter_from=publish_page", timeout=3)
                douyin_logger.info("[+] 成功进入version_1发布页面!")
                break  # 成功进入页面后跳出循环
            except Exception:
                try:
                    # 如果第一个 URL 超时，再尝试等待第二个 URL
                    await page.wait_for_url(
                        "https://creator.douyin.com/creator-micro/content/post/video?enter_from=publish_page",
                        timeout=3)
                    douyin_logger.info("[+] 成功进入version_2发布页面!")

                    break  # 成功进入页面后跳出循环
                except:
                    print("  [-] 超时未进入视频发布页面，重新尝试...")
                    await asyncio.sleep(0.5)  # 等待 0.5 秒后重新尝试
        # 填充标题和话题
        # 检查是否存在包含输入框的元素
        # 这里为了避免页面变化，故使用相对位置定位：作品标题父级右侧第一个元素的input子元素
        await asyncio.sleep(1)
        douyin_logger.info(f'  [-] 正在填充标题和话题...')
        title_container = page.get_by_text('作品标题').locator("..").locator("xpath=following-sibling::div[1]").locator("input")
        if await title_container.count():
            await title_container.fill(self.title[:30])
        else:
            titlecontainer = page.locator(".notranslate")
            await titlecontainer.click()
            await page.keyboard.press("Backspace")
            await page.keyboard.press("Control+KeyA")
            await page.keyboard.press("Delete")
            await page.keyboard.type(self.title)
            await page.keyboard.press("Enter")
        added_topics = await self._fill_topics(page, self.tags, self.hot_tags)
        douyin_logger.info(f'总共添加{len(added_topics)}个话题: {added_topics}')

        while True:
            # 判断重新上传按钮是否存在，如果不存在，代表视频正在上传，则等待
            try:
                #  新版：定位重新上传
                number = await page.locator('[class^="long-card"] div:has-text("重新上传")').count()
                if number > 0:
                    douyin_logger.success("  [-]视频上传完毕")
                    break
                else:
                    douyin_logger.info("  [-] 正在上传视频中...")
                    await asyncio.sleep(2)

                    if await page.locator('div.progress-div > div:has-text("上传失败")').count():
                        douyin_logger.error("  [-] 发现上传出错了... 准备重试")
                        await self.handle_upload_error(page)
            except:
                douyin_logger.info("  [-] 正在上传视频中...")
                await asyncio.sleep(2)
        
        #上传视频封面
        await self.set_thumbnail(page, self.thumbnail_path, self.horizontal_cover_path)

        # 更换可见元素
        await self.set_location(page, "杭州市")

        # 頭條/西瓜
        third_part_element = '[class^="info"] > [class^="first-part"] div div.semi-switch'
        # 定位是否有第三方平台
        if await page.locator(third_part_element).count():
            # 检测是否是已选中状态
            if 'semi-switch-checked' not in await page.eval_on_selector(third_part_element, 'div => div.className'):
                await page.locator(third_part_element).locator('input.semi-switch-native-control').click()

        if self.publish_date != 0:
            await self.set_schedule_time_douyin(page, self.publish_date)

        # 判断视频是否发布成功
        if upload_dry_run():
            # 只验流程：表单填好、封面上传好，停在“发布”按钮之前
            douyin_logger.info("  [-] dry_run：表单已就绪，停在“发布”按钮前，不真正发布")
            try:
                await page.screenshot(path=str(self.file_path) + ".dry_run.png", full_page=True)
            except Exception:
                pass
        else:
            await self.publish_video(page)

        await context.storage_state(path=self.account_file)  # 保存cookie
        douyin_logger.success('  [-]cookie更新完毕！')
        await asyncio.sleep(2)  # 这里延迟是为了方便眼睛直观的观看
        # 关闭浏览器上下文和浏览器实例
        await context.close()
        await browser.close()
    
    async def _click_suggestion(self, page, tag: str, skip: int = 0) -> str:
        """在“#话题”联想下拉里选官方话题（带播放量的那种），返回选中的文本。

        ``skip=0`` 优先选和 ``tag`` 同名的官方话题；``skip>0`` 用于“热门标签”，
        按播放量从高到低补几个相关话题。选不到返回空串。
        """
        try:
            picked = await page.evaluate(
                """([tag, skip]) => {
                  // 页面上可能有多个联想容器，挑“带播放量的行”最多的那个
                  const drops = [...document.querySelectorAll('[class*="suggest"]')]
                                 .filter(d => d.offsetParent);
                  let best = null, bestRows = [];
                  for (const drop of drops) {
                    const rows = [...drop.querySelectorAll('div,li,span')].filter(e => {
                      const parts = (e.innerText || '').split(String.fromCharCode(10))
                                      .map(x => x.trim()).filter(Boolean);
                      return parts.length === 2 && parts[0].startsWith('#')
                             && /[0-9.]+[亿万]$/.test(parts[1]);
                    });
                    if (rows.length > bestRows.length) { best = drop; bestRows = rows; }
                  }
                  if (!bestRows.length) return '';
                  // 行首是话题、第二行是播放量（如 “#xxx万”）。
                  const headOf = e => ((e.innerText || '').trim()
                                        .split(String.fromCharCode(10))[0] || '').trim();
                  // skip=0：优先同名官方话题，否则第一行；
                  // skip>0：命中“热门标签”，排除“同名”行后按序号取。
                  // 注意必须用“完全相同”而不是 startsWith：像
                  // #今天是太阳雨定档1106 也以 #今天是太阳雨 开头，用前缀过滤会
                  // 把所有相关热门话题一起滤掉，热门标签永远加不上。
                  let pool = bestRows;
                  if (skip > 0) {
                    pool = bestRows.filter(e => headOf(e) !== '#' + tag);
                  }
                  let pick;
                  if (skip === 0) {
                    pick = pool.find(e => headOf(e) === '#' + tag) || pool[0];
                  } else {
                    pick = pool[skip - 1];
                  }
                  if (!pick) return '';
                  pick.click();
                  const parts = (pick.innerText || '').split(String.fromCharCode(10))
                                  .map(x => x.trim()).filter(Boolean);
                  return parts[0] || '#';
                }""",
                [tag, skip],
            ) or ""
            return re.sub(r"[0-9.]+[亿万]$", "", picked)
        except Exception as e:
            douyin_logger.debug(f"选官方话题失败: {e}")
            return ""

    async def _fill_topics(self, page, tags, hot_tags: int = 0) -> list:
        """把话题填进描述框，并尽量挂上官方话题（联想结果），再补几个热门话题。"""
        selector = ".zone-container"
        added = []
        for tag in tags:
            await page.type(selector, "#" + tag)
            await asyncio.sleep(2.0)
            picked = await self._click_suggestion(page, tag)
            if picked:
                added.append(picked)
                douyin_logger.info(f"  [-] 话题已挂官方话题：{picked}")
            else:
                await page.press(selector, "Space")
                added.append("#" + tag)
            await asyncio.sleep(0.4)

        # 热门标签：同一个关键词下按播放量再补几个官方话题
        for tag in tags:
            for index in range(1, hot_tags + 1):
                await page.type(selector, "#" + tag)
                await asyncio.sleep(2.0)
                picked = await self._click_suggestion(page, tag, skip=index)
                if picked and picked not in added:
                    added.append(picked)
                    douyin_logger.info(f"  [-] 加了个热门话题：{picked}")
                else:
                    # 没选中就撤掉刚敲的 "#tag"
                    for _ in range(len(tag) + 1):
                        await page.keyboard.press("Backspace")
                    break
                await asyncio.sleep(0.4)
        return added

    async def _open_cover_modal(self, page):
        """打开封面编辑弹窗（已经开着就复用），返回 modal locator。

        设完一张封面后，页面上的“选择封面”可能变成悬浮才显示的可点区域，
        Playwright 的可点性检查会超时，所以点不动就用 JS 直接触发一次。
        """
        modal = page.locator("div.dy-creator-content-modal-wrap").last
        if await page.locator("div.dy-creator-content-modal-wrap").count():
            return modal
        try:
            await page.get_by_text("选择封面").first.click(timeout=6000)
        except Exception:
            await page.evaluate(
                """() => {
                  const els = [...document.querySelectorAll('*')]
                      .filter(e => !e.children.length && (e.innerText || '').trim() === '选择封面');
                  if (els.length) els[0].click();
                }"""
            )
        await modal.wait_for(state="visible", timeout=15000)
        return modal

    async def _upload_cover_in_modal(self, page, image_path: str) -> bool:
        """在当前封面 tab 里塞图并点“完成”。

        弹窗里有多个图片上传框：左侧“生成参考图/AI素材”列表 2 个，真正能换封面的
        是“上传封面”按钮所在容器里的那一个。旧实现固定取第一个 ``input``，图被塞进
        参考图列表，封面一直是平台默认的第 0 帧——而处理后的视频首帧是淡入黑场，
        所以发出去的作品封面永远是黑的。这里按“上传封面”按钮反查它所在容器里的
        file input。
        """
        tagged = False
        for _ in range(6):
            try:
                tagged = await page.evaluate(
                    """() => {
                      const modals = [...document.querySelectorAll(
                          'div.dy-creator-content-modal-wrap, div.dy-creator-content-modal')]
                          .filter(e => e.offsetParent);
                      const m = modals[modals.length - 1];
                      if (!m) return false;
                      const btn = [...m.querySelectorAll('*')].find(
                          e => (e.innerText || '').trim() === '上传封面' && e.offsetParent);
                      const root = btn && btn.closest('div[class*="container-"]');
                      const input = root && root.querySelector('input[type="file"]');
                      if (!input) return false;
                      input.setAttribute('data-omp-cover-input', '1');
                      return true;
                    }"""
                )
            except Exception:
                tagged = False
            if tagged:
                break
            await asyncio.sleep(1.0)
        if not tagged:
            douyin_logger.warning("  [-] 找不到“上传封面”的图片输入框")
            return False
        upload_input = page.locator("input[data-omp-cover-input='1']").first
        try:
            await upload_input.wait_for(state="attached", timeout=10000)
            await upload_input.set_input_files(str(image_path))
        except Exception as e:
            douyin_logger.warning(f"  [-] 封面文件塞不进上传框: {e}")
            return False
        done = page.locator(
            "div.dy-creator-content-modal-wrap, div.dy-creator-content-modal"
        ).last.get_by_role("button", name="完成").first
        for _ in range(20):
            await asyncio.sleep(1.0)
            try:
                if await done.is_enabled():
                    break
            except Exception:
                return False
        try:
            await done.click(timeout=8000)
            await asyncio.sleep(2.0)
            return True
        except Exception as e:
            douyin_logger.warning(f"  [-] 封面“完成”点不动: {e}")
            return False

    async def _switch_cover_tab(self, modal, tab_name: str, page=None) -> bool:
        """在封面弹窗里切到另一个 tab（“设置横封面”/“设置竖封面”）。"""
        for locator_factory in (
            lambda: modal.get_by_role("button", name=tab_name),
            lambda: modal.get_by_text(tab_name, exact=True),
        ):
            try:
                locator = locator_factory()
                if await locator.count():
                    await locator.first.click(timeout=4000)
                    await asyncio.sleep(1.8)
                    return True
            except Exception:
                continue
        # 最后兜底：JS 直接点（Playwright 的可点性检查会被浮层挡住）
        try:
            done = await (page or modal.page).evaluate(
                """(name) => {
                  const modals = [...document.querySelectorAll('div.dy-creator-content-modal-wrap')]
                                   .filter(e => e.offsetParent);
                  if (!modals.length) return false;
                  const m = modals[modals.length - 1];
                  const btn = [...m.querySelectorAll('button,[role=button],div')]
                      .find(e => (e.innerText || '').trim() === name);
                  if (!btn) return false;
                  btn.click();
                  return true;
                }""",
                tab_name,
            )
            if done:
                await asyncio.sleep(1.8)
                return True
        except Exception:
            pass
        try:
            labels = [b.strip()[:12] for b in await modal.get_by_role("button").all_inner_texts()]
            text = (await modal.inner_text()).replace(chr(10), " / ")[:160]
            douyin_logger.info(f"  [-] 封面弹窗现状 按钮={labels} 文本={text}")
        except Exception:
            pass
        return False

    async def _use_ai_cover(self, page) -> bool:
        """让平台用它 AI 生成的封面（自己传图失败时的兜底）。"""
        modal = page.locator("div.dy-creator-content-modal-wrap").last
        try:
            await modal.get_by_role("button", name="AI生成封面").first.click(timeout=8000)
            douyin_logger.info("  [-] 点“AI生成封面”，等平台生成…")
            await asyncio.sleep(3)
        except Exception as e:
            douyin_logger.warning(f"  [-] 点不到“AI生成封面”: {e}")
            return False
        # 生成出来的封面会出现在列表里（aiGenCoverList-*），点第一张选中
        for _ in range(20):
            await asyncio.sleep(1.5)
            try:
                card = modal.locator("[class*='aiGenCoverList'] img, [class*='coverList'] img").first
                if await card.count():
                    await card.click(timeout=6000)
                    await asyncio.sleep(1.5)
                    douyin_logger.info("  [-] 已选中 AI 推荐封面")
                    break
            except Exception:
                continue
        done = modal.get_by_role("button", name="完成").first
        for _ in range(20):
            await asyncio.sleep(1.0)
            try:
                if await done.is_enabled():
                    await done.click(timeout=8000)
                    await asyncio.sleep(2.0)
                    douyin_logger.success("  [-] 封面用了 AI 推荐图")
                    return True
            except Exception:
                return False
        return False

    async def _reopen_cover_modal(self, page, attempts: int = 3):
        """打开（或复用）封面弹窗。

        注意必须判断“真的可见”：弹窗关掉后 DOM 里可能还留着隐藏的
        ``dy-creator-content-modal-wrap``，只看 count>0 会拿到一个隐藏元素，
        后面的点击全部 30 秒超时。
        """
        modal = page.locator(
            "div.dy-creator-content-modal-wrap, div.dy-creator-content-modal"
        ).last
        for _ in range(attempts):
            try:
                if await modal.count() and await modal.is_visible():
                    return modal
            except Exception:
                pass
            try:
                await page.evaluate(
                    """() => {
                      const els = [...document.querySelectorAll('div,span')]
                          .filter(e => !e.children.length
                                  && (e.innerText || '').trim() === '选择封面' && e.offsetParent);
                      if (els.length) els[0].click();
                    }"""
                )
                await modal.wait_for(state="visible", timeout=8000)
                return modal
            except Exception:
                await asyncio.sleep(1.5)
        return None

    async def _cover_preview_srcs(self, page) -> list:
        """页面上“设置封面”预览图的地址，用来判断封面到底换没换。"""
        try:
            return await page.evaluate(
                """() => [...document.querySelectorAll('[class*="coverControl"] img')]
                        .map(i => i.getAttribute('src') || '')
                        .filter(Boolean)"""
            )
        except Exception:
            return []

    async def set_thumbnail(self, page: Page, thumbnail_path: str = "", horizontal_cover: str = ""):
        """设置竖/横封面（抖音会提示“横/竖双封面缺失”，两个都设曝光更好）。

        实测要点：
        * 点“选择封面”打开封面弹窗，默认“设置竖封面”tab；
        * 弹窗里换封面只能用“上传封面”那个 file input（见 ``_upload_cover_in_modal``）；
        * 点“完成”之后弹窗经常自己关掉，而页面上仍留着两个“选择封面”（竖/横各一个），
          直接用 JS 点它重新打开，再切到“设置横封面”传第二张 —— 用 Playwright
          的可点性检查在这里会一直超时（元素被遮挡/需要悬停）。
        不点“完成”时页面预览不会变，所以设完要对比预览图地址，别只看自己的日志。
        """
        if not thumbnail_path and not horizontal_cover:
            return
        before = await self._cover_preview_srcs(page)
        modal = await self._reopen_cover_modal(page)
        if modal is None:
            douyin_logger.warning("  [-] 打不开封面弹窗，跳过设置封面")
            return

        # 先设横封面：刚打开的弹窗里切 tab 才有效；点过“完成”之后切 tab 会被忽略
        # （实测按钮点了没反应），所以顺序是 横 → 竖，不能反过来。
        if horizontal_cover:
            text_now = ""
            try:
                text_now = await modal.inner_text()
            except Exception:
                pass
            switched = ("横封面预览" in text_now) or await self._switch_cover_tab(modal, "设置横封面")
            if switched and await self._upload_cover_in_modal(page, horizontal_cover):
                douyin_logger.info("  [-] 横封面已设置")
            else:
                douyin_logger.warning("  [-] 横封面没设成功")

        if thumbnail_path:
            modal = await self._reopen_cover_modal(page)
            if modal is None:
                douyin_logger.warning("  [-] 重新打开封面弹窗失败，竖封面没设")
            elif await self._upload_cover_in_modal(page, thumbnail_path):
                douyin_logger.info("  [-] 竖封面已设置")

        try:
            for _ in range(3):
                visible_modal = page.locator(
                    "div.dy-creator-content-modal-wrap, div.dy-creator-content-modal"
                ).last
                if not (await visible_modal.count() and await visible_modal.is_visible()):
                    break
                await page.keyboard.press("Escape")
                await asyncio.sleep(1.2)
        except Exception:
            pass

        after = await self._cover_preview_srcs(page)
        changed = bool(before) and bool(after) and after != before
        if thumbnail_path and before and after and not changed:
            # 预览没变说明“完成”没把图应用上去，退到平台 AI 封面，别让作品挂黑封面
            douyin_logger.warning("  [-] 封面预览没变，改用 AI 推荐封面")
            if await self._reopen_cover_modal(page):
                await self._use_ai_cover(page)
            after = await self._cover_preview_srcs(page)
            changed = bool(before) and bool(after) and after != before
        douyin_logger.success(
            f"  [-] 封面已处理（{'预览已更新' if changed else '预览未变化/无法确认'}；"
            f"页面提示: {await self._cover_warning(page) or '无'}）"
        )

    async def _cover_warning(self, page) -> str:
        """读“发文助手/封面”那块关于封面的提示，用来判断封面到底设上没有。"""
        try:
            body = await page.locator("body").inner_text()
        except Exception:
            return ""
        lines = [l.strip() for l in body.splitlines() if "封面" in l]
        for line in lines:
            if "缺失" in line or "检测通过" in line or "低质" in line:
                return line[:40]
        return " ".join(lines)[:40]

    async def set_location(self, page: Page, location: str = "杭州市"):
        # todo supoort location later
        # await page.get_by_text('添加标签').locator("..").locator("..").locator("xpath=following-sibling::div").locator(
        #     "div.semi-select-single").nth(0).click()
        await page.locator('div.semi-select span:has-text("输入地理位置")').click()
        await page.keyboard.press("Backspace")
        await page.wait_for_timeout(2000)
        await page.keyboard.type(location)
        await page.wait_for_selector('div[role="listbox"] [role="option"]', timeout=5000)
        await page.locator('div[role="listbox"] [role="option"]').first.click()

    async def main(self):
        async with async_playwright() as playwright:
            await self.upload(playwright)


