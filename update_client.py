"""Клиент за ъпдейти от swing_live канала: локален Drive или HTTP fallback.

--check : само докладва има ли нова версия
--apply : сваля, проверява подпис+sha256, бекъпва, разархивира, събужда watchdog
Проверява RSA подписа на RELEASE.json срещу публичния модул на publisher ключа.

Режим на работа: ако локалният Drive канал съществува (машината на собственика),
файловете се четат от него без промяна. Иначе (клиентски машини без G:) се
свалят по HTTP от RELEASE_BASE_URL — публичното копие на канала.
"""
import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# BASE от местоположението на скрипта — еднакво работи на машината на
# собственика и при клиенти (твърдият D:\ път счупваше ъпдейта на клиенти).
BASE = Path(__file__).resolve().parents[1]
DRIVE = Path(r"G:\My Drive\AdmiralAI_Shared\swing_live")
RELEASE_BASE_URL = "https://martin4o123.github.io/demon-centar/swing_live"
LOCAL_VER = BASE / "VERSION.json"
EVENTS = BASE / "logs" / "events.jsonl"
STOP_FLAG = BASE / "STOP.flag"

MODULUS_HEX = "b663a2203c5bdac9e0778eba9b74a2cd72db245036b571932459490f6fc21283cd3c11f5c146067ada7b931dc08d142b1cd39006aa7bff8d516164391305f3ea5ca9396cb66c05abb332f45d71490035f3f0cee66e02a9386b0cdb38c5ea05f802c5f6a6a3c3e97acf4b309c4c4b8606ca2c31ea9a3c04c7b4223b5e3accdb3957f30af630a13ab55ef77516a1728d62b5d26471dacedd9762b28906baa937e0b4d753b803947e258b3eca8c432e9c2e9234fcbd2330c0a503042e5baf16bfc801470637670fbad5cb27bce20044caa8cda16e8b4bbbc907d7dd6c257f540252abd055c505f6b061963d8833395fbbcc038ff63d8d1914c685057edb4ac85ddf97e50b15fa8ae1f798ebbb9befefccc8a72246995cd447fb86b226c889ac881bddd74b0598c453e4f7ac24bc1a46dd5fd7f00505034b214f5a609621762f9c592c580601c476df82a809baefa2a831b4a62904da7618dea24cff72fb0a0571e106997b47b797a71183f686b705ab7d67f214d34f2607776d88de033cdd64cef1"
KEY_ID = "da6dbc7a152497ac"


def log_event(kind: str, detail: str) -> None:
    EVENTS.parent.mkdir(exist_ok=True)
    with open(EVENTS, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                            "kind": kind, "detail": detail}, ensure_ascii=False) + "\n")


def notify(level: str, category: str, text: str) -> None:
    """Central notification bus (engine\\notify.py) — best-effort."""
    try:
        subprocess.run([sys.executable, str(BASE / "engine" / "notify.py"),
                        "--level", level, "--category", category, "--text", text],
                       capture_output=True, timeout=60)
    except Exception:
        pass


def version_tuple(v: str):
    return tuple(int(x) for x in v.split("."))


