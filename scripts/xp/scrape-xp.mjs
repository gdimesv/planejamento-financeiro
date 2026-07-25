import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(SCRIPT_DIR, "../..");

const CARTEIRA_URL = "https://experiencia.xpi.com.br/conta/#/carteira";
const EXTRATO_URL = "https://experiencia.xpi.com.br/conta-corrente/extrato/#/";
const SESSION_DIR = path.join(SCRIPT_DIR, ".xp-session");
const CHROME_CANDIDATES = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
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

function resolveOutputDir() {
  const mes = getArgValue("--mes") || getRunMonth();
  const cliente = getArgValue("--cliente") || "gabriel";
  const cliOutputDir = getArgValue("--output-dir");
  const outputDir = cliOutputDir
    ? path.resolve(cliOutputDir)
    : path.join(PROJECT_ROOT, "clientes", cliente, "inputs", mes);
  return { outputDir, mes };
}

// Todas as telas relevantes (carteira, extrato) vivem em iframes cross-origin
// dentro do portal da XP; por isso as buscas de texto precisam varrer todos os
// frames da pagina, e nao apenas o frame principal.
async function countWithTimeout(locator, timeoutMs) {
  return Promise.race([
    locator.count(),
    new Promise((resolve) => setTimeout(() => resolve(0), timeoutMs)),
  ]);
}

async function waitForTextInAnyFrame(page, text, { exact = false, timeoutMs = 180_000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const frame of page.frames()) {
      try {
        const locator = frame.getByText(text, { exact });
        // Um frame em navegacao/destruicao pode nunca resolver count(); um
        // timeout curto por frame evita travar o loop inteiro indefinidamente.
        if (await countWithTimeout(locator, 3_000)) return frame;
      } catch {
        // Frame pode estar navegando/destruido; tenta o proximo.
      }
    }
    await sleep(500);
  }
  return null;
}

async function clickTextInAnyFrame(page, text, { exact = false, timeoutMs = 20_000 } = {}) {
  const frame = await waitForTextInAnyFrame(page, text, { exact, timeoutMs });
  if (!frame) return false;
  await frame.getByText(text, { exact }).first().click({ timeout: 5_000 });
  return true;
}

async function findExcelIconButton(frame) {
  const byLabel = frame.locator(
    '[aria-label*="xls" i], [aria-label*="excel" i], [title*="xls" i], [title*="excel" i]',
  );
  if (await byLabel.count()) return byLabel.first();

  // Os icones de exportacao (buscar, imprimir, pdf, excel) nao tem aria-label
  // e ficam lado a lado na mesma linha; varios OUTROS botoes da pagina (menu,
  // notificacoes) compartilham o mesmo x mais a direita da tela, entao ordenar
  // so por x quebra em caso de empate. O botao "Procurar" tem aria-label fixo
  // e fica no inicio dessa linha; usamos a linha dele (mesmo y) como ancora e
  // pegamos o botao mais a direita SO dentro dessa linha (o de Excel).
  const searchButton = frame.locator('[aria-label="Procurar" i]').first();
  if (!(await searchButton.count())) return null;
  const searchBox = await searchButton.boundingBox();
  if (!searchBox) return null;

  const iconButtons = frame.locator("button:has(svg)");
  const count = await iconButtons.count();
  const sameRow = [];
  for (let i = 0; i < count; i += 1) {
    const box = await iconButtons.nth(i).boundingBox();
    if (box && Math.abs(box.y - searchBox.y) < 10) sameRow.push({ index: i, box });
  }
  if (!sameRow.length) return null;
  sameRow.sort((a, b) => a.box.x - b.box.x);
  return iconButtons.nth(sameRow[sameRow.length - 1].index);
}

async function downloadViaAction({ page, actionLabel, action, destPath, manualTimeoutMs = 120_000 }) {
  const downloadPromise = page.waitForEvent("download", { timeout: manualTimeoutMs });
  let triggered = false;
  try {
    triggered = await action();
  } catch (error) {
    console.error(`Falha ao tentar "${actionLabel}" automaticamente: ${error.message}`);
  }
  if (!triggered) {
    console.log(
      `Nao consegui localizar "${actionLabel}" automaticamente. Clique manualmente na janela do Chromium ` +
        `(aguardando ate ${Math.round(manualTimeoutMs / 1000)}s pelo download).`,
    );
  }
  const download = await downloadPromise;
  await download.saveAs(destPath);
  console.log(`Arquivo salvo: ${destPath}`);
}

