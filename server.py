import asyncio
from imghdr import what
import json
import re
from io import BytesIO
from os import getenv, listdir, mkdir, path
from random import SystemRandom
from typing import Optional

import aiofiles
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.responses import RedirectResponse
from PIL import Image, ImageOps


load_dotenv()


CHARS = "ABCDEFGHIJKLMOPQRSTUVWXYZabcdefghijklmopqrstuvwxyz0123456789-_"

ID_REGEX = re.compile(r"([a-zA-Z0-9\-_]{6})(?:\.+?)?")
FILE_REGEX = re.compile(r"([a-zA-Z0-9\-_]{6})\/(.+)\.(.+)")

APP = FastAPI()
NOT_FOUND = HTTPException(404, "Not Found")

TOKEN = getenv("TOKEN")


async def read_data() -> dict[str, dict[str, str]]:
    async with aiofiles.open("data.json", "r") as f:
        return json.loads(await f.read())


async def write_data(data: dict[str, dict[str, str]]) -> None:
    async with aiofiles.open("data.json", "w") as f:
        await f.write(json.dumps(data))


def remove_jpeg_exif(buffer: bytes) -> bytes:
    original = Image.open(buffer)
    ImageOps.exif_transpose(original)

    exifless = Image.new(original.mode, original.size)
    exifless.putdata(list(original.getdata()))

    new_buffer = BytesIO()
    exifless.save(new_buffer)
    new_buffer.seek(0)

    return new_buffer.read()


@APP.get("/", response_class=RedirectResponse)
@APP.get("/upload", response_class=RedirectResponse)
async def index():
    return "https://isaactaylor.xyz"


@APP.post("/upload")
async def upload(
    file: UploadFile = File(...),
    Authorization: str = Header(None),
    content_length: Optional[str] = Header(None),
):
    data: dict[str, dict[str, str]] = await read_data()

    if content_length is None:
        raise HTTPException(411, "Length Required")

    if Authorization != TOKEN:
        raise HTTPException(403, "Forbidden")

    user = data["auth"][Authorization]

    if user != "isaac" and int(content_length) >= 999999999:
        raise HTTPException(413, "Request Entity Too Large")
    
    filename = file.filename

    random = SystemRandom()
    while (file_id := "".join(random.choices(CHARS, k=6))) in data["ids"]:
        file_id = "".join(random.choices(CHARS, k=6))

    data["ids"][file_id] = user
    await write_data(data)

    mkdir(f"./files/{user}/{file_id}")

    async with aiofiles.open(f"./files/{user}/{file_id}/{filename}", "rb") as f:
        if (ext := filename.split(".")[-1].lower()) in ("jpe", "jpeg", "jpg"):
            image = await asyncio.get_running_loop().run_in_executor(
                None,
                remove_jpeg_exif,
                await f.read(),
            )
    async with aiofiles.open(f"./files/{user}/{file_id}/{filename}", "wb") as f:
        if (ext := filename.split(".")[-1].lower()) in ("jpe", "jpeg", "jpg"):
            await f.write(image)
        else:
            while chunk := await file.read(134217728):
                await f.write(chunk)

    return {"ext": ext, "url": f"https://cdn.isaactaylor.xyz/{file_id}"}


@APP.get("/{file:path}")
async def fetch_file(file: str):
    data = await read_data()

    if re.fullmatch(r"[a-zA-Z0-9\-_]{6}(?:\..+)?\/?", file):
        file_id = ID_REGEX.match(file).group(1)
        if file_id not in data["ids"]:
            raise NOT_FOUND

        name = data["ids"][file_id]
        filename = listdir(f"./files/{name}/{file_id}")[0]
        return RedirectResponse(
            f"https://cdn.isaactaylor.xyz/{file_id}/{filename}", 301
        )

    if (match := FILE_REGEX.match(file)) is None:
        raise NOT_FOUND

    file_id, name, ext = match.groups()
    filename = f"{name}.{ext}"

    if ext is None:
        mime = "application/octet-stream"
    else:
        with open("mime.json", "r", encoding="utf-8") as f:
            mime_types: dict = json.load(f)
            mime = mime_types.get(ext.lower(), "application/octet-stream")

    if (user := data["ids"].get(file_id)) is None:
        raise NOT_FOUND

    filepath = f"./files/{user}/{file_id}/{filename}"

    if not path.exists(filepath):
        raise NOT_FOUND

    async with aiofiles.open(filepath, "rb") as f:
        return Response(await f.read(), media_type=mime)
