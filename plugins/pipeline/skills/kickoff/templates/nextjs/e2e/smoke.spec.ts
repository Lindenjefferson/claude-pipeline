import { expect, test } from "@playwright/test";

test("the home page answers @smoke", async ({ page }) => {
  const response = await page.goto("/");
  expect(response?.status()).toBeLessThan(400);
});
