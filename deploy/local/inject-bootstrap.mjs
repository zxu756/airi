import { copyFile, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const dist = resolve('apps/stage-web/dist')
const htmlPath = resolve(dist, 'index.html')
const bootstrapPath = resolve(dist, 'airi-bootstrap.js')

const html = await readFile(htmlPath, 'utf8')
const scriptPattern = /<script\b[^>]*\btype="module"[^>]*\bsrc="([^"]+)"[^>]*><\/script>/g
const sources = []
for (const match of html.matchAll(scriptPattern))
  sources.push(match[1])

if (!sources.length)
  throw new Error('No external module entry found in apps/stage-web/dist/index.html')

const withoutApp = html.replace(scriptPattern, '')
const imports = sources
  .map(source => `import(${JSON.stringify(source)}).catch(error => console.error('[airi] app load failed', error));`)
  .join('\n      ')
const loader = `<script type="module">
  import('/airi-bootstrap.js')
    .then(module => module.hydrate())
    .catch(error => console.error('[airi] bootstrap failed', error))
    .finally(() => {
      ${imports}
    });
</script>`

await writeFile(htmlPath, withoutApp.replace('</body>', `${loader}\n</body>`), 'utf8')
await copyFile(resolve('deploy/local/bootstrap.js'), bootstrapPath)
console.log(`[inject] app entries: ${sources.length}`)
console.log(`[inject] bootstrap: ${bootstrapPath}`)
