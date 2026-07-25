import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(SCRIPT_DIR, "../..");

const TARGET_URL = "https://investidor.suno.com.br/carteiras/dividendos";
const SESSION_DIR = path.join(SCRIPT_DIR, ".suno-session");
const CHROME_CANDIDATES = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
];

const headers = [
  "rank",
  "ticker",
  "setor/tipo",
  "DY esperado",
  "preco de entrada ajustado (R$)",
  "data preco de entrada",
  "preco atual (R$)",
  "variacao preco atual",
  "preco-teto (R$)",
  "alocacao",
  "rentabilidade",
  "relatorio",
  "vies",
];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function getRunMonth(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function getArgValue(name) {
  const arg = process.argv.find((item) => item === name || item.startsWith(`${name}=`));
  if (!arg) return "";
  if (arg.includes("=")) return arg.slice(arg.indexOf("=") + 1);
  const index = process.argv.indexOf(arg);
  return process.argv[index + 1] && !process.argv[index + 1].startsWith("--") ? process.argv[index + 1] : "";
}

function resolveOutputPath() {
  const mes = getArgValue("--mes") || getRunMonth();
  const cliente = getArgValue("--cliente") || "gabriel";
  const fileName = `acoes_recomendadas_${mes}.csv`;

  const cliOutputDir = getArgValue("--output-dir");
  const outputDir = cliOutputDir
    ? path.resolve(cliOutputDir)
    : path.join(PROJECT_ROOT, "clientes", cliente, "inputs", mes);

  return { outputDir, csvPath: path.join(outputDir, fileName) };
}

function csvEscape(value) {
  const text = value == null ? "" : String(value);
  return /[",\n;]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

// Tickers de acoes/units na B3 seguem 4 letras + 1 ou 2 digitos (ex.: PETR4, VALE3, TAEE11).
function parseRow(raw) {
  const lines = raw.text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  const tickerIndex = lines.findIndex((line) => /^[A-Z]{4}\d{1,2}$/.test(line));
  if (tickerIndex < 0) return null;

  const rankMatch = lines
    .slice(0, tickerIndex)
    .join(" ")
    .match(/\b\d+\b/);

  const ticker = lines[tickerIndex];
  const sector = lines[tickerIndex + 1] ?? "";
  const dyIndex = lines.findIndex((line, index) => index > tickerIndex && /^-?\d+,\d+%$/.test(line));
  const dy = dyIndex >= 0 ? lines[dyIndex] : "";
  const entryPrice = dyIndex >= 0 ? lines[dyIndex + 1] ?? "" : "";
  const entryDate = lines.find((line) => /^\d{2}\.\d{2}\.\d{4}$/.test(line)) ?? "";
  const entryDateIndex = entryDate ? lines.indexOf(entryDate) : -1;
  const currentPrice = entryDateIndex >= 0 ? lines[entryDateIndex + 1] ?? "" : "";
  const currentChange = entryDateIndex >= 0 ? lines[entryDateIndex + 2] ?? "" : "";

  const afterCurrent = entryDateIndex >= 0 ? lines.slice(entryDateIndex + 3) : lines.slice(dyIndex + 2);
  const bias = [...afterCurrent].reverse().find((line) => /^(Comprar|Aguardar|Vender)$/i.test(line)) ?? "";
  const percentages = afterCurrent.filter((line) => /^-?\d+,\d+%$/.test(line));
  const ceiling = afterCurrent.find((line) => /^\d{1,3}(?:\.\d{3})*,\d{2}$/.test(line)) ?? "";
  const rank = rankMatch?.[0] ?? "";

  if (!rank || !bias) return null;

  return {
    rank,
    ticker,
    "setor/tipo": sector,
    "DY esperado": dy,
    "preco de entrada ajustado (R$)": entryPrice,
    "data preco de entrada": entryDate,
    "preco atual (R$)": currentPrice,
    "variacao preco atual": currentChange,
    "preco-teto (R$)": ceiling,
    alocacao: percentages.at(-2) ?? "",
    rentabilidade: percentages.at(-1) ?? "",
    relatorio: raw.reportUrl ?? "",
    vies: bias,
  };
}

async function collectVisibleRows(page) {
  return page.evaluate(() => {
    const absoluteUrl = (href) => {
      try {
        return href ? new URL(href, location.origin).toString() : "";
      } catch {
        return "";
      }
    };

    const tickerPattern = /[A-Z]{4}\d{1,2}\b/;

    const tableRows = [...document.querySelectorAll("tbody tr")]
      .map((row) => ({
        text: row.innerText,
        reportUrl: absoluteUrl(row.querySelector('a[href*="relatorio"], a[href*="reader"]')?.getAttribute("href")),
      }))
      .filter((row) => row.text && tickerPattern.test(row.text));

    if (tableRows.length) return tableRows;

    const candidates = [...document.querySelectorAll("div, li")]
      .map((node) => ({
        node,
        text: node.innerText || "",
        childCount: node.children.length,
      }))
      .filter(({ text, childCount }) => childCount >= 6 && tickerPattern.test(text));

    return candidates
      .filter(({ node }) => {
        const parentText = node.parentElement?.innerText || "";
        return parentText.length === node.innerText.length || parentText.length > node.innerText.length * 1.4;
      })
      .map(({ node }) => ({
        text: node.innerText,
        reportUrl: absoluteUrl(node.querySelector('a[href*="relatorio"], a[href*="reader"]')?.getAttribute("href")),
      }));
  });
}

async function findScrollableContainers(page) {
  return page.evaluate(() => {
    return [...document.querySelectorAll("*")]
      .map((element, index) => ({
        index,
        scrollHeight: element.scrollHeight,
        clientHeight: element.clientHeight,
      }))
      .filter((item) => item.scrollHeight > item.clientHeight + 200)
      .sort((a, b) => b.scrollHeight - a.scrollHeight)
      .slice(0, 8)
      .map((item) => item.index);
  });
}

async function scrollContainer(page, containerIndex, amount) {
  await page.evaluate(
    ({ containerIndex: index, amount: delta }) => {
      const element = [...document.querySelectorAll("*")][index];
      if (element) element.scrollTop += delta;
    },
    { containerIndex, amount },
  );
}

async function main() {
  if (process.argv.includes("--help")) {
    console.log("Uso: scripts/suno-acoes/run-suno-acoes.sh [--cliente gabriel] [--mes 2026-07] [--output-dir /caminho]");
    console.log("Por padrao salva em clientes/<cliente>/inputs/<mes>/acoes_recomendadas_<mes>.csv");
    return;
  }

  const { outputDir, csvPath } = resolveOutputPath();
  await fs.mkdir(outputDir, { recursive: true });
  console.log(`Arquivo de saida: ${csvPath}`);

  const executablePath = await (async () => {
    for (const candidate of CHROME_CANDIDATES) {
      try {
        await fs.access(candidate);
        return candidate;
      } catch {
        // Tenta o proximo navegador.
      }
    }
    return undefined;
  })();

  const browser = await chromium.launchPersistentContext(SESSION_DIR, {
    headless: false,
    executablePath,
    viewport: { width: 1680, height: 1000 },
  });
  const page = browser.pages()[0] ?? (await browser.newPage());

  await page.goto(TARGET_URL, { waitUntil: "domcontentloaded" });
  console.log("Login local: se a Suno pedir autenticacao, faca o login na janela do Chromium.");
  console.log("Depois deixe a pagina da carteira de Dividendos (acoes) aberta; a coleta comeca automaticamente quando a tabela aparecer.");

  await page.waitForFunction(
    () => Boolean(document.body?.innerText) && /[A-Z]{4}\d{1,2}\b/.test(document.body.innerText),
    undefined,
    { timeout: 180_000 },
  );
  await page.waitForTimeout(1500);

  const rowsByTicker = new Map();
  let lastCount = 0;
  let stableRounds = 0;

  for (let round = 0; round < 120 && stableRounds < 8; round += 1) {
    const visibleRows = await collectVisibleRows(page);
    for (const raw of visibleRows) {
      const parsed = parseRow(raw);
      if (parsed?.ticker) rowsByTicker.set(parsed.ticker, parsed);
    }

    const containers = await findScrollableContainers(page);
    await page.mouse.wheel(0, 1400);
    for (const containerIndex of containers) {
      await scrollContainer(page, containerIndex, 1400);
    }

    await sleep(350);

    if (rowsByTicker.size === lastCount) stableRounds += 1;
    else stableRounds = 0;
    lastCount = rowsByTicker.size;
    console.log(`Linhas coletadas: ${rowsByTicker.size}`);
  }

  const rows = [...rowsByTicker.values()].sort((a, b) => Number(a.rank || 9999) - Number(b.rank || 9999));
  const csv = [
    headers.map(csvEscape).join(";"),
    ...rows.map((row) => headers.map((header) => csvEscape(row[header])).join(";")),
  ].join("\n");

  await fs.writeFile(csvPath, csv, "utf8");
  console.log(`CSV gerado: ${csvPath}`);
  console.log(`Total de linhas: ${rows.length}`);

  await browser.close();
}

main().catch(async (error) => {
  console.error(error);
  process.exitCode = 1;
});
