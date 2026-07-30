import fs from "node:fs";

const html = fs.readFileSync("src/web/dashboard_shell.html", "utf8");
const match = html.match(
  /<script nonce="__CSP_NONCE__">([\s\S]*?)<\/script>/,
);
if (!match) {
  throw new Error("Dashboard script was not found");
}
const source = match[1]
  .replace("__CSRF_TOKEN__", '"test"')
  .replace("__DASHBOARD_ROLE__", '"owner"');

new Function(source);
