"""Local gallery with an optional, one-at-a-time manual LUT audition tool."""
import os
import secrets
import sys
from urllib.parse import unquote
from uuid import uuid4
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
sys.path.insert(0, str(PROJECT))

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool

from backend.app.errors import AppError
from backend.app.preview_gallery import DEFAULT_STORE, list_galleries, read_gallery
from backend.app.single_pass_runtime import runtime_status
from backend.app.manual_lut_preview import ManualApply, ManualPreview
from backend.app.style_gallery import StyleGallery, DEFAULT_STYLE_STORE, MAX_UPLOAD


def create_app(preview_dir=None, manual_enabled=None, style_dir=None):
    store = Path(preview_dir or DEFAULT_STORE).resolve()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    enabled = os.getenv('LUT_MANUAL_PREVIEW', '0') == '1' if manual_enabled is None else manual_enabled
    manual = ManualPreview(store)
    token = secrets.token_urlsafe(32)
    app.state.manual_preview = manual
    styles = StyleGallery(style_dir or DEFAULT_STYLE_STORE, store, manual.lock)
    app.state.style_gallery = styles
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]', 'testserver'])

    @app.middleware('http')
    async def readonly(request: Request, call_next):
        manual_post = enabled and request.method == 'POST' and request.url.path == '/api/manual/apply'
        style_post = request.method == 'POST' and request.url.path == '/api/styles/apply'
        if manual_post or style_post:
            origin = request.headers.get('origin')
            if (origin and origin != str(request.base_url).rstrip('/')) or not secrets.compare_digest(request.headers.get('x-lut-preview-token', ''), token):
                return JSONResponse({'detail': '请从当前预览页发起操作，或刷新页面后重试。'}, status_code=403)
            if style_post:
                try:
                    length = int(request.headers.get('content-length', '0'))
                except ValueError:
                    return JSONResponse({'detail': '上传长度无效。'}, status_code=400)
                if length < 0 or length > MAX_UPLOAD:
                    return JSONResponse({'detail': '每张照片不能超过 10 MB。'}, status_code=413)
        elif request.method not in ('GET', 'HEAD'):
            return JSONResponse({'detail': '此页面仅展示调色结果，任务由 Codex 提交。'}, status_code=405,
                                headers={'Allow': 'GET, HEAD'})
        response = await call_next(request)
        immutable_sample = request.method in ('GET', 'HEAD') and request.url.path.startswith('/api/styles/') and '/files/' in request.url.path and response.status_code == 200
        response.headers['Cache-Control'] = 'private, max-age=31536000, immutable' if immutable_sample else 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        return response

    @app.exception_handler(AppError)
    async def app_error(_request, error):
        return JSONResponse({'detail': error.message}, status_code=error.status)

    def gallery(run_id=None):
        try:
            return read_gallery(store, run_id)
        except (ValueError, ValidationError, OSError):
            raise HTTPException(503, '暂时无法读取预览结果。') from None

    def public(value):
        if value is None:
            return {'status': 'waiting', 'gallery': None}
        photos = []
        for item in value.photos:
            photos.append({k: v for k, v in item.model_dump().items() if k not in ('original_file', 'result_file')})
            prefix = f'api/previews/{value.id}/files/'
            photos[-1].update(original_url=prefix+item.original_file, result_url=prefix+item.result_file)
        return {'status': 'ready', 'gallery': {'id': value.id, 'created_at': value.created_at, 'photos': photos}}

    @app.get('/api/health')
    async def health():
        return {**runtime_status(), 'mode': 'preview-with-manual-lut' if enabled else 'style-gallery', 'manual_enabled': bool(enabled)}

    @app.get('/api/styles')
    def style_list():
        try:
            return {**styles.public(), 'token': token}
        except (OSError, ValueError, KeyError):
            raise HTTPException(503, '风格预览暂时无法读取，请稍后重试。') from None

    @app.get('/api/styles/{build_id}/files/{filename}')
    def style_file(build_id: str, filename: str):
        try:
            return FileResponse(styles.asset(build_id, filename))
        except (OSError, ValueError, KeyError):
            raise HTTPException(404, '预览图片不存在。') from None

    @app.post('/api/styles/apply')
    async def apply_style(request: Request, build_id: str = Query(pattern=r'^[a-f0-9]{32}$'),
                          lut_id: str = Query(pattern=r'^[a-z0-9-]{1,100}$'), strength: float = Query(gt=0, le=1)):
        # Validate the choice before accepting or decoding photo content.
        try:
            styles.selected(build_id, lut_id, strength)
        except (OSError, ValueError, KeyError):
            raise HTTPException(503, '所选风格暂时不可用，请刷新页面。') from None
        uploads = styles.store / 'uploads'
        uploads.mkdir(parents=True, exist_ok=True)
        source = uploads / (uuid4().hex+'.bin')
        count = 0
        try:
            with source.open('xb') as output:
                async for chunk in request.stream():
                    count += len(chunk)
                    if count > MAX_UPLOAD:
                        raise HTTPException(413, '每张照片不能超过 10 MB。')
                    output.write(chunk)
            if not count:
                raise HTTPException(422, '请选择一张 JPEG 或 PNG 照片。')
            name = unquote(request.headers.get('x-photo-name', '我的照片'))[:200]
            return await run_in_threadpool(styles.apply, source, build_id, lut_id, strength, name)
        finally:
            source.unlink(missing_ok=True)

    @app.get('/api/manual/luts')
    def manual_luts(source_run_id: str | None = None, photo_id: str | None = None):
        if not enabled:
            return {'enabled': False, 'items': [], 'count': 0}
        if bool(source_run_id) != bool(photo_id):
            raise HTTPException(422, '请同时指定当前批次和照片。')
        return {'enabled': True, 'token': token, **manual.options(source_run_id, photo_id)}

    @app.post('/api/manual/apply')
    def manual_apply(value: ManualApply):
        result = manual.apply(value)
        return {**result, 'status': 'completed', 'gallery': public(gallery(result['run_id']))['gallery']}

    @app.get('/api/preview')
    async def current_preview():
        return public(gallery())

    @app.get('/api/history')
    async def history(limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0)):
        try:
            records = list_galleries(store, limit, offset)
        except OSError:
            raise HTTPException(503, '暂时无法读取历史记录。') from None
        items = []
        for value in records.pop('galleries'):
            items.append({'id': value.id, 'created_at': value.created_at, 'photo_count': len(value.photos),
                          'names': [p.name for p in value.photos],
                          'lut_names': list(dict.fromkeys(p.lut_name for p in value.photos)),
                          'cover_url': f'api/previews/{value.id}/files/{value.photos[0].result_file}',
                          'url': f'?run={value.id}'})
        return {**records, 'items': items}

    @app.get('/api/previews/{run_id}')
    async def specific_preview(run_id: str):
        return public(gallery(run_id))

    @app.get('/api/previews/{run_id}/files/{filename}')
    async def preview_image(run_id: str, filename: str):
        value = gallery(run_id)
        allowed = {name for item in value.photos for name in (item.original_file, item.result_file)}
        if filename not in allowed:
            raise HTTPException(404, '预览图片不存在。')
        directory = (store / 'runs' / run_id).resolve() / 'files'
        file = (directory / filename).resolve()
        if file.parent != directory or not file.is_file():
            raise HTTPException(404, '预览图片不存在。')
        return FileResponse(file)

    @app.get('/')
    async def index(request: Request):
        return FileResponse(HERE / ('index.html' if 'run' in request.query_params else 'gallery.html'))

    @app.get('/results')
    async def results():
        return FileResponse(HERE / 'index.html')

    @app.get('/gallery.js')
    async def gallery_javascript():
        return FileResponse(HERE / 'gallery.js', media_type='text/javascript')

    @app.get('/gallery.css')
    async def gallery_stylesheet():
        return FileResponse(HERE / 'gallery.css', media_type='text/css')

    @app.get('/app.js')
    async def javascript():
        return FileResponse(HERE / 'app.js', media_type='text/javascript')

    @app.get('/styles.css')
    async def stylesheet():
        return FileResponse(HERE / 'styles.css', media_type='text/css')

    app.mount('/assets', StaticFiles(directory=HERE / 'assets'), name='assets')
    return app


if __name__ == '__main__':
    uvicorn.run(create_app(), host='127.0.0.1', port=int(os.getenv('LUT_PROTOTYPE_PORT', '4175')), workers=1)
