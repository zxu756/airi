import asyncio
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import edge_tts

DEFAULT_VOICE = os.environ.get('EDGE_TTS_VOICE', 'zh-CN-XiaoxiaoNeural')
PORT = int(os.environ.get('PORT', '8790'))


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')

    def json(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        if self.path.rstrip('/') == '/health':
            self.json(200, {'ok': True, 'voice': DEFAULT_VOICE})
            return
        if self.path.rstrip('/') == '/v1/models':
            self.json(200, {
                'object': 'list',
                'data': [{'id': 'tts-1', 'object': 'model', 'owned_by': 'edge-tts'}],
            })
            return
        self.json(404, {'error': 'not found'})

    def do_POST(self):
        if self.path.rstrip('/') != '/v1/audio/speech':
            self.json(404, {'error': 'not found'})
            return

        try:
            length = int(self.headers.get('Content-Length', '0'))
            payload = json.loads(self.rfile.read(length) or b'{}')
            text = (payload.get('input') or payload.get('text') or '').strip()
            voice = payload.get('voice') or DEFAULT_VOICE
            if not text:
                self.json(400, {'error': 'input is required'})
                return

            audio = asyncio.run(synthesize(text, voice))
            self.send_response(200)
            self.cors()
            self.send_header('Content-Type', 'audio/mpeg')
            self.send_header('Content-Length', str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)
        except Exception as error:
            self.json(500, {'error': str(error)})

    def log_message(self, fmt, *args):
        print('[tts] ' + (fmt % args), flush=True)


async def synthesize(text, voice):
    communicate = edge_tts.Communicate(text, voice)
    chunks = []
    async for chunk in communicate.stream():
        if chunk['type'] == 'audio':
            chunks.append(chunk['data'])
    if not chunks:
        raise RuntimeError('edge-tts returned no audio')
    return b''.join(chunks)


if __name__ == '__main__':
    server = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    print(f'Edge TTS bridge on http://0.0.0.0:{PORT} voice={DEFAULT_VOICE}', flush=True)
    server.serve_forever()
