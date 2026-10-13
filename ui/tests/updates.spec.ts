import { test, expect, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

async function login(page: Page, role: string) {
  const issuer = JSON.parse(readFileSync(".e2e/config.json", "utf8")).issuer;
  const response = await page.request.post(
    "http://127.0.0.1:18787/api/v1/sessions",
    {
      headers: { Authorization: `Bearer ${issuer}` },
      data: { subject: `opaque-${role}`, username: role, groups: [role] },
    },
  );
  expect(response.ok()).toBeTruthy();
  await page.context().addCookies([
    {
      name: "wiki_session",
      value: (await response.json()).token,
      url: "http://127.0.0.1:18789",
      httpOnly: true,
      secure: false,
      sameSite: "Lax",
    },
  ]);
}

test("an administrator confirms an offered update and sees its outcome", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await login(page, "admin");
  await page.goto("/");
  const badge = page.getByRole("link", {
    name: /Доступно обновление v0\.3\.0/,
  });
  await expect(badge).toBeVisible();
  await badge.click();

  const updates = page.locator("#updates");
  await expect(updates.getByText("v0.2.0", { exact: true })).toBeVisible();
  await expect(updates.getByText("Доступна версия v0.3.0")).toBeVisible();
  await expect(
    updates.getByRole("link", { name: /Что изменилось/ }),
  ).toHaveAttribute(
    "href",
    "https://github.com/BadRabbit00/llm-wiki/compare/aaaaaaa...bbbbbbb",
  );
  await updates.getByRole("button", { name: "Обновить", exact: true }).click();

  const dialog = page.getByRole("dialog");
  const confirm = dialog.getByRole("button", { name: "Обновить", exact: true });
  await expect(confirm).toBeDisabled();
  await dialog.getByRole("checkbox", { name: /подходящее время/ }).check();
  await confirm.click();

  await expect(
    page
      .getByRole("dialog")
      .getByRole("heading", { name: /Обновление до v0\.3\.0/ }),
  ).toBeVisible();
  // The page reloads by itself once the update is over.
  await expect(updates.getByText(/Обновлено: v0\.2\.0 → v0\.3\.0/)).toBeVisible(
    {
      timeout: 30000,
    },
  );
  await expect(
    updates.getByText("Установлена последняя версия канала."),
  ).toBeVisible();
  await expect(
    updates.getByText(/Задач агента на паузе перед обновлением: 1/),
  ).toBeVisible();
  await expect(badge).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("updates stay out of sight for everyone but administrators", async ({
  page,
}) => {
  await login(page, "reviewer");
  await page.goto("/settings");
  await expect(
    page.getByRole("heading", { name: "Профиль и подключение" }),
  ).toBeVisible();
  await expect(page.locator("#updates")).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: /Доступно обновление/ }),
  ).toHaveCount(0);
});
