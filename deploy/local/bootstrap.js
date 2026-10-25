const ALLOW = [
  /^settings\//,
  /^airi-cards$/,
  /^airi-card-module-defaults$/,
  /^memory\//,
  /^recipes\//,
  /^ui\//,
  /^vueuse-color-scheme$/,
]
const DENY = [
  /^__VUE_DEVTOOLS/,
  /^__vue-devtools/,
  /^settings\/stage-ui-three\/skyBoxUrl$/,
  /^settings\/connection\/websocket-url$/,
  /^settings\/connection\/websocket-auth-token$/,
]

function allowed(key) {
  return ALLOW.some(pattern => pattern.test(key)) && !DENY.some(pattern => pattern.test(key))
}

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('localforage', 2)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains('keyvaluepairs'))
        db.createObjectStore('keyvaluepairs')
      if (!db.objectStoreNames.contains('local-forage-detect-blob-support'))
        db.createObjectStore('local-forage-detect-blob-support')
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function idbGet(db, key) {
  return new Promise((resolve, reject) => {
    const request = db.transaction('keyvaluepairs', 'readonly').objectStore('keyvaluepairs').get(key)
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function idbPut(db, key, value) {
  return new Promise((resolve, reject) => {
    const request = db.transaction('keyvaluepairs', 'readwrite').objectStore('keyvaluepairs').put(value, key)
    request.onsuccess = () => resolve()
    request.onerror = () => reject(request.error)
  })
}

function idbKeys(db) {
  return new Promise((resolve, reject) => {
    const request = db.transaction('keyvaluepairs', 'readonly').objectStore('keyvaluepairs').getAllKeys()
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

async function seedModels(models) {
  if (!models?.length)
    return
  const db = await openDb()
  try {
    for (const model of models) {
      const existing = await idbGet(db, model.id)
      if (existing?.file)
        continue
      try {
        const response = await fetch(model.url, { cache: 'no-store' })
        if (!response.ok)
          throw new Error(`HTTP ${response.status}`)
        const blob = await response.blob()
        const name = model.name || `${model.id}.zip`
        const file = new File([blob], name, { type: 'application/zip' })
        await idbPut(db, model.id, {
          id: model.id,
          format: model.format || 'live2d-zip',
          type: 'file',
          file,
          name,
          importedAt: model.updated_at || Date.now(),
        })
        console.log(`[airi-bootstrap] model restored: ${name}`)
      }
      catch (error) {
        console.warn(`[airi-bootstrap] model restore failed: ${model.id}`, error)
      }
    }
  }
  finally {
    db.close()
  }
}

function readSettings() {
  const settings = {}
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (key && allowed(key))
      settings[key] = localStorage.getItem(key)
  }
  return settings
}

let startSync = () => {}

async function syncModelsOnce() {
  try {
    const response = await fetch('/api/models', { cache: 'no-store' })
    if (!response.ok)
      return
    const { models = [] } = await response.json()
    const known = new Set(models.map(model => model.id))
    const db = await openDb()
    try {
      const keys = await idbKeys(db)
      for (const key of keys) {
        if (typeof key !== 'string' || !key.startsWith('display-model-') || known.has(key))
          continue
        const value = await idbGet(db, key)
        if (!value?.file)
          continue
        const headers = {
          'content-type': 'application/zip',
          'x-model-name': encodeURIComponent(value.name || `${key}.zip`),
          'x-model-format': value.format || 'live2d-zip',
        }
        const upload = await fetch(`/api/models/${encodeURIComponent(key)}`, {
          method: 'PUT',
          headers,
          body: value.file,
        })
        if (upload.ok)
          console.log(`[airi-bootstrap] model uploaded: ${value.name || key}`)
        else
          console.warn(`[airi-bootstrap] model upload failed: ${key} HTTP ${upload.status}`)
      }
    }
    finally {
      db.close()
    }
  }
  catch (error) {
    console.warn('[airi-bootstrap] model sync failed', error)
  }
}

function beginSync(initial) {
  let last = JSON.stringify(initial || readSettings())
  let timer
  const push = async () => {
    const settings = readSettings()
    // A wiped profile temporarily looks empty; never let it erase the backend.
    if (Object.keys(settings).length < 20)
      return
    const current = JSON.stringify(settings)
    if (current === last)
      return
    try {
      const response = await fetch('/api/state', {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ settings }),
        keepalive: true,
      })
      if (response.ok)
        last = current
    }
    catch (error) {
      console.warn('[airi-bootstrap] state sync failed', error)
    }
  }
  startSync = () => { void push() }
  timer = setInterval(() => { void push() }, 5000)
  window.addEventListener('pagehide', () => { void push(); clearInterval(timer) })
  window.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden')
      void push()
  })
  setTimeout(() => { void push() }, 1200)
  setTimeout(() => { void syncModelsOnce() }, 12000)
  setInterval(() => { void syncModelsOnce() }, 60000)
}

export async function hydrate() {
  const overlay = document.createElement('div')
  overlay.textContent = '正在从本地后端恢复设置...'
  overlay.style.cssText = 'position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);z-index:2147483647;padding:12px 18px;border-radius:12px;background:rgba(255,255,255,.92);color:#333;font:14px/1.5 system-ui,sans-serif;box-shadow:0 8px 30px rgba(0,0,0,.15)'
  document.documentElement.appendChild(overlay)

  let loaded = null
  try {
    const response = await fetch('/api/state', { cache: 'no-store' })
    if (response.ok) {
      const state = await response.json()
      const settings = state.settings || {}
      if (Object.keys(settings).length) {
        for (const [key, value] of Object.entries(settings)) {
          if (allowed(key) && typeof value === 'string')
            localStorage.setItem(key, value)
        }
        loaded = settings
      }
      await seedModels(state.models || [])
    }
  }
  catch (error) {
    console.warn('[airi-bootstrap] hydrate failed', error)
  }
  finally {
    overlay.remove()
    beginSync(loaded)
  }
}
