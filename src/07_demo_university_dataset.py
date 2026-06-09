import argparse
import json
import random
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data" / "processed" / "university_v02"
CONV_DIR = DATA_ROOT / "conversation"
TRAINING_DIR = DATA_ROOT / "training"
DB_PATH = DATA_ROOT / "database" / "university_registration.sqlite"
REPORT_PATH = DATA_ROOT / "report_v02.json"

SPLITS = ["train", "dev", "test"]


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_conversations(split):
    path = CONV_DIR / f"university_multi_turn_{split}_v02.json"
    return load_json(path)


def load_training(split):
    path = TRAINING_DIR / f"university_train_format_{split}_v02.json"
    return load_json(path)


def one_line(text):
    return re.sub(r"\s+", " ", text).strip()


def query_sql(sql, limit=20):
    wrapped_sql = f"SELECT * FROM ({sql}) AS generated_query LIMIT ?"
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(wrapped_sql, (limit,)).fetchall()
        return {
            "columns": rows[0].keys() if rows else [],
            "rows": [dict(row) for row in rows],
            "row_count_preview": len(rows),
        }
    finally:
        conn.close()


def find_training_item(split, conversation_id, turn_id):
    target_id = f"{conversation_id}_turn_{turn_id}"
    for item in load_training(split):
        if item["id"] == target_id:
            return item
    return None


def print_conversation(split, index=None):
    conversations = load_conversations(split)
    if index is None:
        index = random.randrange(len(conversations))
    index = max(0, min(index, len(conversations) - 1))
    conv = conversations[index]

    print("=" * 100)
    print(f"Conversation: {conv['conversation_id']} | split={split} | index={index}")
    print(f"Domain: {conv['domain']} | DB: {conv['db_id']}")
    print("=" * 100)
    for item in conv["turns"]:
        print(f"\nTurn {item['turn_id']} | {item['operation']} | tags={', '.join(item['tags'])}")
        print("User:", item["utterance"])
        print("SQL :", item["sql"])
        try:
            result = query_sql(item["sql"], limit=3)
            print(f"Rows preview: {result['row_count_preview']}")
            for row in result["rows"]:
                print("  ", row)
        except Exception as exc:
            print("SQL error:", exc)


