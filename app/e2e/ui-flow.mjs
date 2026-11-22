// UI flow test against the browser mock backend (no Tauri needed).
// Usage: npm run dev  (in another shell), then: node e2e/ui-flow.mjs [screenshotDir]
// Covers plan §7: upload many/1 active, save config, success->top-3 preview->save,
// failure keeps config + shows error, stale preview blocks save.
import { createRequire } from "node:module";
const { chromium } = createRequire(import.meta.url)("playwright"); // global install works too
import assert from "node:assert/strict";

const URL = process.env.APP_URL ?? "http://localhost:5173";
const shots = process.argv[2];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: shots ? 2 : 1 });
page.on("dialog", (d) => d.accept());
page.on("pageerror", (e) => { console.error("PAGE ERROR", e); process.exitCode = 1; });
const shot = async (n) => shots && page.screenshot({ path: `${shots}/${n}.png` });
const step = (s) => console.log("✓", s);

await page.goto(URL);
await page.getByRole("button", { name: /open or create workspace/i }).click();
await page.getByRole("button", { name: /add pdf files/i }).click();
await page.getByText("3 added").waitFor();
const radios = page.getByRole("radio", { name: /\.pdf/ });
assert.equal(await radios.count(), 3);
assert.equal(await page.getByRole("radiogroup", { name: "Active file" }).locator('[aria-checked=true]').count(), 1);
step("upload 3 files, exactly 1 active");

// configure from detected table
await page.getByRole("button", { name: /p\.1 · #1/ }).click();
await page.getByLabel("Name").fill("Bank statement – Oct");
await page.getByRole("button", { name: "Save config" }).click();
await page.getByText(/Config “Bank statement – Oct” saved \(v1\)/).waitFor();
step("config built from detected table and saved");

await page.getByRole("button", { name: "Convert & preview" }).click();
await page.getByText(/Preview · top 3 of 42 records/).waitFor();
await page.getByRole("tab", { name: "Data" }).click();
assert.equal(await page.locator(".grid tbody tr").count(), 3);
await page.getByRole("tab", { name: "Rendered" }).click();
await shot("1-preview-success");
step("success: top-3 preview shown before save");

// stale guard
await page.getByLabel(/^Record/).fill("- {{ description }}");
await page.getByText(/config changed after this preview/i).waitFor();
assert.ok(await page.getByRole("button", { name: /^Save 42 records/ }).isDisabled());
step("stale preview blocks save");

// failure keeps config
const broken = "- {{ description }} {{ not_mapped }}";
await page.getByLabel(/^Record/).fill(broken);
await page.getByRole("button", { name: "Convert & preview" }).click();
await page.getByRole("alert").getByText("TEMPLATE_RENDER").waitFor();
assert.equal(await page.getByLabel(/^Record/).inputValue(), broken);
await page.getByText(/existing output file and this config were not changed/i).waitFor();
await shot("2-error-kept-config");
step("failure: error shown, config kept");

// fix, convert, save
await page.getByLabel(/^Record/).fill("- **{{ date }}** {{ description }}: {{ amount }}");
await page.getByRole("button", { name: "Convert & preview" }).click();
await page.getByRole("button", { name: /^Save 42 records/ }).click();
await page.getByText(/Saved 42 records/).waitFor();
await page.locator(".badge.converted").first().waitFor();
step("save after successful preview");

// switch file: other file has its own draft; switch back keeps the first draft
await radios.nth(2).click(); // scanned
await page.getByRole("heading", { name: "scanned-receipt.pdf" }).waitFor();
await page.getByText(/no text layer/).waitFor();
await page.getByLabel("Config").selectOption({ label: "Bank statement – Oct · v1" });
await page.getByRole("button", { name: "Convert & preview" }).click();
await page.getByRole("alert").getByText("NO_TEXT_LAYER").waitFor();
await shot("3-scanned-error");
await radios.nth(0).click();
await page.getByRole("heading", { name: "bank-statement-oct.pdf" }).waitFor(); // switch is async
assert.match(await page.getByLabel(/^Record/).inputValue(), /\{\{ amount \}\}/);
step("per-file drafts survive switching; scanned PDF -> NO_TEXT_LAYER");

// block extraction + pattern tester
await radios.nth(1).click();
await page.getByRole("heading", { name: "invoices-q3.pdf" }).waitFor();
await page.getByRole("radio", { name: "Text blocks (regex)" }).click();
await page.getByRole("button", { name: "Test pattern" }).click();
await page.getByText(/4 matches/).waitFor();
await page.getByRole("button", { name: "Map all sources" }).click();
await page.getByRole("button", { name: "Sections" }).click();
await page.getByRole("button", { name: "Convert & preview" }).click();
await page.getByText(/Preview · top 3 of 12 records/).waitFor();
await shot("4-block-preview");
step("block/regex rule with pattern tester");

await browser.close();
console.log(process.exitCode ? "FAILED" : "ALL UI FLOWS PASSED");
