import asyncio
import io

import aiohttp
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError

app = FastAPI(title="Image to RGBA PNG converter")

MAX_BYTES = 20 * 1024 * 1024  # 20 MB safety cap
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=15)


def _convert_to_rgba_png(data: bytes) -> bytes:
    """Blocking Pillow work, runs in a thread so the event loop stays free."""
    with Image.open(io.BytesIO(data)) as img:
        rgba = img.convert("RGBA")
        buf = io.BytesIO()
        rgba.save(buf, format="PNG")
        return buf.getvalue()


@app.get("/")
async def convert(url: str = Query(..., description="URL of the image to convert")):
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url must start with http:// or https://")

    try:
        async with aiohttp.ClientSession(timeout=FETCH_TIMEOUT) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Upstream returned status {resp.status}",
                    )
                if resp.content_length and resp.content_length > MAX_BYTES:
                    raise HTTPException(status_code=413, detail="Image too large")
                data = await resp.read()
    except aiohttp.ClientError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch image: {exc}") from exc
    except asyncio.TimeoutError as exc:
        raise HTTPException(status_code=504, detail="Timed out fetching image") from exc

    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image too large")

    try:
        png_bytes = await asyncio.to_thread(_convert_to_rgba_png, data)
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=422, detail="URL did not point to a readable image") from exc

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": 'inline; filename="converted.png"'},
    )


async def main():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
