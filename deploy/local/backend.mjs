import { createServer } from 'node:http'
import { createReadStream } from 'node:fs'
import { mkdir, rm, stat, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { randomUUID } from 'node:crypto'
import { Readable } from 'node:stream'

const PORT = Number(process.env.PORT ?? 8789)
const DATA_DIR = process.env.DATA_DIR ?? '/data'
const MODEL_DIR = join(DATA_DIR, 'models')
const TARGET = (process.env.OPENCODE_TARGET ?? 'https://opencode.ai/inference/go/v1').replace(/\/$/, '')
const SESSION = process.env.OPENCODE_SESSION ?? `airi-${randomUUID()}`

await mkdir(MODEL_DIR, { recursive: true })

const db = new DatabaseSync(join(DATA_DIR, 'airi.db'))
db.exec(`
  CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    json TEXT NOT NULL,
    updated_at INTEGER NOT NULL
  );
  CREATE TABLE IF NOT EXISTS settings_history (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    json TEXT NOT NULL,
    updated_at INTEGER NOT NULL
  );
  CREATE TABLE IF NOT EXISTS models (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    format TEXT NOT NULL,
    file TEXT NOT NULL,
    updated_at INTEGER NOT NULL
  );
`)

const CORS = {
  'access-control-allow-origin': '*',
  'access-control-allow-methods': 'GET, PUT, POST, DELETE, OPTIONS',
  'access-control-allow-headers': 'Content-Type, Authorization, X-Model-Name, X-Model-Format, X-Opencode-Session, X-Api-Key',
  'access-control-max-age': '86400',
}

function json(res, status, value) {
  if (res.writableEnded) return
  res.writeHead(status, { ...CORS, 'content-type': 'application/json; charset=utf-8' })
  res.end(JSON.stringify(value))
}

async function body(req, limit = 5 * 1024 * 1024) {
  const chunks = []
  let size = 0
  for await (const chunk of req) {
    size += chunk.length
    if (size > limit) throw new Error('request body too large')
    chunks.push(chunk)
  }
  return Buffer.concat(chunks)
}

function modelId(url) {
  const match = url.match(/^\/api\/models\/([^/]+)(?:\/file)?$/)
  if (!match) return null
  const id = decodeURIComponent(match[1])
  return /^[A-Za-z0-9_-]{1,128}$/.test(id) ? id : null
}

function listModels() {
  return db.prepare('SELECT id, name, format, updated_at FROM models ORDER BY updated_at DESC').all()
    .map(model => ({ ...model, url: `/api/models/${encodeURIComponent(model.id)}/file` }))
}

function readState() {
  const row = db.prepare('SELECT json, updated_at FROM settings WHERE id = 1').get()
  return {
    settings: row ? JSON.parse(row.json) : {},
    updated_at: row?.updated_at ?? null,
    models: listModels(),
  }
}

const server = createServer(async (req, res) => {
  if (req.method === 'OPTIONS') {
    res.writeHead(204, CORS)
    res.end()
    return
  }

  const url = new URL(req.url, 'http://localhost')

  try {
    if (url.pathname === '/health') {
      json(res, 200, { ok: true, target: TARGET, models: listModels().length })
      return
    }

    if (url.pathname === '/api/state' && req.method === 'GET') {
      json(res, 200, readState())
      return
    }

    if (url.pathname === '/api/state' && (req.method === 'PUT' || req.method === 'POST')) {
      const payload = JSON.parse((await body(req)).toString('utf8'))
      const settings = payload?.settings ?? payload
      if (!settings || typeof settings !== 'object' || Array.isArray(settings)) {
        json(res, 400, { error: 'settings must be an object' })
        return
      }
      const now = Date.now()
      const row = db.prepare('SELECT json, updated_at FROM settings WHERE id = 1').get()
      const existing = row ? JSON.parse(row.json) : {}
      const merged = { ...existing, ...settings }
      if (row) {
        db.prepare(`
          INSERT INTO settings_history (id, json, updated_at) VALUES (1, ?, ?)
          ON CONFLICT(id) DO UPDATE SET json = excluded.json, updated_at = excluded.updated_at
        `).run(row.json, row.updated_at)
      }
      db.prepare(`
        INSERT INTO settings (id, json, updated_at) VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET json = excluded.json, updated_at = excluded.updated_at
      `).run(JSON.stringify(merged), now)
      json(res, 200, { ok: true, updated_at: now, keys: Object.keys(merged).length })
      return
    }

    if (url.pathname === '/api/state/restore' && req.method === 'POST') {
      const backup = db.prepare('SELECT json, updated_at FROM settings_history WHERE id = 1').get()
      if (!backup) {
        json(res, 404, { error: 'no backup' })
        return
      }
      const now = Date.now()
      db.prepare(`
        INSERT INTO settings (id, json, updated_at) VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET json = excluded.json, updated_at = excluded.updated_at
      `).run(backup.json, now)
      json(res, 200, { ok: true, restored_from: backup.updated_at, updated_at: now })
      return
    }

    if (url.pathname === '/api/models' && req.method === 'GET') {
      json(res, 200, { models: listModels() })
      return
    }

    const id = modelId(url.pathname)
    if (id && url.pathname.endsWith('/file') && req.method === 'GET') {
      const row = db.prepare('SELECT file FROM models WHERE id = ?').get(id)
      if (!row) {
        json(res, 404, { error: 'model not found' })
        return
      }
      const path = join(MODEL_DIR, row.file)
      const info = await stat(path)
      res.writeHead(200, {
        ...CORS,
        'content-type': 'application/zip',
        'content-length': info.size,
      })
      createReadStream(path).pipe(res)
      return
    }

    if (id && req.method === 'PUT') {
      const bytes = await body(req, 200 * 1024 * 1024)
      const name = decodeURIComponent(req.headers['x-model-name'] ?? `${id}.zip`)
      const format = String(req.headers['x-model-format'] ?? 'live2d-zip')
      const file = `${id}.zip`
      await writeFile(join(MODEL_DIR, file), bytes)
      const now = Date.now()
      db.prepare(`
        INSERT INTO models (id, name, format, file, updated_at) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET name = excluded.name, format = excluded.format, file = excluded.file, updated_at = excluded.updated_at
      `).run(id, name, format, file, now)
      json(res, 200, { ok: true, id, name, format, bytes: bytes.length, updated_at: now })
      return
    }

    if (id && req.method === 'DELETE') {
      const row = db.prepare('SELECT file FROM models WHERE id = ?').get(id)
      if (row) {
        await rm(join(MODEL_DIR, row.file), { force: true })
        db.prepare('DELETE FROM models WHERE id = ?').run(id)
      }
      json(res, 200, { ok: true })
      return
    }

    if (url.pathname.startsWith('/v1/')) {
      const target = `${TARGET}${url.pathname.replace(/^\/v1/, '')}${url.search}`
      const headers = {}
      for (const name of ['authorization', 'content-type', 'accept', 'x-api-key', 'x-opencode-session', 'x-opencode-org-id']) {
        const value = req.headers[name]
        if (value) headers[name] = Array.isArray(value) ? value.join(', ') : value
      }
      headers['x-opencode-session'] ??= SESSION
      headers['user-agent'] = 'airi-docker/1.0'

      let payload
      if (req.method !== 'GET' && req.method !== 'HEAD') payload = await body(req, 50 * 1024 * 1024)

      const upstream = await fetch(target, { method: req.method, headers, body: payload, redirect: 'follow' })
      const responseHeaders = { ...CORS }
      for (const name of ['content-type', 'cache-control', 'x-request-id', 'openai-processing-ms']) {
        const value = upstream.headers.get(name)
        if (value) responseHeaders[name] = value
      }
      res.writeHead(upstream.status, responseHeaders)
      if (!upstream.body) {
        res.end()
        return
      }
      Readable.fromWeb(upstream.body).on('error', error => res.destroy(error)).pipe(res)
      console.log(`[proxy] ${req.method} ${url.pathname} -> ${upstream.status}`)
      return
    }

    json(res, 404, { error: 'not found' })
  } catch (error) {
    console.error('[backend]', error)
    json(res, 500, { error: error.message })
  }
})

server.listen(PORT, '0.0.0.0', () => {
  console.log(`AIRI local backend: http://0.0.0.0:${PORT}`)
  console.log(`OpenCode target: ${TARGET}`)
  console.log(`Data dir: ${DATA_DIR}`)
})
