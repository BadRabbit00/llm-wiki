import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

const pageErrors: string[] = [];
test.beforeEach(async ({ page }) => {
  pageErrors.length = 0;
  page.on("pageerror", (error) => pageErrors.push(error.message));
});
test.afterEach(() => expect(pageErrors).toEqual([]));

async function login(page: Page, role = "human", path = "/") {
  const issuer = JSON.parse(readFileSync(".e2e/config.json", "utf8")).issuer;
  const response = await page.request.post(
    "http://127.0.0.1:18787/api/v1/sessions",
    {
      headers: { Authorization: `Bearer ${issuer}` },
      data: { subject: `opaque-${role}`, username: role, groups: [role] },
    },
  );
  expect(response.ok()).toBeTruthy();
  const session = await response.json();
  await page.context().addCookies([
    {
      name: "wiki_session",
      value: session.token,
      url: "http://127.0.0.1:18789",
      httpOnly: true,
      secure: false,
      sameSite: "Lax",
    },
  ]);
  await page.goto(path);
  await expect(page.locator(".sidebar .user-panel")).toBeVisible();
}
async function logout(page: Page) {
  await page.goto("/settings");
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Выйти", exact: true })
    .click();
  await expect(
    page.getByText("Вы вышли из вики", { exact: false }),
  ).toBeVisible();
  expect(
    (await page.context().cookies()).filter(
      (cookie) => cookie.name === "wiki_session",
    ),
  ).toEqual([]);
}

