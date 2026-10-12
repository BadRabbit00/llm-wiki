import { test, expect } from "@playwright/test";
import {
  readFileSync,
  mkdtempSync,
  mkdirSync,
  writeFileSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("human uploads docs, sees completed audit and findings", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const issuer = JSON.parse(readFileSync(".e2e/config.json", "utf8")).issuer;
  const session = await page.request.post(
    "http://127.0.0.1:18787/api/v1/sessions",
    {
      headers: { Authorization: `Bearer ${issuer}` },
      data: { subject: "opaque-human", username: "human", groups: ["human"] },
    },
  );
  expect(session.ok()).toBeTruthy();
  await page.context().addCookies([
    {
      name: "wiki_session",
      value: (await session.json()).token,
      url: "http://127.0.0.1:18789",
      httpOnly: true,
      secure: false,
      sameSite: "Lax",
    },
  ]);
  await page.goto("/jobs");
  await page
    .getByRole("button", { name: "Сверить документацию", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Проект", { exact: true }).fill("orders-browser");
  await dialog
    .getByRole("combobox", { name: "Профиль", exact: true })
    .selectOption("python-fastapi");
  const temporary = mkdtempSync(join(tmpdir(), "wiki-audit-browser-"));
  try {
    const docs = join(temporary, "docs");
    mkdirSync(join(docs, "stack"), { recursive: true });
    writeFileSync(join(docs, "stack", "languages.md"), "Python 3.11\n");
    await dialog.getByLabel("Папка документации").setInputFiles(docs);
    await expect(dialog.getByText(/Выбрано файлов: 1/)).toBeVisible();
    await dialog.getByRole("button", { name: "Запустить сверку" }).click();
    await expect(dialog).toBeHidden();
    const card = page
      .locator(".job-card")
      .filter({ hasText: "orders-browser" });
    await expect(card).toBeVisible();
    await expect(card.getByRole("button", { name: "Остановить" })).toHaveCount(
      0,
    );
    await card.getByRole("link", { name: "Находки" }).click();
    await expect(
      page.getByText("Проект использует устаревшую версию Python.").first(),
    ).toBeVisible();
    expect(errors).toEqual([]);
  } finally {
    rmSync(temporary, { recursive: true, force: true });
  }
});