def build_html():
    return r"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>University Multi-turn Text-to-SQL v02</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #1c2430;
      --muted: #657080;
      --line: #d9dee6;
      --accent: #0f766e;
      --accent-weak: #d9f4ef;
      --danger: #b42318;
      --mono: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", monospace;
      --sans: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: var(--sans);
      font-size: 14px;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 18px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1 {
      margin: 0;
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0;
    }
    main {
      display: grid;
      grid-template-columns: 280px minmax(0, 1fr);
      min-height: calc(100vh - 58px);
    }
    aside {
      border-right: 1px solid var(--line);
      background: #fbfcfd;
      padding: 14px;
      overflow: auto;
    }
    section {
      min-width: 0;
      padding: 16px;
    }
    label {
      display: block;
      margin: 12px 0 6px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
    }
    select, input, button {
      font: inherit;
    }
    select, input {
      width: 100%;
      height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--ink);
      padding: 0 10px;
    }
    button {
      height: 36px;
      border: 1px solid var(--accent);
      border-radius: 6px;
      background: var(--accent);
      color: white;
      padding: 0 12px;
      cursor: pointer;
      font-weight: 650;
    }
    button.secondary {
      background: #fff;
      color: var(--accent);
    }
    .row {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .row > * { flex: 1; }
    .stats {
      display: grid;
      gap: 8px;
      margin-top: 14px;
    }
    .stat {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 10px;
    }
    .stat strong {
      display: block;
      font-size: 20px;
      line-height: 1.1;
    }
    .stat span {
      color: var(--muted);
      font-size: 12px;
    }
    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      margin-bottom: 14px;
    }
    .title {
      font-size: 18px;
      font-weight: 750;
      margin-bottom: 4px;
    }
    .subtle { color: var(--muted); }
    .turns {
      display: grid;
      gap: 10px;
    }
    .turn {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      overflow: hidden;
    }
    .turn-header {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfd;
    }
    .utterance {
      padding: 12px;
      font-size: 15px;
    }
    .sql {
      margin: 0;
      padding: 12px;
      border-top: 1px solid var(--line);
      background: #17212f;
      color: #eaf1f8;
      overflow: auto;
      font-family: var(--mono);
      font-size: 12px;
      line-height: 1.55;
      white-space: pre-wrap;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      padding: 2px 8px;
      border-radius: 999px;
      background: var(--accent-weak);
      color: #075e57;
      font-size: 12px;
      font-weight: 700;
      white-space: nowrap;
    }
    .tags {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      padding: 0 12px 12px;
    }
    .result {
      border-top: 1px solid var(--line);
      padding: 12px;
      background: #fff;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 7px 8px;
      text-align: left;
      vertical-align: top;
      max-width: 240px;
      overflow-wrap: anywhere;
    }
    th {
      background: #f3f5f7;
      color: #334155;
      font-weight: 700;
    }
    textarea {
      width: 100%;
      min-height: 220px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      font-family: var(--mono);
      font-size: 12px;
      line-height: 1.5;
      background: #fff;
      color: var(--ink);
    }
    .training {
      margin-top: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 12px;
    }
    .error {
      color: var(--danger);
      font-weight: 700;
    }
    @media (max-width: 860px) {
      main { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      .topbar { flex-direction: column; }
    }
  </style>
</head>
<body>
  <header>
    <h1>University Multi-turn Text-to-SQL v02</h1>
    <button id="randomBtn">Random conversation</button>
  </header>
  <main>
    <aside>
      <label for="split">Split</label>
      <select id="split">
        <option value="train">train</option>
        <option value="dev">dev</option>
        <option value="test">test</option>
      </select>

      <label for="index">Conversation index</label>
      <div class="row">
        <input id="index" type="number" min="0" value="0">
        <button class="secondary" id="loadBtn">Load</button>
      </div>

      <div class="stats" id="stats"></div>
    </aside>

    <section>
      <div class="topbar">
        <div>
          <div class="title" id="convTitle">Loading...</div>
          <div class="subtle" id="convMeta"></div>
        </div>
      </div>

      <div class="turns" id="turns"></div>

      <div class="training">
        <div class="title">Training sample for selected turn</div>
        <label for="trainingInput">Input</label>
        <textarea id="trainingInput" readonly></textarea>
        <label for="trainingOutput">Output SQL</label>
        <textarea id="trainingOutput" readonly></textarea>
      </div>
    </section>
  </main>

  <script>
    const splitEl = document.getElementById('split');
    const indexEl = document.getElementById('index');
    const statsEl = document.getElementById('stats');
    const titleEl = document.getElementById('convTitle');
    const metaEl = document.getElementById('convMeta');
    const turnsEl = document.getElementById('turns');
    const trainingInputEl = document.getElementById('trainingInput');
    const trainingOutputEl = document.getElementById('trainingOutput');

    let report = null;
    let currentConv = null;

    async function api(path) {
      const response = await fetch(path);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || response.statusText);
      return data;
    }

    function esc(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;'
      }[ch]));
    }

    function renderStats() {
      if (!report) return;
      const split = splitEl.value;
      const s = report.splits[split];
      statsEl.innerHTML = `
        <div class="stat"><strong>${report.total_conversations}</strong><span>total conversations</span></div>
        <div class="stat"><strong>${report.total_turns}</strong><span>total turns</span></div>
        <div class="stat"><strong>${s.conversations}</strong><span>${split} conversations</span></div>
        <div class="stat"><strong>${s.turns}</strong><span>${split} turns</span></div>
        <div class="stat"><strong>${report.sql_feature_counts.join}</strong><span>JOIN turns</span></div>
        <div class="stat"><strong>${report.sql_feature_counts.group_by}</strong><span>GROUP BY turns</span></div>
        <div class="stat"><strong>${report.sql_feature_counts.having}</strong><span>HAVING turns</span></div>
      `;
      indexEl.max = Math.max(0, s.conversations - 1);
    }

    async function loadConversation(random = false) {
      renderStats();
      const split = splitEl.value;
      let index = Number(indexEl.value || 0);
      if (random && report) {
        index = Math.floor(Math.random() * report.splits[split].conversations);
        indexEl.value = index;
      }
      currentConv = await api(`/api/conversation?split=${split}&index=${index}`);
      titleEl.textContent = currentConv.conversation_id;
      metaEl.textContent = `${currentConv.domain} | ${currentConv.db_id} | ${currentConv.turns.length} turns`;
      renderTurns();
      await showTraining(currentConv.turns[0].turn_id);
    }

    async function showTraining(turnId) {
      if (!currentConv) return;
      const split = splitEl.value;
      const item = await api(`/api/training?split=${split}&conversation_id=${encodeURIComponent(currentConv.conversation_id)}&turn_id=${turnId}`);
      trainingInputEl.value = item.input;
      trainingOutputEl.value = item.output;
    }

    async function runTurn(turnId, button) {
      const turn = currentConv.turns.find(item => item.turn_id === turnId);
      const resultEl = document.getElementById(`result-${turnId}`);
      button.disabled = true;
      resultEl.innerHTML = 'Running...';
      try {
        const result = await api(`/api/execute?sql=${encodeURIComponent(turn.sql)}&limit=10`);
        if (!result.rows.length) {
          resultEl.innerHTML = '<span class="subtle">Query executed successfully, but returned no rows.</span>';
        } else {
          const headers = result.columns.map(col => `<th>${esc(col)}</th>`).join('');
          const rows = result.rows.map(row => `<tr>${result.columns.map(col => `<td>${esc(row[col])}</td>`).join('')}</tr>`).join('');
          resultEl.innerHTML = `<table><thead><tr>${headers}</tr></thead><tbody>${rows}</tbody></table>`;
        }
      } catch (err) {
        resultEl.innerHTML = `<span class="error">${esc(err.message)}</span>`;
      } finally {
        button.disabled = false;
      }
    }

    function renderTurns() {
      turnsEl.innerHTML = currentConv.turns.map(turn => `
        <article class="turn">
          <div class="turn-header">
            <div><strong>Turn ${turn.turn_id}</strong> <span class="pill">${esc(turn.operation)}</span></div>
            <div class="row" style="flex: 0 0 auto;">
              <button class="secondary" onclick="showTraining(${turn.turn_id})">Training</button>
              <button onclick="runTurn(${turn.turn_id}, this)">Run SQL</button>
            </div>
          </div>
          <div class="utterance">${esc(turn.utterance)}</div>
          <div class="tags">${turn.tags.map(tag => `<span class="pill">${esc(tag)}</span>`).join('')}</div>
          <pre class="sql">${esc(turn.sql)}</pre>
          <div class="result" id="result-${turn.turn_id}"><span class="subtle">Run SQL to preview rows.</span></div>
        </article>
      `).join('');
    }

    async function init() {
      report = await api('/api/report');
      renderStats();
      await loadConversation(false);
    }

    document.getElementById('loadBtn').addEventListener('click', () => loadConversation(false));
    document.getElementById('randomBtn').addEventListener('click', () => loadConversation(true));
    splitEl.addEventListener('change', () => {
      indexEl.value = 0;
      loadConversation(false);
    });

    init().catch(err => {
      titleEl.textContent = 'Failed to load demo';
      metaEl.innerHTML = `<span class="error">${esc(err.message)}</span>`;
    });
  </script>
