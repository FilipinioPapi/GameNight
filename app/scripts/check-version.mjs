// Fails the build if the version numbers disagree, or if the update notes weren't written for this version.
import { readFileSync } from "node:fs";
const read = (p) => readFileSync(new URL(`../${p}`, import.meta.url), "utf8");
const tauri = JSON.parse(read("src-tauri/tauri.conf.json")).version;
const pkg = JSON.parse(read("package.json")).version;
const cargo = /^version\s*=\s*"([^"]+)"/m.exec(read("src-tauri/Cargo.toml"))?.[1];
const notesFor = /^#\s*([\d.]+)/.exec(read("UPDATE_NOTES.txt"))?.[1];
const bad = [];
if (pkg !== tauri) bad.push(`package.json says ${pkg}, tauri.conf.json says ${tauri}`);
if (cargo !== tauri) bad.push(`Cargo.toml says ${cargo}, tauri.conf.json says ${tauri}`);
if (notesFor !== tauri) bad.push(`UPDATE_NOTES.txt starts with "# ${notesFor}", it should be "# ${tauri}"`);
if (bad.length) {
  console.error("Version check failed:\n- " + bad.join("\n- "));
  process.exit(1);
}
console.log(`Version ${tauri} everywhere`);
