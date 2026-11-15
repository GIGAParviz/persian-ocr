import ast
import fnmatch
import gzip
import hashlib
import io
import json
import re
import struct
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".cache" / "img"
BLOBS = WORK / "blobs"
SITE = WORK / "site-packages"
IMAGE = "persian-ocr:0.2.0"
OUT = ROOT / "deploy" / "persian-ocr-0.2.0.tar"
BASE_REPO, BASE_TAG = "library/python", "3.12-slim-trixie"
APP_DIRS = ("persian_ocr", "evaluation", "indra-ocr")
APP_FILES = ("requirements.txt", "requirements.lock")
SITE_DIR = "usr/local/lib/python3.12/site-packages"
MODEL_FILES = {"det.onnx", "rec.onnx", "rec_rtl.onnx", "rec_cjk.onnx", "rec_world.onnx", "order.onnx", "orient.onnx", "script.onnx", "mathcls.onnx", "meta.json", "config.json", "lm.npz", "lm_cjk.npz", "lm_world.npz", "LICENSE"}
EPOCH = 1793404800
ENV = ["PYTHONDONTWRITEBYTECODE=1", "PYTHONUNBUFFERED=1", "PERSIAN_OCR_HOST=0.0.0.0", "PERSIAN_OCR_PORT=8000", "HOME=/tmp"]
HEALTH = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def fetch(url: str, token: str, accept: str = "") -> bytes:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", **({"Accept": accept} if accept else {})})
    try:
        with OPENER.open(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code not in (301, 302, 303, 307, 308):
            raise
        with urllib.request.urlopen(e.headers["Location"], timeout=300) as r:
            return r.read()


def blob(digest: str, token: str) -> bytes:
    path = BLOBS / digest.replace(":", "_")
    data = path.read_bytes() if path.exists() else fetch(f"https://registry-1.docker.io/v2/{BASE_REPO}/blobs/{digest}", token)
    if "sha256:" + hashlib.sha256(data).hexdigest() != digest:
        raise SystemExit(f"digest mismatch for {digest}")
    BLOBS.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def pull_base() -> tuple[dict, list[bytes]]:
    with urllib.request.urlopen(f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{BASE_REPO}:pull", timeout=60) as r:
        token = json.load(r)["token"]
    index = json.loads(fetch(f"https://registry-1.docker.io/v2/{BASE_REPO}/manifests/{BASE_TAG}", token, "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json"))
    digest = next(m["digest"] for m in index["manifests"] if m["platform"] == {"architecture": "amd64", "os": "linux"} or (m["platform"].get("architecture"), m["platform"].get("os"), m["platform"].get("variant")) == ("amd64", "linux", None))
    manifest = json.loads(fetch(f"https://registry-1.docker.io/v2/{BASE_REPO}/manifests/{digest}", token, "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json"))
    config = json.loads(blob(manifest["config"]["digest"], token))
    layers = [gzip.decompress(blob(layer["digest"], token)) for layer in manifest["layers"]]
    for data, diff_id in zip(layers, config["rootfs"]["diff_ids"], strict=True):
        if "sha256:" + hashlib.sha256(data).hexdigest() != diff_id:
            raise SystemExit(f"base layer diff_id mismatch {diff_id}")
    print(f"base {BASE_REPO}:{BASE_TAG} {digest[:19]} python {dict(e.split('=', 1) for e in config['config']['Env']).get('PYTHON_VERSION')}, {len(layers)} layers verified")
    return config, layers


def ignore_rules() -> list[tuple[bool, str]]:
    rules = []
    for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            rules.append((line.startswith("!"), line.lstrip("!").rstrip("/")))
    return rules


def ignored(rel: str, rules: list[tuple[bool, str]]) -> bool:
    parts = rel.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    result = False
    for include, pattern in rules:
        if any(fnmatch.fnmatch(p, pattern) or fnmatch.fnmatch(p, pattern.replace("**/", "")) or fnmatch.fnmatch(p.split("/")[-1], pattern.replace("**/", "")) for p in prefixes):
            result = not include
    return result


def add(tar: tarfile.TarFile, name: str, data: bytes | None = None, mode: int = 0o644, uid: int = 0) -> None:
    info = tarfile.TarInfo(name)
    info.mtime, info.uid, info.gid = EPOCH, uid, uid
    if data is None:
        info.type, info.mode = tarfile.DIRTYPE, 0o755
        tar.addfile(info)
    else:
        info.size, info.mode = len(data), mode
        tar.addfile(info, io.BytesIO(data))


def app_layer() -> tuple[bytes, list[str]]:
    rules = ignore_rules()
    buf = io.BytesIO()
    names = []
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for d in ("app", "usr", "usr/local", "usr/local/lib", "usr/local/lib/python3.12", SITE_DIR):
            add(tar, d)
        add(tar, "app/.cache", uid=1000)
        add(tar, "app/output", uid=1000)
        sources = [ROOT / f for f in APP_FILES] + [p for d in APP_DIRS for p in sorted((ROOT / d).rglob("*"))]
        for path in sources:
            rel = path.relative_to(ROOT).as_posix()
            if ignored(rel, rules):
                continue
            add(tar, f"app/{rel}") if path.is_dir() else add(tar, f"app/{rel}", path.read_bytes())
            names.append(f"app/{rel}")
        for path in sorted(SITE.rglob("*")):
            rel = path.relative_to(SITE).as_posix()
            if rel.split("/")[0] in ("bin", "share") or "__pycache__" in rel:
                continue
            exe = path.suffix == ".so" or ".so." in path.name or ".libs/" in rel
            add(tar, f"{SITE_DIR}/{rel}") if path.is_dir() else add(tar, f"{SITE_DIR}/{rel}", path.read_bytes(), 0o755 if exe else 0o644)
            names.append(f"{SITE_DIR}/{rel}")
    return buf.getvalue(), names


def elf_info(data: bytes) -> tuple[list[str], set[str], set[str]]:
    if data[:4] != b"\x7fELF" or data[4] != 2:
        return [], set(), set()
    phoff, shoff = struct.unpack_from("<QQ", data, 0x20)
    phentsize, phnum = struct.unpack_from("<HH", data, 0x36)
    loads, dynamic = [], None
    for i in range(phnum):
        p_type, _, p_offset, p_vaddr, _, p_filesz, _, _ = struct.unpack_from("<IIQQQQQQ", data, phoff + i * phentsize)
        if p_type == 1:
            loads.append((p_vaddr, p_offset, p_filesz))
        if p_type == 2:
            dynamic = (p_offset, p_filesz)
    if dynamic is None:
        return [], set(), set()

    def off(vaddr: int) -> int:
        return next(o + vaddr - v for v, o, s in loads if v <= vaddr < v + s)

    tags: dict[int, list[int]] = {}
    for i in range(dynamic[1] // 16):
        tag, val = struct.unpack_from("<qQ", data, dynamic[0] + i * 16)
        if tag == 0:
            break
        tags.setdefault(tag, []).append(val)
    strtab = off(tags[5][0])

    def string(o: int) -> str:
        return data[strtab + o: data.index(b"\0", strtab + o)].decode()

    needed = [string(v) for v in tags.get(1, [])]
    required, provided = set(), set()
    if 0x6FFFFFFE in tags:
        pos = off(tags[0x6FFFFFFE][0])
        for _ in range(tags[0x6FFFFFFF][0]):
            _, cnt, _, aux, nxt = struct.unpack_from("<HHIII", data, pos)
            a = pos + aux
            for _ in range(cnt):
                _, _, _, name, anext = struct.unpack_from("<IHHII", data, a)
                required.add(string(name))
                a += anext
            pos += nxt
    if 0x6FFFFFFC in tags:
        pos = off(tags[0x6FFFFFFC][0])
        for _ in range(tags[0x6FFFFFFD][0]):
            _, _, _, cnt, _, aux, nxt = struct.unpack_from("<HHHHIII", data, pos)
            if cnt:
                provided.add(string(struct.unpack_from("<I", data, pos + aux)[0]))
            pos += nxt
    return needed, required, provided


def version_key(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v))


def check(base_layers: list[bytes], app_tar: bytes, app_names: list[str]) -> list[str]:
    problems = []
    base_files: dict[str, bytes | None] = {}
    for layer in base_layers:
        with tarfile.open(fileobj=io.BytesIO(layer)) as tar:
            for m in tar.getmembers():
                base_files[m.name.lstrip("./")] = None
    libdirs = ("lib/", "usr/lib/", "usr/local/lib/", "lib64/")
    base_sonames = {Path(n).name for n in base_files if n.startswith(libdirs) and ".so" in n}
    for layer in base_layers:
        with tarfile.open(fileobj=io.BytesIO(layer)) as tar:
            for m in tar.getmembers():
                if m.isfile() and Path(m.name).name.startswith("libc.so"):
                    glibc = max((v for v in elf_info(tar.extractfile(m).read())[2] if v.startswith("GLIBC_2")), key=version_key)
    app_sonames = {Path(n).name for n in app_names if ".so" in Path(n).name}
    missing, max_glibc, checked = {}, "GLIBC_2.0", 0
    with tarfile.open(fileobj=io.BytesIO(app_tar)) as tar:
        for m in tar.getmembers():
            if not (m.isfile() and (".so" in Path(m.name).name)):
                continue
            needed, required, _ = elf_info(tar.extractfile(m).read())
            checked += 1
            for lib in needed:
                if lib not in base_sonames and lib not in app_sonames:
                    missing.setdefault(lib, []).append(m.name.split("site-packages/")[-1])
            for v in required:
                if v.startswith("GLIBC_2") and version_key(v) > version_key(max_glibc):
                    max_glibc = v
    print(f"shared libraries checked: {checked}; highest glibc needed {max_glibc}, base provides {glibc}")
    if version_key(max_glibc) > version_key(glibc):
        problems.append(f"needs {max_glibc} but base has {glibc}")
    for lib, users in missing.items():
        problems.append(f"missing system library {lib} (needed by {users[0]} and {len(users) - 1} more)")

    site_top = {n.split("/")[5] for n in app_names if n.startswith(SITE_DIR + "/") and n.count("/") >= 5}
    site_mods = {Path(t).stem.split("-")[0] for t in site_top} | {"_yaml"}
    local = {"persian_ocr", "evaluation"}
    stdlib = set(sys.stdlib_module_names)
    for n in app_names:
        if n.endswith(".py") and n.split("/")[1] in local:
            tree = ast.parse((ROOT / n[4:]).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else ([node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else [])
                for mod in mods:
                    top = mod.split(".")[0]
                    if top not in stdlib and top not in local and top not in site_mods:
                        problems.append(f"{n}: import {mod} not installed in image")
    models = {Path(n).name for n in app_names if n.startswith("app/indra-ocr/") and "/" not in n[len("app/indra-ocr/"):]}
    if models != MODEL_FILES:
        problems.append(f"model files differ: missing {sorted(MODEL_FILES - models)}, extra {sorted(models - MODEL_FILES)}")
    for secret in ("app/evaluation/ground_truth", "app/evaluation/number_verdicts.json", "app/eval_data", "app/files", "app/.venv"):
        if any(n == secret or n.startswith(secret + "/") for n in app_names):
            problems.append(f"confidential path inside image: {secret}")
    return problems


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass
    if not SITE.exists():
        subprocess.run(["uv", "pip", "install", "--target", str(SITE), "--python-platform", "x86_64-manylinux_2_28", "--python-version", "3.12", "--only-binary", ":all:", "--no-deps", "-r", str(ROOT / "requirements.lock")], check=True)
    base_config, base_layers = pull_base()
    layer, names = app_layer()
    problems = check(base_layers, layer, names)
    for p in problems:
        print("PROBLEM:", p)
    if problems:
        return 1

    layers = base_layers + [layer]
    diff_ids = ["sha256:" + hashlib.sha256(d).hexdigest() for d in layers]
    config = dict(base_config)
    cfg = dict(config["config"])
    cfg["Env"] = [e for e in cfg.get("Env", []) if e.split("=")[0] not in {x.split("=")[0] for x in ENV}] + ENV
    cfg.update({"WorkingDir": "/app", "User": "1000:1000", "Cmd": ["python", "-m", "persian_ocr", "serve"], "Entrypoint": None, "ExposedPorts": {"8000/tcp": {}}, "Healthcheck": {"Test": HEALTH, "Interval": 30 * 10**9, "Timeout": 5 * 10**9, "StartPeriod": 90 * 10**9, "Retries": 3}, "Labels": {"org.opencontainers.image.title": "persian-ocr", "org.opencontainers.image.version": "0.2.0"}})
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    config.update({"config": cfg, "created": created, "architecture": "amd64", "os": "linux"})
    config["rootfs"] = {"type": "layers", "diff_ids": diff_ids}
    config["history"] = list(config.get("history", [])) + [{"created": created, "created_by": "persian-ocr app layer (tools/build_image_tar.py)"}]
    config_bytes = json.dumps(config, separators=(",", ":")).encode()
    config_name = hashlib.sha256(config_bytes).hexdigest() + ".json"
    layer_names = [f"{d[7:]}/layer.tar" for d in diff_ids]
    manifest = [{"Config": config_name, "RepoTags": [IMAGE], "Layers": layer_names}]
    with tarfile.open(OUT, "w", format=tarfile.PAX_FORMAT) as tar:
        add(tar, config_name, config_bytes)
        for name, data in zip(layer_names, layers):
            add(tar, name.split("/")[0])
            add(tar, name, data)
        add(tar, "manifest.json", json.dumps(manifest).encode())
        add(tar, "repositories", json.dumps({IMAGE.split(":")[0]: {IMAGE.split(":")[1]: diff_ids[-1][7:]}}).encode())
    print(f"written {OUT} ({OUT.stat().st_size >> 20} MB), app layer {len(layer) >> 20} MB, {len(names)} files")
    return 0


sys.exit(main())