</body>
</html>
"""


class DemoHandler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self):
        body = build_html().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            if parsed.path == "/":
                self.send_html()
            elif parsed.path == "/api/report":
                self.send_json(load_json(REPORT_PATH))
            elif parsed.path == "/api/conversation":
                split = qs.get("split", ["train"])[0]
                index = int(qs.get("index", [0])[0])
                if split not in SPLITS:
                    raise ValueError(f"Unknown split: {split}")
                conversations = load_conversations(split)
                index = max(0, min(index, len(conversations) - 1))
                self.send_json(conversations[index])
            elif parsed.path == "/api/training":
                split = qs.get("split", ["train"])[0]
                conversation_id = qs.get("conversation_id", [""])[0]
                turn_id = int(qs.get("turn_id", [1])[0])
                item = find_training_item(split, conversation_id, turn_id)
                if not item:
                    self.send_json({"error": "Training item not found"}, status=404)
                    return
                self.send_json(item)
            elif parsed.path == "/api/execute":
                sql = qs.get("sql", [""])[0]
                limit = int(qs.get("limit", [10])[0])
                self.send_json(query_sql(sql, max(1, min(limit, 50))))
            else:
                self.send_json({"error": "Not found"}, status=404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def log_message(self, format, *args):
        return


def serve(host, port):
    server = ThreadingHTTPServer((host, port), DemoHandler)
    print(f"Demo server: http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="Demo viewer for university multi-turn Text-to-SQL v02.")
    parser.add_argument("--split", choices=SPLITS, default="train")
    parser.add_argument("--index", type=int, default=None)
    parser.add_argument("--web", action="store_true", help="Start a local web demo.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if not REPORT_PATH.exists():
        raise SystemExit("Missing v02 dataset. Run: python src/06_generate_university_multiturn_v02.py")

    if args.web:
        serve(args.host, args.port)
    else:
        print_conversation(args.split, args.index)


if __name__ == "__main__":
    main()