test("login, keyboard search, theme, real pages and logout", async ({
  page,
}) => {
  await page.goto("/");
  await page.screenshot({
    animations: "disabled",
    path: ".e2e/login.png",
    fullPage: true,
  });
  await expect(
    page.getByText("Вход временно недоступен", { exact: false }),
  ).toBeVisible();
  await login(page);
  expect(await page.evaluate(() => document.cookie)).not.toContain(
    "wiki_session",
  );
  await expect(page.locator(".stat-card").first()).toBeVisible();
  await page.screenshot({
    animations: "disabled",
    path: ".e2e/dashboard.png",
    fullPage: true,
  });
  await page.keyboard.press("Control+k");
  await page.getByRole("dialog").getByRole("textbox").fill("Python");
  await expect(page.locator(".command-result").first()).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/pages\//);
  await expect(page.locator(".prose").first()).toBeVisible();
  await page.getByRole("button", { name: "Тёмная тема" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.screenshot({
    animations: "disabled",
    path: ".e2e/page-dark.png",
    fullPage: true,
  });
  await logout(page);
  expect(
    await page.evaluate(() => sessionStorage.getItem("wiki.token")),
  ).toBeNull();
  expect(
    await page.evaluate(() => localStorage.getItem("wiki.token")),
  ).toBeNull();
});

test("write a proposal, retain typing focus, reject self review and accept as another person", async ({
  page,
}) => {
  await login(page, "human", "/pages");
  await page.getByRole("button", { name: "Создать страницу" }).click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByRole("combobox", { name: "Тип", exact: true })
    .selectOption("term");
  await dialog.getByLabel("Идентификатор").fill("term-browser-workflow");
  const title = dialog.getByLabel("Заголовок");
  await title.pressSequentially("Знание из браузера", { delay: 15 });
  await expect(title).toHaveValue("Знание из браузера");
  await expect(title).toBeFocused();
  await dialog
    .getByLabel("Краткий тезис", { exact: false })
    .fill(
      "Проверяем полный путь нового знания от редактора до принятия человеком.",
    );
  await dialog
    .getByLabel("Содержание страницы")
    .fill(
      "## Определение\n\nСогласованное знание, которое прошло ревью команды.\n\n<script>window.pwned=true</script>\n\n![tracking](https://example.invalid/tracker.png)",
    );
  await dialog.getByRole("button", { name: "Предпросмотр" }).click();
  await expect(dialog.locator("script")).toHaveCount(0);
  await expect(dialog.locator("img")).toHaveCount(0);
  await dialog.getByRole("button", { name: "Отправить на ревью" }).click();
  await expect(page).toHaveURL(/\/proposals\/[a-z0-9-]+$/);
  const proposalURL = page.url();
  await expect(
    page.getByText("Ваше предложение ждёт другого ревьюера"),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Принять", exact: true }),
  ).toHaveCount(0);
  await page.screenshot({
    animations: "disabled",
    path: ".e2e/review.png",
    fullPage: true,
  });
  await logout(page);
  await login(page, "reviewer", proposalURL);
  await page.getByRole("button", { name: "Принять", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Принять и обновить вики" })
    .click();
  await expect(
    page.getByText("Изменения уже вошли в базу знаний."),
  ).toBeVisible();
  await page.goto("/pages/term-browser-workflow");
  await expect(
    page.getByRole("heading", { name: "Знание из браузера" }),
  ).toBeVisible();
  expect(
    await page.evaluate(() => (window as unknown as { pwned?: boolean }).pwned),
  ).toBeUndefined();
});

test("real streamed chat creates plan, history survives reload and belongs to its owner", async ({
  page,
}) => {
  await login(page, "human", "/chat");
  await page
    .getByLabel("Сообщение агенту")
    .fill("Мы используем только асинхронный Python");
  await page.getByRole("button", { name: "Отправить сообщение" }).click();
  await expect(page.locator(".plan-card")).toBeVisible({ timeout: 30000 });
  await expect(page.locator(".chat-history-item")).toContainText(
    "асинхронный Python",
  );
  const sessionURL = page.url();
  await page.screenshot({
    animations: "disabled",
    path: ".e2e/chat.png",
    fullPage: true,
  });
  await page.reload();
  await expect(page.locator(".plan-card")).toBeVisible();
  await page.getByRole("link", { name: "Проверить и применить" }).click();
  await page.getByRole("button", { name: "Принять", exact: true }).click();
  const decision = page.getByRole("dialog");
  await decision.getByRole("checkbox", { name: /Асинхронный Python/ }).check();
  await decision.getByLabel("Уровень Асинхронный Python").selectOption("must");
  await decision.getByLabel("Владелец Асинхронный Python").fill("team-python");
  await expect(
    decision.getByRole("button", { name: "Принять и обновить вики" }),
  ).toBeDisabled();
  await decision.getByRole("checkbox", { name: /Я проверил влияние/ }).check();
  await decision
    .getByRole("button", { name: "Принять и обновить вики" })
    .click();
  await expect(
    page.getByText("Изменения уже вошли в базу знаний."),
  ).toBeVisible();
  await page.goto(sessionURL);
  await expect(
    page.locator(".plan-card").getByText("Принято", { exact: true }),
  ).toBeVisible();
  await logout(page);
  await login(page, "reviewer", sessionURL);
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.locator(".chat-history-item")).toHaveCount(0);
});

test("source upload, extraction, policy export, graph and reader permissions", async ({
  page,
}) => {
  await login(page, "reviewer", "/sources");
  await page
    .getByRole("button", { name: "Добавить источник", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog.locator('input[type="file"]').setInputFiles({
    name: "team-guide.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Команда проверяет изменения.\n".repeat(40)),
  });
  await dialog.getByRole("button", { name: "Добавить в библиотеку" }).click();
  await expect(
    page.getByRole("dialog").getByRole("heading", { name: "team-guide.txt" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Извлечь текст", exact: true })
    .click();
  await expect(page.locator(".toast")).toBeVisible();
  await expect(async () => {
    await page.getByRole("button", { name: "Обновить", exact: true }).click();
    await expect(page.locator(".outline-list")).toBeVisible();
  }).toPass({ timeout: 20000 });
  await page.getByRole("button", { name: "Прочитать фрагмент" }).click();
  await expect(page.locator(".source-text")).toContainText(
    "Команда проверяет изменения",
  );
  await page.goto("/policies");
  await expect(page.locator(".policy-paper .prose")).toBeVisible();
  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Скачать AGENTS.md" }).click();
  expect((await downloading).suggestedFilename()).toContain("AGENTS");
  await page.goto("/graph");
  await expect(page.locator(".graph-node").first()).toBeVisible();
  await page.locator(".graph-node").first().click();
  await page.screenshot({
    animations: "disabled",
    path: ".e2e/graph.png",
    fullPage: true,
  });
  await logout(page);
  await login(page, "reader", "/pages");
  await expect(
    page.getByRole("button", { name: "Создать страницу" }),
  ).toHaveCount(0);
  await page.goto("/sources");
  await expect(
    page.getByRole("heading", {
      name: "Для источников нужен ограниченный допуск",
    }),
  ).toBeVisible();
});

test("mobile navigation and layouts fit a narrow viewport", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.screenshot({
    animations: "disabled",
    path: ".e2e/login-mobile.png",
    fullPage: true,
  });
  await login(page);
  await expect(
    page.getByRole("button", { name: "Открыть навигацию" }),
  ).toBeVisible();
  for (const path of [
    "/",
    "/pages",
    "/chat",
    "/proposals",
    "/graph",
    "/policies",
    "/sources",
    "/jobs",
    "/settings",
  ]) {
    await page.goto(path);
    await expect(page.locator(".main-content")).toBeVisible();
    await expect(page.getByRole("status", { name: "Загрузка" })).toHaveCount(0);
    await expect
      .poll(() =>
        page.evaluate(() => document.documentElement.scrollWidth - innerWidth),
      )
      .toBeLessThanOrEqual(1);
  }
  await page.goto("/");
  await expect(page.locator(".stat-card").first()).toBeVisible();
  await expect(page.getByRole("status", { name: "Загрузка" })).toHaveCount(0);
  await page.screenshot({
    animations: "disabled",
    path: ".e2e/dashboard-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Открыть навигацию" }).click();
  await page
    .getByRole("navigation")
    .getByRole("link", { name: "База знаний" })
    .click();
  await expect(page).toHaveURL(/\/pages$/);
  await expect(page.locator(".sidebar-overlay")).toHaveCount(0);
});
