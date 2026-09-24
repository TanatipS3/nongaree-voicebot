#!/usr/bin/env node
/**
 * Admin tool for the Aree problem reports.
 *
 * Reports are append-only JSONL written by app/api/report/route.ts, rotated monthly
 * only so a retention policy can delete a file instead of migrating rows. Rotation
 * never gated reading — every subcommand here works at any moment, on demand.
 *
 * Usage (on the server, against the named volume):
 *
 *   docker run --rm -v nongaree-voicebot_report_data:/data/reports:ro \
 *     -v "$PWD/scripts:/s:ro" node:22-alpine node /s/reports.mjs summary
 *
 * Or directly if you have the directory mounted:
 *
 *   node scripts/reports.mjs summary
 *   node scripts/reports.mjs summary --since 2026-08-01
 *   node scripts/reports.mjs export --format csv --out /tmp/reports.csv
 *   node scripts/reports.mjs rotate            # seal the current file, start fresh
 *   node scripts/reports.mjs list
 *   node scripts/reports.mjs purge             # dry run: what retention would delete
 *   node scripts/reports.mjs purge --yes       # actually delete
 *
 * Retention is 6 months (REPORT_RETENTION_MONTHS overrides). `purge` is manual on
 * purpose — see cmdPurge. Note the docker example above mounts the volume :ro, which
 * is fine for reading but purge needs it writable.
 *
 * REPORT_DIR overrides the location (default /data/reports).
 */

import { readdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import path from "node:path";

const REPORT_DIR = process.env.REPORT_DIR || "/data/reports";

const TYPE_LABELS = {
  wrong_answer: "คำตอบไม่ถูกต้อง",
  incomplete: "ตอบไม่ตรงคำถาม / ข้อมูลไม่ครบ",
  outdated: "ข้อมูลล้าสมัย",
  no_response: "ระบบค้าง / ไม่ตอบ",
  audio_mic: "เสียง หรือ ไมโครโฟนมีปัญหา",
  other: "อื่น ๆ",
};

function parseArgs(argv) {
  const [command = "summary", ...rest] = argv;
  const flags = {};
  for (let i = 0; i < rest.length; i += 1) {
    if (rest[i].startsWith("--")) {
      const key = rest[i].slice(2);
      const next = rest[i + 1];
      if (next && !next.startsWith("--")) {
        flags[key] = next;
        i += 1;
      } else {
        flags[key] = true;
      }
    }
  }
  return { command, flags };
}

async function reportFiles() {
  let entries;
  try {
    entries = await readdir(REPORT_DIR);
  } catch {
    return [];
  }
  return entries
    .filter((name) => name.startsWith("reports-") && name.endsWith(".jsonl"))
    .sort();
}

async function loadReports({ since, until } = {}) {
  const files = await reportFiles();
  const rows = [];
  for (const file of files) {
    const text = await readFile(path.join(REPORT_DIR, file), "utf8");
    for (const line of text.split("\n")) {
      if (!line.trim()) continue;
      try {
        const row = JSON.parse(line);
        if (since && row.created_at < since) continue;
        if (until && row.created_at > until) continue;
        rows.push(row);
      } catch {
        // A truncated final line can happen if the container died mid-write.
        // Skip it rather than failing the whole report.
        console.error(`! skipped unparseable line in ${file}`);
      }
    }
  }
  return rows;
}

function tally(rows, pick) {
  const counts = new Map();
  for (const row of rows) {
    for (const key of [pick(row)].flat()) {
      if (key === undefined || key === null || key === "") continue;
      counts.set(key, (counts.get(key) || 0) + 1);
    }
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

function bar(count, max, width = 24) {
  return "#".repeat(Math.max(1, Math.round((count / max) * width)));
}

async function cmdSummary(flags) {
  const rows = await loadReports({ since: flags.since, until: flags.until });
  if (!rows.length) {
    console.log(`No reports found in ${REPORT_DIR}.`);
    return;
  }

  const first = rows.reduce((a, r) => (r.created_at < a ? r.created_at : a), rows[0].created_at);
  const last = rows.reduce((a, r) => (r.created_at > a ? r.created_at : a), rows[0].created_at);

  console.log(`Aree problem reports — ${rows.length} total`);
  console.log(`${first}  ->  ${last}`);
  console.log(`source: ${REPORT_DIR}`);

  const byType = tally(rows, (r) => r.type);
  const maxType = byType[0]?.[1] || 1;
  console.log("\nBy type");
  for (const [type, count] of byType) {
    const label = TYPE_LABELS[type] || type;
    console.log(`  ${String(count).padStart(4)}  ${bar(count, maxType)}  ${type} — ${label}`);
  }

  // The actionable one: which knowledge-base chunks keep producing complaints.
  const byChunk = tally(rows, (r) => (r.sources || []).map((s) => s.cluster_id));
  if (byChunk.length) {
    console.log("\nMost-reported chunks (cluster_id)");
    for (const [cluster, count] of byChunk.slice(0, 15)) {
      const example = rows
        .flatMap((r) => r.sources || [])
        .find((s) => s.cluster_id === cluster);
      const flag = example?.outdated ? "  [possibly_outdated]" : "";
      console.log(`  ${String(count).padStart(4)}  ${cluster}  ${example?.title || ""}${flag}`);
    }
  }

  const noSource = rows.filter((r) => r.diagnostics?.retrieval_empty).length;
  const noTurn = rows.filter((r) => !r.turn || !r.turn.question).length;
  console.log("\nDiagnostics");
  console.log(`  ${String(noSource).padStart(4)}  retrieval returned nothing (score gate)`);
  console.log(`  ${String(noTurn).padStart(4)}  reported with no completed turn`);

  const byRoute = tally(rows, (r) => r.diagnostics?.route);
  if (byRoute.length) {
    console.log("\nBy route");
    for (const [route, count] of byRoute) {
      console.log(`  ${String(count).padStart(4)}  ${route}`);
    }
  }

  console.log("\nMost recent messages");
  for (const row of rows.slice(-8).reverse()) {
    const when = row.created_at.replace("T", " ").slice(0, 16);
    console.log(`  [${when}] ${row.type}: ${row.message.replace(/\s+/g, " ").slice(0, 90)}`);
  }
}

function toCsv(rows) {
  const columns = [
    "report_id", "created_at", "username", "type", "message",
    "question", "route", "retrieval_empty", "cluster_ids", "job_id",
  ];
  const escape = (value) => {
    const text = value === undefined || value === null ? "" : String(value);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  const lines = [columns.join(",")];
  for (const row of rows) {
    lines.push([
      row.report_id,
      row.created_at,
      row.username,
      row.type,
      row.message,
      row.turn?.question,
      row.diagnostics?.route,
      row.diagnostics?.retrieval_empty,
      (row.sources || []).map((s) => s.cluster_id).join(" "),
      row.diagnostics?.job_id,
    ].map(escape).join(","));
  }
  return lines.join("\n");
}

async function cmdExport(flags) {
  const rows = await loadReports({ since: flags.since, until: flags.until });
  const format = flags.format || "json";
  const body = format === "csv" ? toCsv(rows) : JSON.stringify(rows, null, 2);
  if (flags.out) {
    await writeFile(flags.out, body, "utf8");
    console.log(`Wrote ${rows.length} reports to ${flags.out} (${format})`);
  } else {
    console.log(body);
  }
}

/**
 * Seal the current month's file immediately and let the next report start a fresh
 * one. Use when you want a clean batch boundary without waiting for the month to
 * roll over — reading never required this, but closing a batch sometimes does.
 */
async function cmdRotate() {
  const now = new Date();
  const current = `reports-${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}.jsonl`;
  const stamp = now.toISOString().replace(/[-:]/g, "").replace(/\..+/, "Z");
  const sealed = `${current.replace(/\.jsonl$/, "")}.sealed-${stamp}.jsonl`;
  try {
    await rename(path.join(REPORT_DIR, current), path.join(REPORT_DIR, sealed));
    console.log(`Sealed ${current} -> ${sealed}`);
    console.log("The next report starts a new file automatically.");
  } catch (error) {
    if (error.code === "ENOENT") {
      console.log(`Nothing to rotate: ${current} does not exist yet.`);
      return;
    }
    throw error;
  }
}

/**
 * Delete report files whose month is older than the retention window.
 *
 * Retention is 6 MONTHS (decided 2026-09-10). These files are not ordinary logs: each
 * line carries a named user's question, up to 3 preceding turns, and in this product a
 * question is routinely "เงินเดือน 80,000 มีลูก 2 คน อายุ 65" — real taxpayers' salary,
 * dependants and ages on a government server. `preceding_turns` is already capped at 3
 * and source excerpts are already dropped; a retention window is the remaining
 * mitigation, and without one these accumulate forever.
 *
 * Six months keeps a chunk-quality complaint actionable long enough to be triaged
 * (given 74% of the corpus is needs_tax_review, these are effectively a review queue)
 * without holding financial details indefinitely. Change RETENTION_MONTHS if the
 * supervisor sets a different policy.
 *
 * Dry by default — it prints what it would delete. Pass --yes to actually delete.
 * Deliberately manual rather than automatic: nothing should silently destroy the only
 * copy of user-reported data on a timer nobody is watching.
 */
const RETENTION_MONTHS = Number(process.env.REPORT_RETENTION_MONTHS || 6);

function fileMonth(name) {
  // reports-YYYY-MM.jsonl, and the sealed variant reports-YYYY-MM.sealed-<stamp>.jsonl
  const match = name.match(/^reports-(\d{4})-(\d{2})\b/);
  if (!match) return null;
  return { year: Number(match[1]), month: Number(match[2]) };
}

async function cmdPurge(flags) {
  const files = await reportFiles();
  if (!files.length) {
    console.log(`No report files in ${REPORT_DIR}.`);
    return;
  }

  const now = new Date();
  // Months since epoch keeps the comparison free of day-of-month and DST edge cases.
  const cutoff = now.getUTCFullYear() * 12 + now.getUTCMonth() - RETENTION_MONTHS;
  const doomed = [];
  for (const file of files) {
    const parsed = fileMonth(file);
    if (!parsed) {
      console.log(`  skip (unrecognised name)  ${file}`);
      continue;
    }
    if (parsed.year * 12 + (parsed.month - 1) < cutoff) doomed.push(file);
  }

  if (!doomed.length) {
    console.log(`Nothing older than ${RETENTION_MONTHS} months. ${files.length} file(s) kept.`);
    return;
  }

  for (const file of doomed) {
    if (flags.yes) {
      await unlink(path.join(REPORT_DIR, file));
      console.log(`  deleted  ${file}`);
    } else {
      console.log(`  would delete  ${file}`);
    }
  }
  console.log(
    flags.yes
      ? `Deleted ${doomed.length} file(s) older than ${RETENTION_MONTHS} months.`
      : `${doomed.length} file(s) older than ${RETENTION_MONTHS} months. Re-run with --yes to delete.`,
  );
}

async function cmdList() {
  const files = await reportFiles();
  if (!files.length) {
    console.log(`No report files in ${REPORT_DIR}.`);
    return;
  }
  for (const file of files) {
    const text = await readFile(path.join(REPORT_DIR, file), "utf8");
    const count = text.split("\n").filter((line) => line.trim()).length;
    console.log(`  ${String(count).padStart(5)}  ${file}`);
  }
}

const { command, flags } = parseArgs(process.argv.slice(2));
const commands = {
  summary: cmdSummary,
  export: cmdExport,
  rotate: cmdRotate,
  list: cmdList,
  purge: cmdPurge,
};

if (!commands[command]) {
  console.error(`Unknown command "${command}". Use: summary | export | rotate | list | purge`);
  process.exit(1);
}

await commands[command](flags);
