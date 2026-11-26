"""Official Topaz Video API. Quote first, then upload and render on approval."""

import json
import math
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

from engine import Cancelled, check_cancel, probe

BASE = "https://api.topazlabs.com/video"
PART_SIZE = 500_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def https_request(url, method="GET", headers=None, data=None):
    if urlsplit(url).scheme != "https":
        raise RuntimeError("Topaz returned a transfer address without HTTPS.")
    try:
        return build_opener(NoRedirect()).open(
            Request(url, data=data, headers=headers or {}, method=method), timeout=45
        )
    except HTTPError as error:
        code = error.code
        error.close()
        if code in (401, 403):
            raise RuntimeError(f"Topaz access was denied (HTTP {code}). Check the key and API credits.") from None
        raise RuntimeError(f"Topaz request failed (HTTP {code}).") from None
    except (URLError, TimeoutError):
        raise RuntimeError("Could not reach Topaz. Check your network connection.") from None


class TopazVideo:
    def __init__(self, api_key):
        self.headers = {"X-API-Key": api_key, "Accept": "application/json"}

    def api(self, method, route, body=None):
        headers = self.headers.copy()
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        with https_request(BASE + route, method, headers, data) as response:
            payload = response.read()
        return json.loads(payload) if payload else {}

    def quote(self, source, info, size):
        width, height, rate, duration, _, frame_count = info
        if duration <= 0:
            raise ValueError("Topaz Cloud requires a video with a known duration.")
        byte_count = source.stat().st_size
        if not 0 < byte_count < 100_000_000_000:
            raise ValueError("Topaz Cloud accepts source files below 100 GB.")
        response = self.api("POST", "/", {
            "source": {"resolution": {"width": width, "height": height},
                       "size": byte_count, "container": source.suffix.lower()[1:],
                       "duration": duration, "frameRate": float(rate),
                       "frameCount": frame_count or max(1, round(duration * rate))},
            "output": {"resolution": {"width": size[0], "height": size[1]},
                       "container": "mp4", "videoEncoder": "H265", "videoProfile": "Main",
                       "audioTransfer": "Copy", "audioCodec": "AAC",
                       "frameRate": float(rate), "dynamicCompressionLevel": "High"},
            "filters": [{"model": "prob-4", "auto": "Auto"}],
        })
        costs = response["estimates"]["cost"]
        if len(costs) != 2 or any(not isinstance(cost, int) or cost < 0 for cost in costs):
            raise RuntimeError("Topaz did not return a usable credit estimate.")
        return str(UUID(response["requestId"])), tuple(costs), byte_count

    def render(self, quote, source, target, cancel, progress, expected_size):
        request_id, _, byte_count = quote
        route = f"/{request_id}"
        reserved = remote_done = False
        try:
            check_cancel(cancel)
            if source.stat().st_size != byte_count:
                raise RuntimeError("Source size changed. Request a new quote.")
            reserved = True
            accepted = self.api("PATCH", route + "/accept")
            urls = accepted["urls"]
            if not urls:
                raise RuntimeError("Topaz returned no upload URL.")
            part_size = byte_count if len(urls) == 1 else max(
                PART_SIZE, math.ceil(byte_count / len(urls)))
            results = []
            sent = 0
            with source.open("rb") as media:
                for index, url in enumerate(urls, 1):
                    check_cancel(cancel)
                    size = min(part_size, byte_count - sent)
                    if size <= 0:
                        raise RuntimeError("Topaz returned unexpected upload parts.")

                    def chunks():
                        nonlocal sent
                        remaining = size
                        while remaining:
                            check_cancel(cancel)
                            data = media.read(min(1_048_576, remaining))
                            if not data:
                                raise RuntimeError("The input file changed during upload.")
                            sent += len(data)
                            remaining -= len(data)
                            progress(0.35 * sent / byte_count, "Uploading source to Topaz")
                            yield data

                    headers = {"Content-Length": str(size)}
                    if source.suffix.lower() == ".mp4":
                        headers["Content-Type"] = "video/mp4"
                    with https_request(url, "PUT", headers, chunks()) as upload:
                        etag = upload.headers.get("ETag")
                    if len(urls) > 1 and not etag:
                        raise RuntimeError("Topaz upload did not return a part identifier.")
                    results.append({"partNum": index, "eTag": etag or "unused"})
            if sent != byte_count:
                raise RuntimeError("The upload did not cover the whole video.")
            check_cancel(cancel)
            self.api("PATCH", route + "/complete-upload/", {"uploadResults": results})
            deadline = time.monotonic() + 24 * 3600
            while time.monotonic() < deadline:
                check_cancel(cancel)
                try:
                    result = self.api("GET", route + "/status")
                except (RuntimeError, TimeoutError) as error:
                    if cancel.wait(5):
                        raise Cancelled() from error
                    # Do not submit another render to recover from a status outage.
                    result = self.api("GET", route + "/status")
                state = str(result.get("status", "")).lower()
                if state == "complete":
                    remote_done = True
                    break
                if state in {"failed", "canceled", "cancelled"}:
                    remote_done = True
                    raise RuntimeError(f"Topaz reported that the render {state}.")
                progress(0.45, f"Topaz render: {state or 'waiting'}")
                cancel.wait(5)
            else:
                raise RuntimeError("Polling timed out. Check the request in your Topaz account.")
            progress(0.9, "Receiving upscale from Topaz")
            with https_request(result["download"]["url"]) as response, Path(target).open("wb") as output:
                while chunk := response.read(1_048_576):
                    check_cancel(cancel)
                    output.write(chunk)
            if probe(target)[:2] != expected_size:
                raise RuntimeError("Topaz returned different dimensions from the requested output.")
        except Exception as failure:
            if reserved and not remote_done:
                try:
                    self.api("DELETE", route)
                except Exception:
                    raise RuntimeError(
                        f"{failure or 'Stopped locally.'} Topaz cancellation was not confirmed. "
                        f"Check request {request_id} in your Topaz account."
                    ) from None
            if reserved and not isinstance(failure, Cancelled):
                raise RuntimeError(f"{failure} Topaz request {request_id}.") from None
            raise
