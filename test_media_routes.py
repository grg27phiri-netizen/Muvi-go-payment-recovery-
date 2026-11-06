from pathlib import Path
from app import app

client = app.test_client()
failed = 0
checked = 0

for kind, folder, ext in [("videos", "media/videos", ".mp4"), ("music", "media/music", ".mp3")]:
    for path in sorted(Path(folder).glob("*" + ext)):
        checked += 1
        url = "/media-files/{}/{}".format(kind, path.name)
        response = client.get(url, headers={"Range": "bytes=0-1023"})
        ok = response.status_code == 206 and len(response.data) > 0
        print("{} | HTTP {} | {} | {}".format("PASS" if ok else "FAIL", response.status_code, path.name, response.headers.get("Content-Type", "unknown")))
        if not ok:
            failed += 1

print("FILES_CHECKED={}".format(checked))
print("FAILED_FILES={}".format(failed))
print("MEDIA_ROUTE_TEST={}".format("PASS" if checked == 20 and failed == 0 else "FAIL"))