async function maybeConfirmExportModal(page) {
  const frame = await waitForTextInAnyFrame(page, "EXPORTAR", { exact: true, timeoutMs: 5_000 });
  if (!frame) return;
  try {
    await frame.getByText("EXPORTAR", { exact: true }).first().click({ timeout: 5_000 });
  } catch {
    // Modal pode nao estar visivel/clicavel (ex: elemento homonimo escondido);
    // o download ja ocorreu antes desta etapa, entao seguimos em frente.
  }
}

async function main() {
  if (process.argv.includes("--help")) {
    console.log("Uso: scripts/xp/run-xp.sh [--cliente gabriel] [--mes 2026-07] [--output-dir /caminho]");
    console.log(
      "Salva posicao (XLS da carteira) e extrato (ultimos 3 meses) em " +
        "clientes/<cliente>/inputs/<mes>/{posicao_m0_xp,extrato_xp}_<mes>.xlsx",
    );
    return;
  }

  const { outputDir, mes } = resolveOutputDir();
  await fs.mkdir(outputDir, { recursive: true });
  const posicaoPath = path.join(outputDir, `posicao_m0_xp_${mes}.xlsx`);
  const extratoPath = path.join(outputDir, `extrato_xp_${mes}.xlsx`);
  console.log(`Posicao sera salva em: ${posicaoPath}`);
  console.log(`Extrato sera salvo em: ${extratoPath}`);

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
    viewport: { width: 1440, height: 900 },
    acceptDownloads: true,
  });
  try {
    const page = browser.pages()[0] ?? (await browser.newPage());

    // --- Posicao (carteira) ---
    await page.goto(CARTEIRA_URL, { waitUntil: "domcontentloaded" });
    console.log("Login: se a XP pedir usuario/senha/token, faca o login na janela do Chromium.");
    console.log('Aguardando a tela "Sua carteira" carregar...');

    const carteiraFrame = await waitForTextInAnyFrame(page, "Sua carteira", { timeoutMs: 180_000 });
    if (!carteiraFrame) {
      throw new Error('Nao encontrei a tela "Sua carteira" a tempo. Verifique o login e rode novamente.');
    }
    await sleep(1_000);

    await downloadViaAction({
      page,
      actionLabel: 'botao "XLS" da carteira',
      action: async () => clickTextInAnyFrame(page, "XLS", { exact: true, timeoutMs: 10_000 }),
      destPath: posicaoPath,
    });
    await maybeConfirmExportModal(page);

    // --- Extrato (ultimos 3 meses, para cobrir buracos de meses sem upload) ---
    await page.goto(EXTRATO_URL, { waitUntil: "domcontentloaded" });
    console.log('Aguardando a tela "Meu extrato" carregar...');
    const extratoFrame = await waitForTextInAnyFrame(page, "Meu extrato", { timeoutMs: 60_000 });
    if (!extratoFrame) {
      throw new Error('Nao encontrei a tela "Meu extrato" a tempo.');
    }
    await sleep(1_000);

    const periodoOk = await clickTextInAnyFrame(page, "3 meses", { exact: true, timeoutMs: 10_000 });
    if (!periodoOk) {
      console.log('Nao consegui clicar em "3 meses" automaticamente; selecione o periodo manualmente.');
    }
    // Da tempo da tabela/toolbar recarregar apos trocar o periodo antes de
    // procurar os icones de exportacao.
    await sleep(3_000);

    await downloadViaAction({
      page,
      actionLabel: "icone de exportar Excel do extrato",
      action: async () => {
        const button = await findExcelIconButton(extratoFrame);
        if (!button) return false;
        await button.click({ timeout: 5_000 });
        // O icone abre um painel "Exportar XLS"; o download so comeca depois
        // de confirmar no botao "EXPORTAR" desse painel.
        return clickTextInAnyFrame(page, "EXPORTAR", { exact: true, timeoutMs: 10_000 });
      },
      destPath: extratoPath,
    });

    console.log("Concluido.");
  } finally {
    await browser.close();
  }
}

main().catch(async (error) => {
  console.error(error);
  process.exitCode = 1;
});
