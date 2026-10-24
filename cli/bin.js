#!/usr/bin/env node
/**
 * OneGameStudio 本地启动 CLI。
 *
 * 用法：
 *   node cli/bin.js                  # 默认 Demo 模式，端口 8000
 *   node cli/bin.js --live           # Live 模式（需要服务端 LLM_API_KEY）
 *   node cli/bin.js --port 8010 --reload
 *   node cli/bin.js --check          # 只检查环境，不启动服务
 *
 * 说明：npm 包尚未发布，`npx onegamestudio` 只有在包发布后才可用。
 */

const { spawn, spawnSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const http = require("http");

const ROOT = path.resolve(__dirname, "..");

function parseArgs(argv) {
  const options = {
    host: "127.0.0.1",
    port: 8000,
    reload: false,
    mode: null,
    open: true,
    check: false,
    help: false,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--help" || arg === "-h") options.help = true;
    else if (arg === "--check") options.check = true;
    else if (arg === "--reload") options.reload = true;
    else if (arg === "--no-open") options.open = false;
    else if (arg === "--live") options.mode = "live";
    else if (arg === "--demo") options.mode = "demo";
    else if (arg === "--port" || arg === "-p") options.port = Number(argv[++i]);
    else if (arg === "--host") options.host = argv[++i];
    else {
      console.error(`未知参数：${arg}`);
      process.exit(2);
    }
  }
  return options;
}

function usage() {
  console.log(`OneGameStudio CLI

  --port <n>     监听端口（默认 8000）
  --host <addr>  监听地址（默认 127.0.0.1）
  --demo         以 Demo 模式启动（默认）
  --live         以 Live 模式启动（必须配置 LLM_API_KEY / LLM_MODEL / MOCK_MODE=false）
  --reload       开发模式自动重载
  --no-open      不自动打开浏览器
  --check        只检查运行环境
  -h, --help     显示帮助
`);
}

function hasCommand(command, args = ["--version"]) {
  const result = spawnSync(command, args, { stdio: "ignore" });
  return !result.error && result.status === 0;
}

function checkEnv() {
  const backend = path.join(ROOT, "backend", "main.py");
  const envExample = path.join(ROOT, ".env.example");
  const demoDir = path.join(ROOT, "demo", "tasks");
  const demoCount = fs.existsSync(demoDir)
    ? fs
        .readdirSync(demoDir, { withFileTypes: true })
        .filter((item) => item.isDirectory()).length
    : 0;

  console.log("OneGameStudio 环境检查");
  console.log(`  项目根目录     ${ROOT}`);
  console.log(`  backend/main.py ${fs.existsSync(backend) ? "存在" : "缺失"}`);
  console.log(`  .env.example   ${fs.existsSync(envExample) ? "存在" : "缺失"}`);
  console.log(`  demo 任务数量  ${demoCount}`);
  console.log(`  node           ${process.version}`);
  console.log(`  uv             ${hasCommand("uv") ? "可用" : "未安装"}`);
  console.log(
    `  python3        ${
      hasCommand("python3", ["--version"]) ? "可用" : "未安装"
    }`,
  );
  return fs.existsSync(backend) && demoCount > 0;
}

function ensureEnvFile() {
  const envPath = path.join(ROOT, ".env");
  const examplePath = path.join(ROOT, ".env.example");
  if (!fs.existsSync(envPath) && fs.existsSync(examplePath)) {
    fs.copyFileSync(examplePath, envPath);
    console.log("已从 .env.example 创建 .env（不会覆盖已有文件）");
  }
}

function waitForHealth(port, attempts = 40) {
  return new Promise((resolve) => {
    let left = attempts;
    const tick = () => {
      const request = http.get(
        { host: "127.0.0.1", port, path: "/api/health", timeout: 800 },
        (response) => {
          response.resume();
          resolve(response.statusCode === 200);
        },
      );
      request.on("error", () => {
        left -= 1;
        if (left <= 0) resolve(false);
        else setTimeout(tick, 500);
      });
      request.on("timeout", () => request.destroy());
    };
    tick();
  });
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    usage();
    return;
  }
  if (options.check) {
    process.exitCode = checkEnv() ? 0 : 1;
    return;
  }

  if (!fs.existsSync(path.join(ROOT, "backend", "main.py"))) {
    console.error(
      "找不到 backend/main.py。请在 OneGameStudio 仓库根目录运行，或安装包含 Python 源码的 npm 包。",
    );
    process.exitCode = 1;
    return;
  }

  ensureEnvFile();
  const mode = options.mode || "demo";
  const env = {
    ...process.env,
    APP_MODE: mode,
    ...(mode === "live" ? { MOCK_MODE: "false" } : { MOCK_MODE: "true" }),
  };

  const uvArgs = [
    "run",
    "--project",
    ROOT,
    "uvicorn",
    "backend.main:app",
    "--host",
    options.host,
    "--port",
    String(options.port),
  ];
  if (options.reload) uvArgs.push("--reload");

  let command = "uv";
  let args = uvArgs;
  if (!hasCommand("uv")) {
    console.log("未检测到 uv，回退到 python3 -m uvicorn");
    command = "python3";
    args = [
      "-m",
      "uvicorn",
      "backend.main:app",
      "--host",
      options.host,
      "--port",
      String(options.port),
      ...(options.reload ? ["--reload"] : []),
    ];
  }

  console.log(`启动 OneGameStudio（${mode.toUpperCase()} 模式）`);
  console.log(`  http://${options.host}:${options.port}`);
  const child = spawn(command, args, { cwd: ROOT, env, stdio: "inherit" });

  if (options.open) {
    waitForHealth(options.port).then((ready) => {
      if (!ready) return;
      const opener =
        process.platform === "darwin"
          ? ["open", [`http://127.0.0.1:${options.port}`]]
          : ["xdg-open", [`http://127.0.0.1:${options.port}`]];
      spawn(opener[0], opener[1], { stdio: "ignore", detached: true }).unref();
    });
  }

  const shutdown = () => child.kill("SIGINT");
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
  child.on("exit", (code) => {
    process.exitCode = code ?? 0;
  });
}

main();