def http_get(url: str) -> bytes:
    """GET с User-Agent и timeout 30; вдига изключение при HTTP грешка/мрежов проблем."""
    req = urllib.request.Request(url, headers={"User-Agent": "admiral-swing-live-updater/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def download(url: str, dest: Path) -> None:
    dest.write_bytes(http_get(url))


def verify_release(rel: dict, rel_bytes: bytes, sig_b64: str) -> str:
    if rel.get("publisher", {}).get("key_id") != KEY_ID:
        return f"key_id {rel.get('publisher', {}).get('key_id')} ≠ {KEY_ID}"
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
        pub = rsa.RSAPublicNumbers(
            65537, int(MODULUS_HEX, 16)).public_key(serialization.Encoding.PEM)
        pub.verify(base64.b64decode(sig_b64.strip()), rel_bytes,
                   padding.PKCS1v15(), hashes.SHA256())
    except Exception as e:
        return f"НЕВАЛИДЕН ПОДПИС: {e}"
    return ""


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _validate_banlist(raw: bytes) -> dict:
    data = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("banlist.json не е JSON обект")
    if not isinstance(data.get("banned_sha256", []), list):
        raise ValueError("banned_sha256 не е списък")
    return data


def _write_banlist(data: dict) -> None:
    dest = BASE / "config" / "banlist.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(dest)
    n = len(data.get("banned_sha256", []))
    log_event("banlist_synced", f"{n} блокирани ключа")
    print(f"banlist.json обновен ({n} блокирани ключа).")


def sync_banlist() -> None:
    """Локален режим: banlist.json от Drive root-а -> config\\banlist.json.

    Така блокираните от собственика ключове влизат в сила при всяка проверка.
    Липсващ/повреден файл = предупреждение; НЕ спира ъпдейта.
    """
    src = DRIVE / "banlist.json"
    if not src.exists():
        print("Няма banlist.json в Drive (пропускам синхронизацията).")
        return
    try:
        data = _validate_banlist(src.read_bytes())
    except Exception as exc:
        print(f"ПРЕДУПРЕЖДЕНИЕ: banlist.json не се чете ({exc}) — продължавам без него.")
        return
    _write_banlist(data)


def sync_banlist_http() -> None:
    """HTTP режим: banlist.json от сървъра -> config\\banlist.json (tmp+replace).

    404/мрежова грешка = предупреждение; НЕ спира ъпдейта.
    """
    try:
        data = _validate_banlist(http_get(RELEASE_BASE_URL + "/banlist.json"))
    except Exception as exc:
        print(f"ПРЕДУПРЕЖДЕНИЕ: banlist.json не се сваля ({exc}) — продължавам без него.")
        return
    _write_banlist(data)


def _release_root_from_zip(zip_rel: str) -> Path:
    """releases/0.9.x/swing_live-0.9.x.zip -> <root> (папката над releases)."""
    return Path(zip_rel).resolve().parents[2]


def _cleanup_old_releases(root: Path, keep: int = 3) -> None:
    """Трие старите releases/<версия> папки, пазейки `keep` най-нови по версия."""
    def vkey(name: str):
        try:
            return tuple(int(x) for x in name.split("."))
        except ValueError:
            return (0,)
    try:
        vers = sorted((p for p in (root / "releases").iterdir() if p.is_dir()),
                      key=lambda p: vkey(p.name))
    except OSError:
        return
    for old in vers[:-keep]:
        try:
            shutil.rmtree(old)
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    http_mode = not (DRIVE / "RELEASE.json").exists()
    if http_mode:
        try:
            rel_bytes = http_get(RELEASE_BASE_URL + "/RELEASE.json")
        except Exception:
            print("Няма връзка със сървъра за обновяване (проверете интернета).")
            return 0
    else:
        rel_bytes = (DRIVE / "RELEASE.json").read_bytes()

    # banlist-ът важи и при --check, и при --apply; НО грешка в него НИКОГА не
    # спира ъпдейта (иначе стар updater не може да си донесе нов — кокошка-яйце).
    try:
        (sync_banlist_http if http_mode else sync_banlist)()
    except Exception as exc:
        print(f"ПРЕДУПРЕЖДЕНИЕ: banlist синхронизацията не мина ({exc}) — продължавам.")

    rel = json.loads(rel_bytes.decode("utf-8-sig"))
    new_ver = rel["version"]
    local = json.loads(LOCAL_VER.read_text(encoding="utf-8")) if LOCAL_VER.exists() else {"version": "0.0.0"}
    if version_tuple(new_ver) <= version_tuple(local["version"]):
        print(f"Актуално: {local['version']}")
        return 0

    if http_mode:
        try:
            sig = http_get(RELEASE_BASE_URL + "/RELEASE.sig").decode("ascii")
        except Exception as exc:
            err = f"RELEASE.sig не се сваля: {exc}"
            print("ОТКАЗ:", err)
            log_event("update_refused", err)
            notify("alert", "update", f"Ъпдейт ОТКАЗАН: {err}")
            return 2
    else:
        sig = (DRIVE / "RELEASE.sig").read_text(encoding="ascii")
    err = verify_release(rel, rel_bytes, sig)
    if err:
        print("ОТКАЗ:", err)
        log_event("update_refused", err)
        notify("alert", "update", f"Ъпдейт ОТКАЗАН (невалиден подпис): {err}")
        return 2

    print(f"НОВА ВЕРСИЯ: {new_ver} (локално {local['version']})")
    print(f"Бележки: {rel.get('notes', '')}")
    log_event("update_available", f"{new_ver}: {rel.get('notes', '')}")
    notify("warning", "update",
           f"Наличен ъпдейт {new_ver} (локално {local['version']}): {rel.get('notes', '')}")

    if args.check or not args.apply:
        print("За прилагане: update_client.py --apply")
        return 0

    zip_rel = rel["installer"]["file"]
    tmp_zip = None
    if http_mode:
        with tempfile.NamedTemporaryFile(prefix="swing_live_", suffix=".zip", delete=False) as tf:
            tmp_zip = Path(tf.name)
        try:
            download(RELEASE_BASE_URL + "/" + zip_rel, tmp_zip)
        except Exception as exc:
            tmp_zip.unlink(missing_ok=True)
            print(f"Липсва zip: {RELEASE_BASE_URL}/{zip_rel} ({exc})")
            return 2
        zip_src = tmp_zip
    else:
        zip_src = DRIVE / zip_rel
        if not zip_src.exists():
            print("Липсва zip:", zip_src)
            return 2
    if sha256(zip_src) != rel["installer"]["sha256"]:
        if tmp_zip:
            tmp_zip.unlink(missing_ok=True)
        print("ОТКАЗ: sha256 на zip не съвпада")
        return 2

    # фаза 2: цялост — verify MANIFEST.sig + sha256 на всички файли преди apply
    sys.path.insert(0, str(BASE / "engine"))
    import integrity as _integrity
    with tempfile.TemporaryDirectory() as td:
        with zipfile.ZipFile(zip_src) as z:
            z.extractall(td)
        if (Path(td) / "MANIFEST.sha256").exists():
            ok, msg = _integrity.verify_manifest(Path(td))
            if not ok:
                print("ОТКАЗ:", msg)
                log_event("update_refused", msg)
                notify("alert", "update", f"Ъпдейт ОТКАЗАН (манифест): {msg}")
                return 2
        apply_src = Path(td)

        # STOP координация
        STOP_FLAG.touch()
        time.sleep(3)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = BASE / "backups" / f"update_{stamp}"
        for item in ("engine", "dashboard", "scripts"):
            src = BASE / item
            if src.exists():
                shutil.copytree(src, backup / item)
        for p in apply_src.rglob("*"):
            if p.is_dir():
                continue
            rel = p.relative_to(apply_src)
            # default.tpl не се презаписва: при първа инсталация го няма,
            # после потребителят може да си е пипнал шаблона — пазим го
            if str(rel).replace("\\", "/") == "mt5_portable/MQL5/Profiles/Templates/default.tpl" and (BASE / rel).exists():
                continue
            dest = BASE / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
    if tmp_zip:
        tmp_zip.unlink(missing_ok=True)
    if not http_mode:
        _cleanup_old_releases(_release_root_from_zip(zip_rel))
    LOCAL_VER.write_text(json.dumps(
        {"version": new_ver, "channel": rel["product_id"]}, indent=2), encoding="utf-8")
    STOP_FLAG.unlink(missing_ok=True)
    subprocess.Popen(["cmd", "/c", str(BASE / "scripts" / "admiral_autostart.cmd")],
                     cwd=str(BASE))
    log_event("update_applied", new_ver)
    notify("info", "update", f"Ъпдейт ПРИЛОЖЕН: {new_ver} (бекъп: {backup})")
    print(f"Приложено {new_ver}. Бекъп: {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
