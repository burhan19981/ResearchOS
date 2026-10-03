// Launches the e2e seed+serve backend for the Playwright smoke test.
// A plain npm script string with a leading ".." relative path (the
// natural way to reach ../../../.venv/Scripts/python.exe from this
// package) fails under Windows' cmd.exe ("'..' is not recognized as
// an internal or external command") when spawned by Playwright's
// webServer — resolving the paths in Node first avoids that shell
// quirk entirely, on every OS.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

const repoRoot = path.resolve(import.meta.dirname, "..", "..", "..", "..");
const isWindows = process.platform === "win32";
const pythonPath = path.join(repoRoot, ".venv", isWindows ? "Scripts" : "bin", isWindows ? "python.exe" : "python");
const scriptPath = path.resolve(import.meta.dirname, "..", "..", "api", "e2e_seed_and_serve.py");

if (!existsSync(pythonPath)) {
  console.error(`e2e-api: expected the project virtualenv's Python at ${pythonPath}, but it does not exist.`);
  process.exit(1);
}

const child = spawn(pythonPath, [scriptPath], { stdio: "inherit" });
child.on("exit", (code) => process.exit(code ?? 1));
