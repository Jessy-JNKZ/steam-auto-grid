"""
Steam Auto-Grid — Non-Steam Shortcut & Artwork Injector
Développé par Jessy JONKISZ (https://github.com/Jessy-JNKZ | https://x.com/JNKZJessy)
"""

import os
import re
import sys
import json
import time
import ctypes
import struct
import random
import shutil
import winreg
import tempfile
import webbrowser
import threading
import subprocess
from io import BytesIO
from pathlib import Path

import requests
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image

# Version et dépôt GitHub pour l'auto-updater
APP_VERSION = "1.0.4"
GITHUB_REPO = "Jessy-JNKZ/steam-auto-grid"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"

# Configuration globale de l'interface (Dark Mode)
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# Palette alignée sur la direction artistique de icon.png / icon.ico
BG_DARK = "#090B0E"
CARD_BG = "#11151C"
CARD_BORDER = "#1E2430"
PREVIEW_BG = "#0C0F14"

ACCENT_BLUE = "#00A8FF"     # Engrenage Steam & Carré 1
ACCENT_GREEN = "#00FF38"    # Flèches d'automatisation & Carré 2
ACCENT_GREEN_HOVER = "#00CC2D"
ACCENT_ORANGE = "#FF8C00"   # Carré 3
ACCENT_PURPLE = "#A820FF"   # Carré 4
TEXT_MUTED = "#8A94A6"


