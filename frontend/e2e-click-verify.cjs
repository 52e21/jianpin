// 真实浏览器点击验证（Chrome CDP）
// 流程：落地页「开始匹配」→ /match「填入示例」→「开始匹配」→ /result「采纳」→ 断言成功提示 + 落库
// 用法：node _e2e_click.js   （需 Chrome 已开 --remote-debugging-port=9222、后端 8015、静态服务 3016）
const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer-core");

const OUT = path.join(__dirname, "_e2e_click_result.json");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function clickByText(page, text) {
  const ok = await page.evaluate((t) => {
    const els = [...document.querySelectorAll("button, a, [role=button]")];
    const el = els.find(
      (e) => (e.textContent || "").trim().includes(t) && !e.disabled
    );
    if (!el) return false;
    el.scrollIntoView({ block: "center" });
    el.click();
    return true;
  }, text);
  if (!ok) throw new Error(`找不到可点击元素：${text}`);
}

(async () => {
  const result = { steps: [], apiCalls: [], ok: false, error: null };
  let browser;
  try {
    browser = await puppeteer.connect({ browserURL: "http://127.0.0.1:9222" });
    const page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 900 });

    const consoleErrors = [];
    page.on("pageerror", (e) => consoleErrors.push("pageerror: " + e.message));
    page.on("console", (m) => {
      if (m.type() === "error") consoleErrors.push("console: " + m.text());
    });

    const bodies = {};
    page.on("response", async (r) => {
      const u = r.url();
      if (u.includes("/api/")) {
        result.apiCalls.push(`${r.request().method()} ${u} → ${r.status()}`);
        try {
          bodies[u] = await r.text();
        } catch (_) {}
      }
    });

    console.log("1) 打开落地页");
    await page.goto("http://127.0.0.1:3016/", { waitUntil: "networkidle2", timeout: 30000 });
    result.steps.push("落地页 title=" + (await page.title()));

    console.log("2) 点「开始匹配」进入输入页");
    await clickByText(page, "开始匹配");
    await page.waitForFunction(() => location.pathname === "/match", { timeout: 20000 });
    result.steps.push("已进入 " + new URL(page.url()).pathname);

    console.log("3) 点「填入示例」");
    await clickByText(page, "填入示例");
    await sleep(600);
    const filled = await page.evaluate(() =>
      [...document.querySelectorAll("textarea")].map((t) => t.value.length)
    );
    result.steps.push("textarea 字数=" + JSON.stringify(filled));
    if (!filled.some((n) => n > 50)) throw new Error("示例数据未填入");

    console.log("4) 点「开始匹配」调用 analyze");
    await clickByText(page, "开始匹配");
    await page.waitForFunction(() => location.pathname === "/result", { timeout: 60000 });
    await sleep(1500);
    result.steps.push("已进入 " + new URL(page.url()).pathname);

    const analyzeBody = Object.entries(bodies).find(([u]) => u.includes("/api/agent/analyze"));
    if (!analyzeBody) throw new Error("未捕获到 /api/agent/analyze 响应");
    const analyze = JSON.parse(analyzeBody[1]);
    result.task_id = analyze.task_id;
    result.conclusion = analyze.recommendation.type;
    result.cache_hit = analyze.cache_hit;
    result.steps.push(`analyze 返回 task_id=${analyze.task_id} 结论=${analyze.recommendation.type}`);

    console.log("5) 点击「采纳」按钮（真实点击反馈组件）");
    const feedbackBefore = result.apiCalls.length;
    await clickByText(page, "采纳");
    await sleep(2500);

    const clicked = result.apiCalls.length > feedbackBefore;
    result.steps.push("点击后是否产生新的 /api/ 调用: " + clicked);

    // 断言页面出现成功提示
    const successText = await page.evaluate(() => document.body.innerText);
    result.ui_success = successText.includes("已记录：采纳");
    result.steps.push("页面出现「已记录：采纳」: " + result.ui_success);

    const fbBody = Object.entries(bodies).find(([u]) => u.includes("/api/agent/feedback"));
    result.feedback_response = fbBody ? JSON.parse(fbBody[1]) : null;
    result.console_errors = consoleErrors;

    result.ok = clicked && result.ui_success && !!result.feedback_response;
    if (!result.ok) {
      fs.writeFileSync(path.join(__dirname, "_e2e_page_dump.html"), await page.content());
    }
  } catch (e) {
    result.error = String(e && e.message ? e.message : e);
    try {
      const pages = await browser.pages();
      if (pages[0]) fs.writeFileSync(path.join(__dirname, "_e2e_page_dump.html"), await pages[0].content());
    } catch (_) {}
  } finally {
    if (browser) browser.disconnect();
    fs.writeFileSync(OUT, JSON.stringify(result, null, 2));
    console.log("\n=== 结果 ===");
    console.log(JSON.stringify(result, null, 2));
    process.exit(result.ok ? 0 : 1);
  }
})();
