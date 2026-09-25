import asyncio
import threading
from typing import AsyncIterator, Any
from camoufox.pkgman import CamoufoxFetcher, list_available_versions, webdl, CamoufoxNotInstalled

class CustomCamoufoxFetcher(CamoufoxFetcher):
    progress_callback = None
    
    @staticmethod
    def download_file(file, url):
        return webdl(url, buffer=file, bar=False, progress_callback=CustomCamoufoxFetcher.progress_callback)

async def stream_download_camoufox(version: str) -> AsyncIterator[dict[str, Any]]:
    yield {
        "stage": "connecting",
        "message": f"正在解析 Camoufox {version}...",
        "percent": 0,
        "downloaded_bytes": 0,
        "total_bytes": 0,
    }
    
    # 1. find version object
    try:
        versions = list_available_versions(include_prerelease=True)
    except Exception as e:
        yield {"stage": "error", "message": str(e), "percent": 0}
        return
        
    target_v = None
    for v in versions:
        disp = str(getattr(v, "display", ""))
        ver_str = str(getattr(v, "version", ""))
        if disp == version or disp.lstrip("v") == version.lstrip("v") or ver_str == version.lstrip("v"):
            target_v = v
            break
            
    if not target_v:
        yield {"stage": "error", "message": f"Version {version} not found on GitHub", "percent": 0}
        return
        
    fetcher = CustomCamoufoxFetcher(selected_version=target_v)
    
    # 2. queue to get progress from thread
    queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    
    last_yield_time = 0.0
    import time
    
    def progress_callback(downloaded, total_size):
        # webdl already limits updates to 64KB intervals, but we can also rate limit time
        loop.call_soon_threadsafe(queue.put_nowait, (downloaded, total_size))
        
    CustomCamoufoxFetcher.progress_callback = progress_callback
        
    def download_thread():
        try:
            fetcher.install(replace=True)
            try:
                from .camoufox_policies import sanitize_all_installed_camoufox_kernels
                sanitize_all_installed_camoufox_kernels()
            except Exception:
                pass
            loop.call_soon_threadsafe(queue.put_nowait, "DONE")
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, e)
            
    t = threading.Thread(target=download_thread, daemon=True)
    t.start()
    
    while True:
        item = await queue.get()
        if item == "DONE":
            yield {
                "stage": "completed",
                "message": f"Camoufox {version} 安装完成",
                "percent": 100,
                "downloaded_bytes": getattr(target_v, "asset_size", 0),
                "total_bytes": getattr(target_v, "asset_size", 0),
            }
            break
        elif isinstance(item, Exception):
            yield {"stage": "error", "message": str(item), "percent": 0}
            break
        else:
            downloaded, total = item
            pct = downloaded / total * 100 if total else 0
            
            # Throttling yields to prevent overwhelming SSE
            now = time.time()
            if now - last_yield_time > 0.1 or downloaded == total:
                last_yield_time = now
                yield {
                    "stage": "downloading",
                    "message": f"正在下载 Camoufox {version}...",
                    "percent": int(pct),
                    "downloaded_bytes": downloaded,
                    "total_bytes": total,
                }