def get_resource_path(filename: str) -> Path:
    """Résout le chemin d'une ressource locale ou embarquée via PyInstaller (_MEIPASS)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        candidate = Path(sys._MEIPASS) / filename
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parent / filename


class AutoUpdater:
    """Gère la vérification et l'installation automatique des mises à jour via GitHub Releases."""

    @staticmethod
    def parse_version(tag: str) -> tuple[int, ...]:
        cleaned = tag.strip().lstrip("vV")
        nums = [int(x) for x in re.findall(r"\d+", cleaned)]
        return tuple(nums) if nums else (0,)

    @staticmethod
    def check_latest_release() -> dict | None:
        resp = requests.get(
            GITHUB_API_LATEST,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "Steam-Auto-Grid-Updater"},
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()

        tag_name = data.get("tag_name", "")
        remote_ver = AutoUpdater.parse_version(tag_name)
        local_ver = AutoUpdater.parse_version(APP_VERSION)

        if remote_ver > local_ver:
            exe_url = None
            for asset in data.get("assets", []):
                if asset.get("name", "").lower().endswith(".exe"):
                    exe_url = asset.get("browser_download_url")
                    break
            return {
                "tag": tag_name,
                "name": data.get("name") or tag_name,
                "body": data.get("body", ""),
                "html_url": data.get("html_url", GITHUB_RELEASES_URL),
                "exe_url": exe_url,
            }
        return None

    @staticmethod
    def download_and_replace_exe(exe_url: str, progress_callback=None):
        """Télécharge le nouvel .exe et génère un script de remplacement isolé de l'environnement PyInstaller."""
        current_exe = Path(sys.executable).resolve()
        temp_dir = Path(tempfile.gettempdir())
        new_exe = temp_dir / f"Steam-Auto-Grid-update-{int(time.time())}.exe"

        with requests.get(exe_url, stream=True, timeout=30) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(new_exe, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total > 0:
                            progress_callback(int(downloaded * 100 / total))

        # Nettoie les variables héritées de PyInstaller pour éviter l'erreur Failed to load Python DLL
        clean_env = os.environ.copy()
        for key in list(clean_env.keys()):
            if key.upper().startswith("_MEI") or key.upper() in {
                "_PYI_ARCHIVE_FILE",
                "_PYI_PARENT_PROCESS_LEVEL",
                "_PYI_SPLASH_IPC",
            }:
                clean_env.pop(key, None)

        bat_path = temp_dir / "steam_auto_grid_updater.bat"
        bat_content = f"""@echo off
set "_MEIPASS="
set "_MEIPASS2="
set "_PYI_ARCHIVE_FILE="
set "_PYI_PARENT_PROCESS_LEVEL="
timeout /t 2 /nobreak > nul
:loop
move /Y "{new_exe}" "{current_exe}" > nul 2>&1
if errorlevel 1 (
    timeout /t 1 /nobreak > nul
    goto loop
)
timeout /t 1 /nobreak > nul
explorer.exe "{current_exe}"
del "%~f0"
"""
        bat_path.write_text(bat_content, encoding="utf-8")
        subprocess.Popen(
            ["cmd.exe", "/c", str(bat_path)],
            env=clean_env,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        )


class SteamBackend:
    """Gère la détection Steam, le cycle de vie du processus, la détection & indexation VR, shortcuts.vdf et l'API."""

    @staticmethod
    def get_steam_path() -> Path | None:
        keys = [
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        ]
        for hive, subkey, val_name in keys:
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    val, _ = winreg.QueryValueEx(key, val_name)
                    path = Path(val.replace("/", "\\"))
                    if (path / "userdata").exists():
                        return path
            except OSError:
                continue
        return None

    @staticmethod
    def get_active_userdata(steam_path: Path) -> Path | None:
        userdata = steam_path / "userdata"
        if not userdata.exists():
            return None
        configs = sorted(
            [p for p in userdata.glob("*/config") if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return configs[0].parent if configs else None

    @staticmethod
    def is_steam_running() -> bool:
        try:
            res = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "if (Get-Process -Name 'steam','vrmonitor' -ErrorAction SilentlyContinue) { 'RUNNING' }",
                ],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return "RUNNING" in res.stdout
        except Exception:
            return False

    @staticmethod
    def force_close_steam(steam_path: Path):
        if not SteamBackend.is_steam_running():
            return

        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Stop-Process -Name 'vrmonitor','vrserver','vrwebhelper','vrcompositor' -Force -ErrorAction SilentlyContinue",
            ],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        steam_exe = steam_path / "steam.exe"
        if steam_exe.exists():
            subprocess.Popen([str(steam_exe), "-shutdown"], creationflags=subprocess.CREATE_NO_WINDOW)

        for _ in range(6):
            time.sleep(1)
            if not SteamBackend.is_steam_running():
                time.sleep(1)
                return

        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Stop-Process -Name 'steam','steamwebhelper','vrmonitor','vrserver','vrwebhelper' -Force -ErrorAction SilentlyContinue",
            ],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        time.sleep(2)

        if not SteamBackend.is_steam_running():
            return

        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "taskkill.exe",
            "/F /T /IM steam.exe /IM steamwebhelper.exe /IM vrmonitor.exe /IM vrserver.exe",
            None,
            0,
        )

        for _ in range(8):
            time.sleep(1)
            if not SteamBackend.is_steam_running():
                time.sleep(1)
                return

        raise RuntimeError("Steam ou SteamVR est toujours actif. Veuillez les fermer manuellement puis réessayez.")

    @staticmethod
    def launch_steam(steam_path: Path):
        steam_exe = steam_path / "steam.exe"
        if steam_exe.exists():
            subprocess.Popen([str(steam_exe)], creationflags=subprocess.CREATE_NO_WINDOW)

    @staticmethod
    def scan_executables(game_dir: Path) -> list[Path]:
        ignore = re.compile(r"(unins|setup|redist|crash|unity|dxweb|vc_redist)", re.IGNORECASE)
        return [p for p in game_dir.glob("*.exe") if not ignore.search(p.name)]

    @staticmethod
    def detect_local_vr(game_dir: Path) -> bool:
        if re.search(r"\bvr\b", game_dir.name, re.IGNORECASE):
            return True

        vr_markers = {"openvr_api.dll", "openxr_loader.dll", "ovrplugin.dll", "libovr64_1.dll"}
        for root, dirs, files in os.walk(game_dir):
            depth = Path(root).relative_to(game_dir).parts
            if len(depth) > 3:
                dirs[:] = []
                continue
            for d in dirs:
                if d.lower() in {"openvr", "openxr", "oculus"}:
                    return True
            for f in files:
                if f.lower() in vr_markers:
                    return True
        return False

    @staticmethod
    def check_steam_api_vr(appid: str) -> bool:
        if not appid.isdigit():
            return False
        try:
            url = f"https://store.steampowered.com/api/appdetails?appids={appid}&filters=categories"
            resp = requests.get(url, timeout=6)
            resp.raise_for_status()
            data = resp.json()
            app_data = data.get(str(appid), {})
            if app_data.get("success"):
                categories = app_data.get("data", {}).get("categories", [])
                vr_cat_ids = {53, 54, 402}
                for cat in categories:
                    if cat.get("id") in vr_cat_ids or "vr" in cat.get("description", "").lower():
                        return True
        except Exception:
            pass
        return False

    @staticmethod
    def detect_local_appid(game_dir: Path) -> tuple[str | None, str | None]:
        targets = {"steam_appid.txt", "steam_emu.ini", "ali213.ini", "codex.ini", "flt.ini", "tenoke.ini", "rune.ini"}
        for root, dirs, files in os.walk(game_dir):
            depth = Path(root).relative_to(game_dir).parts
            if len(depth) > 3:
                dirs[:] = []
                continue
            for file in files:
                if file.lower() in targets:
                    fpath = Path(root) / file
                    try:
                        content = fpath.read_text(encoding="utf-8", errors="ignore")
                        if file.lower() == "steam_appid.txt":
                            m = re.search(r"^\s*(\d{3,10})\s*$", content)
                            if m:
                                return m.group(1), file
                        else:
                            m = re.search(r"(?im)^\s*AppId\s*=\s*(\d{3,10})", content)
                            if m:
                                return m.group(1), file
                    except OSError:
                        pass
        return None, None

    @staticmethod
    def search_steam_store(query: str) -> list[dict]:
        clean = re.sub(r"\[.*?\]|\(.*?\)|\b(vr|repack|portable|goty|edition|v\d+(\.\d+)*)\b", "", query, flags=re.I).strip()
        if not clean:
            clean = query
        url = "https://store.steampowered.com/api/storesearch/"
        resp = requests.get(url, params={"term": clean, "l": "french", "cc": "FR"}, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])[:6]

    @staticmethod
    def inject_shortcut(user_dir: Path, app_name: str, exe_path: Path, is_vr: bool = False) -> int:
        config_dir = user_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        shortcuts_file = config_dir / "shortcuts.vdf"

        if shortcuts_file.exists():
            shutil.copy2(shortcuts_file, config_dir / "shortcuts.vdf.bak")
            raw = shortcuts_file.read_bytes()
        else:
            raw = b"\x00shortcuts\x00\x08\x08"

        text_latin = raw.decode("latin-1")
        target_esc = re.escape(str(exe_path))
        for chunk in text_latin.split("\x02appid\x00")[1:]:
            if len(chunk) >= 4 and re.search(target_esc, chunk, re.IGNORECASE):
                existing_id = struct.unpack("<I", chunk[:4].encode("latin-1"))[0]
                return existing_id

        next_idx = len(re.findall(b"\x02appid\x00", raw))
        non_steam_id = (random.getrandbits(31) | 0x80000000) & 0xFFFFFFFF

        def vdf_str(k: str, v: str) -> bytes:
            return b"\x01" + k.encode("utf-8") + b"\x00" + v.encode("utf-8") + b"\x00"

        def vdf_int(k: str, v: int) -> bytes:
            return b"\x02" + k.encode("utf-8") + b"\x00" + struct.pack("<I", v)

        entry = bytearray()
        entry += b"\x00" + str(next_idx).encode("utf-8") + b"\x00"
        entry += vdf_int("appid", non_steam_id)
        entry += vdf_str("AppName", app_name)
        entry += vdf_str("Exe", f'"{exe_path}"')
        entry += vdf_str("StartDir", f'"{exe_path.parent}"')
        entry += vdf_str("icon", str(exe_path))
        entry += vdf_str("ShortcutPath", "")
        entry += vdf_str("LaunchOptions", "")
        entry += vdf_int("IsHidden", 0)
        entry += vdf_int("AllowDesktopConfig", 1)
        entry += vdf_int("AllowOverlay", 1)
        entry += vdf_int("OpenVR", 1 if is_vr else 0)
        entry += vdf_int("Devkit", 0)
        entry += vdf_str("DevkitGameID", "")
        entry += vdf_int("DevkitOverrideAppID", 0)
        entry += vdf_int("LastPlayTime", 0)
        entry += vdf_str("FlatpakAppID", "")
        entry += b"\x00tags\x00\x08"
        entry += b"\x08"

        if not raw.endswith(b"\x08\x08"):
            raise ValueError("Structure binaire de shortcuts.vdf invalide.")

        final_data = raw[:-2] + bytes(entry) + b"\x08\x08"
        shortcuts_file.write_bytes(final_data)
        return non_steam_id

    @staticmethod
    def register_steamvr_app(steam_path: Path, non_steam_id: int, app_name: str, exe_path: Path):
        steam_config_dir = steam_path / "config"
        vrappconfig_dir = steam_config_dir / "vrappconfig"
        vrappconfig_dir.mkdir(parents=True, exist_ok=True)

        app_key = f"steam.app.{non_steam_id}"
        manifest_file = vrappconfig_dir / f"{app_key}.vrmanifest"

        manifest_data = {
            "source": "builtin",
            "applications": [
                {
                    "app_key": app_key,
                    "launch_type": "binary",
                    "binary_path_windows": str(exe_path),
                    "working_directory": str(exe_path.parent),
                    "is_dashboard_overlay": False,
                    "strings": {
                        "en_us": {
                            "name": app_name,
                            "description": f"{app_name} (Added via Steam Auto-Grid)",
                        },
                        "fr_fr": {
                            "name": app_name,
                            "description": f"{app_name} (Ajouté via Steam Auto-Grid)",
                        },
                    },
                }
            ],
        }
        manifest_file.write_text(json.dumps(manifest_data, indent=4, ensure_ascii=False), encoding="utf-8")

        vrapp_cfg_file = vrappconfig_dir / f"{app_key}.vrappconfig"
        vrapp_cfg_data = {
            "autolaunch": False,
            "last_launch_time": "0",
        }
        vrapp_cfg_file.write_text(json.dumps(vrapp_cfg_data, indent=4), encoding="utf-8")

        appconfig_file = steam_config_dir / "appconfig.json"
        if appconfig_file.exists():
            try:
                appconfig = json.loads(appconfig_file.read_text(encoding="utf-8"))
            except Exception:
                appconfig = {}
        else:
            appconfig = {}

        manifest_paths = appconfig.get("manifest_paths", [])
        if not isinstance(manifest_paths, list):
            manifest_paths = []

        manifest_str = str(manifest_file.resolve())
        normalized_existing = {str(Path(p).resolve()).lower() for p in manifest_paths if isinstance(p, str)}
        if manifest_str.lower() not in normalized_existing:
            manifest_paths.append(manifest_str)
            appconfig["manifest_paths"] = manifest_paths
            appconfig_file.write_text(json.dumps(appconfig, indent=4, ensure_ascii=False), encoding="utf-8")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"Steam Auto-Grid v{APP_VERSION} — Non-Steam Shortcut & Artwork Injector | par Jessy JONKISZ")
        self.geometry("880x785")
        self.minsize(830, 745)
        self.configure(fg_color=BG_DARK)

        # Application de l'icône sur la fenêtre et la barre des tâches Windows
        self._apply_window_icon()

        self.steam_path = SteamBackend.get_steam_path()
        self.user_dir = SteamBackend.get_active_userdata(self.steam_path) if self.steam_path else None
        self.game_dir: Path | None = None
        self.exe_list: list[Path] = []
        self.search_results: list[dict] = []
        self.preview_refs = []
        self.logo_img_ref = None
        self.vr_var = ctk.BooleanVar(value=False)

        self._build_ui()
        self._check_initial_context()
        self.after(1500, lambda: self._check_updates(silent=True))

    def _apply_window_icon(self):
        for name in ("icon_win.ico", "icon.ico"):
            ico_path = get_resource_path(name)
            if ico_path.exists():
                try:
                    self.iconbitmap(default=str(ico_path))
                    break
                except Exception:
                    continue

    def _load_brand_logo(self, size: tuple[int, int] = (48, 48)) -> ctk.CTkImage | None:
        for candidate in ("icon.png", "icon.ico", "icon_win.ico"):
            img_path = get_resource_path(candidate)
            if img_path.exists():
                try:
                    pil_img = Image.open(img_path).convert("RGBA")
                    return ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)
                except Exception:
                    continue
        return None

    def _build_ui(self):
        # --- En-tête avec icône de marque ---
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(16, 8))

        self.logo_img_ref = self._load_brand_logo((48, 48))
        if self.logo_img_ref:
            logo_lbl = ctk.CTkLabel(header, image=self.logo_img_ref, text="")
            logo_lbl.pack(side="left", padx=(0, 12))

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left")

        title_row = ctk.CTkFrame(title_box, fg_color="transparent")
        title_row.pack(anchor="w")

        ctk.CTkLabel(
            title_row,
            text="STEAM ",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color=ACCENT_BLUE,
        ).pack(side="left")

        ctk.CTkLabel(
            title_row,
            text="AUTO-GRID",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color="white",
        ).pack(side="left")

        ctk.CTkLabel(
            title_box,
            text="Injection automatique de jeux non-Steam, SteamVR & 4 jaquettes officielles",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
        ).pack(anchor="w")

        self.btn_update = ctk.CTkButton(
            header,
            text=f"↻ v{APP_VERSION}",
            width=84,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#161B24",
            hover_color="#222A38",
            border_width=1,
            border_color=CARD_BORDER,
            text_color="#D0D7E2",
            command=lambda: self._check_updates(silent=False),
        )
        self.btn_update.pack(side="right", padx=(12, 0))

        self.steam_badge = ctk.CTkLabel(
            header,
            text="● Steam détecté" if self.user_dir else "● Steam introuvable",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=ACCENT_GREEN if self.user_dir else "#FF5252",
        )
        self.steam_badge.pack(side="right")

        # --- Carte 1 : Dossier & Exécutable ---
        card_folder = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=CARD_BORDER)
        card_folder.pack(fill="x", padx=24, pady=7)

        ctk.CTkLabel(
            card_folder, text="1. Dossier du jeu & Exécutable", font=ctk.CTkFont(size=14, weight="bold"), text_color="white"
        ).pack(anchor="w", padx=16, pady=(12, 6))

        row_dir = ctk.CTkFrame(card_folder, fg_color="transparent")
        row_dir.pack(fill="x", padx=16, pady=(0, 8))

        self.dir_entry = ctk.CTkEntry(
            row_dir,
            placeholder_text="Sélectionnez le dossier racine du jeu...",
            height=36,
            fg_color=PREVIEW_BG,
            border_color=CARD_BORDER,
        )
        self.dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkButton(
            row_dir,
            text="Parcourir...",
            width=120,
            height=36,
            font=ctk.CTkFont(weight="bold"),
            fg_color=ACCENT_BLUE,
            hover_color="#008AD1",
            text_color="#06080B",
            command=self._browse_folder,
        ).pack(side="right")

        row_exe = ctk.CTkFrame(card_folder, fg_color="transparent")
        row_exe.pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkLabel(row_exe, text="Exécutable (.exe) :", text_color=TEXT_MUTED, width=130, anchor="w").pack(side="left")
        self.exe_combo = ctk.CTkComboBox(
            row_exe,
            values=["Aucun dossier sélectionné"],
            height=32,
            state="readonly",
            fg_color=PREVIEW_BG,
            border_color=CARD_BORDER,
        )
        self.exe_combo.pack(side="left", fill="x", expand=True)

        # --- Carte 2 : Identification Steam & Option VR ---
        card_id = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=CARD_BORDER)
        card_id.pack(fill="x", padx=24, pady=7)

        ctk.CTkLabel(
            card_id, text="2. Configuration & Recherche d'ID Steam", font=ctk.CTkFont(size=14, weight="bold"), text_color="white"
        ).pack(anchor="w", padx=16, pady=(12, 6))

        row_name = ctk.CTkFrame(card_id, fg_color="transparent")
        row_name.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(row_name, text="Nom dans Steam :", text_color=TEXT_MUTED, width=130, anchor="w").pack(side="left")
        self.name_entry = ctk.CTkEntry(
            row_name,
            placeholder_text="Nom affiché dans votre bibliothèque",
            height=34,
            fg_color=PREVIEW_BG,
            border_color=CARD_BORDER,
        )
        self.name_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkButton(
            row_name,
            text="Rechercher ID",
            width=120,
            height=34,
            fg_color="#1D2432",
            hover_color="#2A3447",
            border_width=1,
            border_color=CARD_BORDER,
            command=self._trigger_search,
        ).pack(side="right")

        row_appid = ctk.CTkFrame(card_id, fg_color="transparent")
        row_appid.pack(fill="x", padx=16, pady=(0, 10))

        ctk.CTkLabel(row_appid, text="Steam AppID :", text_color=TEXT_MUTED, width=130, anchor="w").pack(side="left")
        self.appid_entry = ctk.CTkEntry(
            row_appid,
            placeholder_text="Ex: 620980",
            width=130,
            height=34,
            fg_color=PREVIEW_BG,
            border_color=CARD_BORDER,
        )
        self.appid_entry.pack(side="left", padx=(0, 10))

        self.results_combo = ctk.CTkComboBox(
            row_appid,
            values=["Résultats de recherche Steam..."],
            height=34,
            state="readonly",
            fg_color=PREVIEW_BG,
            border_color=CARD_BORDER,
            command=self._on_result_selected,
        )
        self.results_combo.pack(side="left", fill="x", expand=True)

        row_vr = ctk.CTkFrame(card_id, fg_color="transparent")
        row_vr.pack(fill="x", padx=16, pady=(0, 14))

        self.vr_checkbox = ctk.CTkCheckBox(
            row_vr,
            text="Inclure automatiquement dans la bibliothèque SteamVR (OpenVR + Manifeste VR)",
            variable=self.vr_var,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#E0E6ED",
            fg_color=ACCENT_BLUE,
            hover_color="#008AD1",
        )
        self.vr_checkbox.pack(side="left")

        self.vr_badge = ctk.CTkLabel(
            row_vr,
            text="",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=ACCENT_GREEN,
        )
        self.vr_badge.pack(side="right")

        # --- Carte 3 : Aperçu des 4 visuels (aux 4 couleurs de l'icône) ---
        card_prev = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=12, border_width=1, border_color=CARD_BORDER)
        card_prev.pack(fill="both", expand=True, padx=24, pady=7)

        prev_header = ctk.CTkFrame(card_prev, fg_color="transparent")
        prev_header.pack(fill="x", padx=16, pady=(10, 4))

        ctk.CTkLabel(
            prev_header, text="3. Aperçu des 4 visuels officiels (Grille Steam)", font=ctk.CTkFont(size=14, weight="bold"), text_color="white"
        ).pack(side="left")

        ctk.CTkButton(
            prev_header,
            text="Prévisualiser",
            width=110,
            height=28,
            fg_color="#1D2432",
            hover_color="#2A3447",
            border_width=1,
            border_color=CARD_BORDER,
            command=self._load_previews,
        ).pack(side="right")

        self.preview_box = ctk.CTkFrame(card_prev, fg_color=PREVIEW_BG, corner_radius=8)
        self.preview_box.pack(fill="both", expand=True, padx=16, pady=(4, 14))

        self.preview_labels = []
        # Les 4 couleurs exactes des carrés de icon.png / icon.ico
        grid_specs = [
            ("Couverture (600x900)", ACCENT_BLUE),
            ("Arrière-plan (Hero)", ACCENT_GREEN),
            ("Logo (PNG)", ACCENT_ORANGE),
            ("Grande couverture", ACCENT_PURPLE),
        ]
        for title_txt, border_col in grid_specs:
            col = ctk.CTkFrame(
                self.preview_box,
                fg_color="#10141C",
                corner_radius=8,
                border_width=2,
                border_color=border_col,
            )
            col.pack(side="left", fill="both", expand=True, padx=6, pady=8)
            lbl_img = ctk.CTkLabel(col, text="Aucun aperçu", text_color=TEXT_MUTED, height=118)
            lbl_img.pack(expand=True, padx=4, pady=(6, 2))
            ctk.CTkLabel(
                col,
                text=f"■ {title_txt}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=border_col,
            ).pack(pady=(0, 6))
            self.preview_labels.append(lbl_img)

        # --- Barre d'action inférieure ---
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=24, pady=(8, 6))

        self.status_lbl = ctk.CTkLabel(footer, text="Prêt.", font=ctk.CTkFont(size=12), text_color=TEXT_MUTED)
        self.status_lbl.pack(side="left")

        self.btn_inject = ctk.CTkButton(
            footer,
            text="AJOUTER À STEAM & INJECTER LES IMAGES",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=ACCENT_GREEN,
            hover_color=ACCENT_GREEN_HOVER,
            text_color="#050806",
            height=42,
            width=320,
            command=self._start_injection,
        )
        self.btn_inject.pack(side="right")

        # --- Crédits développeur ---
        credits_bar = ctk.CTkFrame(self, fg_color="transparent")
        credits_bar.pack(fill="x", padx=24, pady=(2, 16))

        dev_lbl = ctk.CTkLabel(
            credits_bar,
            text="Développé par Jessy JONKISZ  •  GitHub : Jessy-JNKZ  •  X : @JNKZJessy",
            font=ctk.CTkFont(size=12),
            text_color=TEXT_MUTED,
            cursor="hand2",
        )
        dev_lbl.pack(side="right")
        dev_lbl.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/Jessy-JNKZ"))

    # --- Gestion des mises à jour GitHub ---
    def _check_updates(self, silent: bool = False):
        if not silent:
            self.btn_update.configure(state="disabled", text="Vérif...")
            self.status_lbl.configure(text="Recherche de mises à jour sur GitHub...", text_color=ACCENT_BLUE)

        def worker():
            try:
                release = AutoUpdater.check_latest_release()
                self.after(0, lambda: self._on_update_checked(release, silent))
            except Exception as exc:
                if not silent:
                    err_msg = str(exc) or type(exc).__name__
                    self.after(0, lambda: self._on_update_check_failed(err_msg))
                else:
                    self.after(0, lambda: self.btn_update.configure(state="normal", text=f"↻ v{APP_VERSION}"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_check_failed(self, err: str):
        self.btn_update.configure(state="normal", text=f"↻ v{APP_VERSION}")
        self.status_lbl.configure(text=f"Échec vérification MAJ : {err}", text_color="#FF5252")

    def _on_update_checked(self, release: dict | None, silent: bool):
        self.btn_update.configure(state="normal", text=f"↻ v{APP_VERSION}")
        if not release:
            if not silent:
                self.status_lbl.configure(text=f"Vous utilisez déjà la dernière version (v{APP_VERSION}).", text_color=ACCENT_GREEN)
                messagebox.showinfo("Mise à jour", f"Steam Auto-Grid v{APP_VERSION} est déjà à jour !")
            return

        new_tag = release["tag"]
        self.btn_update.configure(text=f"⬆ {new_tag}", fg_color=ACCENT_GREEN, text_color="#050806")
        self.status_lbl.configure(text=f"Nouvelle version disponible : {new_tag}", text_color=ACCENT_GREEN)

        is_frozen = getattr(sys, "frozen", False)
        if is_frozen and release.get("exe_url"):
            ask = messagebox.askyesno(
                "Mise à jour disponible",
                f"Une nouvelle version ({new_tag}) de Steam Auto-Grid est disponible sur GitHub !\n\n"
                f"Version actuelle : v{APP_VERSION}\n"
                f"Nouvelle version : {new_tag}\n\n"
                "Voulez-vous la télécharger et redémarrer automatiquement maintenant ?",
            )
            if ask:
                self._perform_auto_update(release["exe_url"], new_tag)
        else:
            ask = messagebox.askyesno(
                "Mise à jour disponible",
                f"Une nouvelle version ({new_tag}) est disponible sur GitHub !\n\n"
                "Voulez-vous ouvrir la page de téléchargement ?",
            )
            if ask:
                webbrowser.open(release["html_url"])

    def _perform_auto_update(self, exe_url: str, new_tag: str):
        self.btn_update.configure(state="disabled")
        self.btn_inject.configure(state="disabled")
        self.status_lbl.configure(text=f"Téléchargement de {new_tag} (0%)...", text_color=ACCENT_BLUE)

        def on_progress(pct: int):
            self.after(0, lambda: self.status_lbl.configure(text=f"Téléchargement de {new_tag} ({pct}%)...", text_color=ACCENT_BLUE))

        def worker():
            try:
                AutoUpdater.download_and_replace_exe(exe_url, progress_callback=on_progress)
                self.after(0, self._finish_auto_update)
            except Exception as exc:
                err_msg = str(exc) or type(exc).__name__
                self.after(0, lambda: self._on_update_error(err_msg))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_auto_update(self):
        self.status_lbl.configure(text="Mise à jour téléchargée ! Redémarrage...", text_color=ACCENT_GREEN)
        self.destroy()
        sys.exit(0)

    def _on_update_error(self, err: str):
        self.btn_update.configure(state="normal")
        self.btn_inject.configure(state="normal")
        self.status_lbl.configure(text=f"Erreur mise à jour : {err}", text_color="#FF5252")
        messagebox.showerror("Erreur de mise à jour", f"Impossible d'installer la mise à jour automatiquement :\n{err}")

    # --- Contexte & Dossier de jeu ---
    def _check_initial_context(self):
        cwd = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
        exes = SteamBackend.scan_executables(cwd)
        if exes:
            self._load_game_folder(cwd)

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Sélectionner le dossier racine du jeu")
        if folder:
            self._load_game_folder(Path(folder))

    def _load_game_folder(self, folder: Path):
        self.game_dir = folder
        self.dir_entry.delete(0, "end")
        self.dir_entry.insert(0, str(folder))

        self.exe_list = SteamBackend.scan_executables(folder)
        if self.exe_list:
            self.exe_combo.configure(values=[p.name for p in self.exe_list])
            self.exe_combo.set(self.exe_list[0].name)
        else:
            self.exe_combo.configure(values=["Aucun exécutable trouvé"])
            self.exe_combo.set("Aucun exécutable trouvé")

        self.name_entry.delete(0, "end")
        self.name_entry.insert(0, folder.name)

        is_local_vr = SteamBackend.detect_local_vr(folder)
        self.vr_var.set(is_local_vr)
        self.vr_badge.configure(text="🥽 Jeu VR détecté" if is_local_vr else "")

        local_id, source_file = SteamBackend.detect_local_appid(folder)
        if local_id:
            self.appid_entry.delete(0, "end")
            self.appid_entry.insert(0, local_id)
            self.status_lbl.configure(text=f"AppID détecté localement ({source_file}) : {local_id}", text_color=ACCENT_GREEN)
            self._verify_api_vr(local_id)
            self._load_previews()
        else:
            self._trigger_search()

    def _verify_api_vr(self, appid: str):
        def worker():
            api_vr = SteamBackend.check_steam_api_vr(appid)
            if api_vr:
                self.after(0, lambda: self._set_vr_detected("🥽 Compatible VR (Steam Store)"))

        threading.Thread(target=worker, daemon=True).start()

    def _set_vr_detected(self, label_text: str):
        self.vr_var.set(True)
        self.vr_badge.configure(text=label_text)

    def _trigger_search(self):
        query = self.name_entry.get().strip()
        if not query:
            return
        self.status_lbl.configure(text=f"Recherche de '{query}' sur Steam...", text_color=ACCENT_BLUE)

        def worker():
            try:
                items = SteamBackend.search_steam_store(query)
                self.after(0, lambda: self._apply_search_results(items))
            except Exception as exc:
                err_msg = str(exc) or type(exc).__name__
                self.after(0, lambda: self.status_lbl.configure(text=f"Erreur recherche : {err_msg}", text_color="#FF5252"))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_search_results(self, items: list[dict]):
        self.search_results = items
        if not items:
            self.results_combo.configure(values=["Aucun résultat trouvé"])
            self.results_combo.set("Aucun résultat trouvé")
            self.status_lbl.configure(text="Aucun jeu trouvé automatiquement. Saisissez l'AppID manuellement.", text_color=ACCENT_ORANGE)
            return

        labels = [f"{it['name']} (ID: {it['id']})" for it in items]
        self.results_combo.configure(values=labels)
        self.results_combo.set(labels[0])

        first_id = str(items[0]["id"])
        self.appid_entry.delete(0, "end")
        self.appid_entry.insert(0, first_id)
        self.status_lbl.configure(text=f"Correspondance trouvée : {items[0]['name']} ({first_id})", text_color=ACCENT_GREEN)
        self._verify_api_vr(first_id)
        self._load_previews()

    def _on_result_selected(self, choice: str):
        m = re.search(r"\(ID:\s*(\d+)\)$", choice)
        if m:
            selected_id = m.group(1)
            self.appid_entry.delete(0, "end")
            self.appid_entry.insert(0, selected_id)
            self._verify_api_vr(selected_id)
            self._load_previews()

    def _load_previews(self):
        appid = self.appid_entry.get().strip()
        if not appid.isdigit():
            return

        urls = [
            (f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg", (82, 122)),
            (f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_hero.jpg", (155, 50)),
            (f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/logo.png", (135, 72)),
            (f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg", (145, 68)),
        ]

        def worker():
            loaded = []
            for url, size in urls:
                try:
                    r = requests.get(url, timeout=6)
                    r.raise_for_status()
                    pil_img = Image.open(BytesIO(r.content))
                    ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)
                    loaded.append(ctk_img)
                except Exception:
                    loaded.append(None)
            self.after(0, lambda: self._render_previews(loaded))

        threading.Thread(target=worker, daemon=True).start()

    def _render_previews(self, images):
        self.preview_refs = images
        for lbl, img in zip(self.preview_labels, images):
            if img:
                lbl.configure(image=img, text="")
            else:
                lbl.configure(image=None, text="Non disponible")

    def _start_injection(self):
        if not self.steam_path or not self.user_dir:
            messagebox.showerror("Erreur", "Installation Steam ou profil utilisateur introuvable.")
            return
        if not self.game_dir or not self.exe_list:
            messagebox.showwarning("Attention", "Veuillez sélectionner un dossier de jeu valide contenant un .exe.")
            return

        appid = self.appid_entry.get().strip()
        app_name = self.name_entry.get().strip()
        if not appid.isdigit() or not app_name:
            messagebox.showwarning("Attention", "Veuillez renseigner le nom du jeu et un Steam AppID numérique valide.")
            return

        selected_exe_name = self.exe_combo.get()
        exe_path = next((p for p in self.exe_list if p.name == selected_exe_name), self.exe_list[0])
        is_vr = self.vr_var.get()

        self.btn_inject.configure(state="disabled")
        self.status_lbl.configure(text="Fermeture obligatoire de Steam / SteamVR en cours...", text_color=ACCENT_BLUE)

        def worker():
            try:
                SteamBackend.force_close_steam(self.steam_path)

                self.after(0, lambda: self.status_lbl.configure(text="Injection du raccourci dans Steam...", text_color=ACCENT_BLUE))
                non_steam_id = SteamBackend.inject_shortcut(self.user_dir, app_name, exe_path, is_vr=is_vr)

                if is_vr:
                    self.after(0, lambda: self.status_lbl.configure(text="Enregistrement du manifeste OpenVR dans SteamVR...", text_color=ACCENT_BLUE))
                    SteamBackend.register_steamvr_app(self.steam_path, non_steam_id, app_name, exe_path)

                self.after(0, lambda: self.status_lbl.configure(text="Téléchargement des 4 jaquettes officielles...", text_color=ACCENT_BLUE))
                grid_dir = self.user_dir / "config" / "grid"
                grid_dir.mkdir(parents=True, exist_ok=True)

                assets = [
                    (f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg", f"{non_steam_id}p.jpg"),
                    (f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_hero.jpg", f"{non_steam_id}_hero.jpg"),
                    (f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/logo.png", f"{non_steam_id}_logo.png"),
                    (f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg", f"{non_steam_id}.jpg"),
                ]

                ok_count = 0
                for url, filename in assets:
                    try:
                        r = requests.get(url, timeout=8)
                        r.raise_for_status()
                        (grid_dir / filename).write_bytes(r.content)
                        ok_count += 1
                    except Exception:
                        pass

                self.after(0, lambda: self.status_lbl.configure(text="Relancement automatique de Steam...", text_color=ACCENT_BLUE))
                SteamBackend.launch_steam(self.steam_path)

                self.after(0, lambda: self._on_injection_done(app_name, non_steam_id, ok_count, is_vr))
            except Exception as exc:
                err_msg = str(exc) or f"{type(exc).__name__} (aucun détail renvoyé)"
                self.after(0, lambda: self._on_injection_error(err_msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_injection_done(self, app_name: str, non_steam_id: int, ok_count: int, is_vr: bool):
        self.btn_inject.configure(state="normal")
        vr_txt = " + SteamVR (Manifeste VR)" if is_vr else ""
        self.status_lbl.configure(
            text=f"Terminé ! '{app_name}' ajouté (ID: {non_steam_id}){vr_txt} — {ok_count}/4 visuels.",
            text_color=ACCENT_GREEN,
        )
        messagebox.showinfo(
            "Opération terminée",
            f"'{app_name}' a été ajouté à votre bibliothèque Steam{vr_txt} avec {ok_count}/4 visuels.\n\nSteam vient d'être relancé automatiquement.",
        )

    def _on_injection_error(self, err: str):
        self.btn_inject.configure(state="normal")
        self.status_lbl.configure(text=f"Erreur : {err}", text_color="#FF5252")
        messagebox.showerror("Erreur lors de l'injection", err)


if __name__ == "__main__":
    app = App()
    app.mainloop()