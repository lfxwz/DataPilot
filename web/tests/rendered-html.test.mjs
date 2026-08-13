import assert from "node:assert/strict";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the DataPilot analysis workbench", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<html lang="zh-CN">/i);
  assert.match(html, /<title>DataPilot · 分析工作台<\/title>/i);
  assert.match(html, /向数据提问/);
  assert.match(html, /最近运行/);
  assert.match(html, /开始分析/);
  assert.match(html, /http:\/\/127\.0\.0\.1:8000\/docs/);
  assert.doesNotMatch(html, /Your site is taking shape|Building your site/i);
});

test("keeps model-generated output out of executable frontend surfaces", async () => {
  const page = await import("node:fs/promises").then(({ readFile }) =>
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
  );

  assert.match(page, /NEXT_PUBLIC_DATAPILOT_API/);
  assert.match(page, /\/agent\/analyze/);
  assert.doesNotMatch(page, /dangerouslySetInnerHTML/);
  assert.doesNotMatch(page, /\beval\s*\(|new Function\s*\(/);
});
