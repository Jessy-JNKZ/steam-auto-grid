"""
Steam Auto-Grid — Non-Steam Shortcut & Artwork Injector
Développé par Jessy JONKISZ (https://github.com/Jessy-JNKZ | https://x.com/JNKZJessy)
"""

import os
import re
import sys
import time
import ctypes
import struct
import random
import shutil
import winreg
import webbrowser
import threading
import subprocess
from io import BytesIO
from pathlib import Path

import requests
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image

# Configuration globale de l'interface (Dark Mode)
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# Couleurs personnalisées
BG_DARK = "#12151C"
CARD_BG = "#1B202B"
ACCENT_GREEN = "#00E676"
ACCENT_GREEN_HOVER = "#00C853"
ACCENT_BLUE = "#1A9FFF"
TEXT_MUTED = "#8F98A0"


class SteamBackend:
    """Gère la détection Steam, le cycle de vie du processus, shortcuts.vdf et l'API."""

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
        """Vérifie via PowerShell / WMI si un processus steam.exe est actif."""
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "if (Get-Process -Name 'steam' -ErrorAction SilentlyContinue) { 'RUNNING' }"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return "RUNNING" in res.stdout
        except Exception:
            return False

    @staticmethod
    def force_close_steam(steam_path: Path):
        """Force la fermeture complète de Steam (avec élévation UAC si Steam tourne en admin)."""
        if not SteamBackend.is_steam_running():
            return

        # Tentative 1 : Arrêt propre via steam.exe -shutdown
        steam_exe = steam_path / "steam.exe"
        if steam_exe.exists():
            subprocess.Popen([str(steam_exe), "-shutdown"], creationflags=subprocess.CREATE_NO_WINDOW)

        for _ in range(6):
            time.sleep(1)
            if not SteamBackend.is_steam_running():
                time.sleep(1)
                return

        # Tentative 2 : Arrêt forcé standard via PowerShell
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Stop-Process -Name 'steam','steamwebhelper' -Force -ErrorAction SilentlyContinue"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        time.sleep(2)

        if not SteamBackend.is_steam_running():
            return

        # Tentative 3 : Si Steam tourne en Administrateur (Accès refusé en mode normal), demande UAC
        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "taskkill.exe",
            "/F /T /IM steam.exe /IM steamwebhelper.exe",
            None,
            0,  # SW_HIDE
        )

        for _ in range(8):
            time.sleep(1)
            if not SteamBackend.is_steam_running():
                time.sleep(1)
                return

        raise RuntimeError("Steam est toujours actif. Veuillez le fermer manuellement (Quitter Steam) puis réessayer.")

    @staticmethod
    def launch_steam(steam_path: Path):
        """Relance Steam proprement."""
        steam_exe = steam_path / "steam.exe"
        if steam_exe.exists():
            subprocess.Popen([str(steam_exe)], creationflags=subprocess.CREATE_NO_WINDOW)

    @staticmethod
    def scan_executables(game_dir: Path) -> list[Path]:
        ignore = re.compile(r"(unins|setup|redist|crash|unity|dxweb|vc_redist)", re.IGNORECASE)
        return [p for p in game_dir.glob("*.exe") if not ignore.search(p.name)]

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
    def inject_shortcut(user_dir: Path, app_name: str, exe_path: Path) -> int:
        config_dir = user_dir / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        shortcuts_file = config_dir / "shortcuts.vdf"

        if shortcuts_file.exists():
            shutil.copy2(shortcuts_file, config_dir / "shortcuts.vdf.bak")
            raw = shortcuts_file.read_bytes()
        else:
            raw = b"\x00shortcuts\x00\x08\x08"

        # Vérifie si l'exécutable est déjà enregistré
        text_latin = raw.decode("latin-1")
        target_esc = re.escape(str(exe_path))
        for chunk in text_latin.split("\x02appid\x00")[1:]:
            if len(chunk) >= 4 and re.search(target_esc, chunk, re.IGNORECASE):
                existing_id = struct.unpack("<I", chunk[:4].encode("latin-1"))[0]
                return existing_id

        # Nouvel index et génération de l'AppID non-Steam (bit 31 à 1)
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
        entry += vdf_int("OpenVR", 0)
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


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Steam Auto-Grid — Non-Steam Shortcut & Artwork Injector | par Jessy JONKISZ")
        self.geometry("860x735")
        self.minsize(820, 700)
        self.configure(fg_color=BG_DARK)

        self.steam_path = SteamBackend.get_steam_path()
        self.user_dir = SteamBackend.get_active_userdata(self.steam_path) if self.steam_path else None
        self.game_dir: Path | None = None
        self.exe_list: list[Path] = []
        self.search_results: list[dict] = []
        self.preview_refs = []

        self._build_ui()
        self._check_initial_context()

    def _build_ui(self):
        # --- En-tête ---
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(18, 8))

        title_lbl = ctk.CTkLabel(
            header,
            text="STEAM AUTO-GRID",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
            text_color="white",
        )
        title_lbl.pack(side="left")

        subtitle_lbl = ctk.CTkLabel(
            header,
            text="  |  Ajout automatique de jeux non-Steam & jaquettes officielles",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED,
        )
        subtitle_lbl.pack(side="left", pady=(4, 0))

        self.steam_badge = ctk.CTkLabel(
            header,
            text="● Steam détecté" if self.user_dir else "● Steam introuvable",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=ACCENT_GREEN if self.user_dir else "#FF5252",
        )
        self.steam_badge.pack(side="right")

        # --- Carte 1 : Dossier & Exécutable ---
        card_folder = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=12)
        card_folder.pack(fill="x", padx=24, pady=7)

        ctk.CTkLabel(
            card_folder, text="1. Dossier du jeu & Exécutable", font=ctk.CTkFont(size=14, weight="bold"), text_color="white"
        ).pack(anchor="w", padx=16, pady=(12, 6))

        row_dir = ctk.CTkFrame(card_folder, fg_color="transparent")
        row_dir.pack(fill="x", padx=16, pady=(0, 8))

        self.dir_entry = ctk.CTkEntry(row_dir, placeholder_text="Sélectionnez le dossier racine du jeu...", height=36)
        self.dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkButton(
            row_dir, text="Parcourir...", width=120, height=36, fg_color=ACCENT_BLUE, command=self._browse_folder
        ).pack(side="right")

        row_exe = ctk.CTkFrame(card_folder, fg_color="transparent")
        row_exe.pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkLabel(row_exe, text="Exécutable (.exe) :", text_color=TEXT_MUTED, width=130, anchor="w").pack(side="left")
        self.exe_combo = ctk.CTkComboBox(row_exe, values=["Aucun dossier sélectionné"], height=32, state="readonly")
        self.exe_combo.pack(side="left", fill="x", expand=True)

        # --- Carte 2 : Identification Steam ---
        card_id = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=12)
        card_id.pack(fill="x", padx=24, pady=7)

        ctk.CTkLabel(
            card_id, text="2. Configuration & Recherche d'ID Steam", font=ctk.CTkFont(size=14, weight="bold"), text_color="white"
        ).pack(anchor="w", padx=16, pady=(12, 6))

        row_name = ctk.CTkFrame(card_id, fg_color="transparent")
        row_name.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkLabel(row_name, text="Nom dans Steam :", text_color=TEXT_MUTED, width=130, anchor="w").pack(side="left")
        self.name_entry = ctk.CTkEntry(row_name, placeholder_text="Nom affiché dans votre bibliothèque", height=34)
        self.name_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkButton(
            row_name, text="Rechercher ID", width=120, height=34, fg_color="#2C3444", hover_color="#3A4458", command=self._trigger_search
        ).pack(side="right")

        row_appid = ctk.CTkFrame(card_id, fg_color="transparent")
        row_appid.pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkLabel(row_appid, text="Steam AppID :", text_color=TEXT_MUTED, width=130, anchor="w").pack(side="left")
        self.appid_entry = ctk.CTkEntry(row_appid, placeholder_text="Ex: 620980", width=130, height=34)
        self.appid_entry.pack(side="left", padx=(0, 10))

        self.results_combo = ctk.CTkComboBox(
            row_appid,
            values=["Résultats de recherche Steam..."],
            height=34,
            state="readonly",
            command=self._on_result_selected,
        )
        self.results_combo.pack(side="left", fill="x", expand=True)

        # --- Carte 3 : Aperçu des 4 visuels ---
        card_prev = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=12)
        card_prev.pack(fill="both", expand=True, padx=24, pady=7)

        prev_header = ctk.CTkFrame(card_prev, fg_color="transparent")
        prev_header.pack(fill="x", padx=16, pady=(10, 4))

        ctk.CTkLabel(
            prev_header, text="3. Aperçu des visuels (Couverture, Hero, Logo, Header)", font=ctk.CTkFont(size=14, weight="bold"), text_color="white"
        ).pack(side="left")

        ctk.CTkButton(
            prev_header, text="Prévisualiser", width=110, height=28, fg_color="#2C3444", command=self._load_previews
        ).pack(side="right")

        self.preview_box = ctk.CTkFrame(card_prev, fg_color="#141820", corner_radius=8)
        self.preview_box.pack(fill="both", expand=True, padx=16, pady=(4, 14))

        self.preview_labels = []
        titles = ["Couverture (600x900)", "Arrière-plan (Hero)", "Logo (PNG)", "Grande couverture"]
        for i, t in enumerate(titles):
            col = ctk.CTkFrame(self.preview_box, fg_color="transparent")
            col.pack(side="left", fill="both", expand=True, padx=6, pady=8)
            lbl_img = ctk.CTkLabel(col, text="Aucun aperçu", text_color=TEXT_MUTED, height=120)
            lbl_img.pack(expand=True)
            ctk.CTkLabel(col, text=t, font=ctk.CTkFont(size=11), text_color=TEXT_MUTED).pack()
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
            text_color="#0B0E14",
            height=42,
            width=310,
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
            text_color="#8F98A0",
            cursor="hand2",
        )
        dev_lbl.pack(side="right")
        dev_lbl.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/Jessy-JNKZ"))

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

        local_id, source_file = SteamBackend.detect_local_appid(folder)
        if local_id:
            self.appid_entry.delete(0, "end")
            self.appid_entry.insert(0, local_id)
            self.status_lbl.configure(text=f"AppID détecté localement ({source_file}) : {local_id}", text_color=ACCENT_GREEN)
            self._load_previews()
        else:
            self._trigger_search()

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
            self.status_lbl.configure(text="Aucun jeu trouvé automatiquement. Saisissez l'AppID manuellement.", text_color="#FFB74D")
            return

        labels = [f"{it['name']} (ID: {it['id']})" for it in items]
        self.results_combo.configure(values=labels)
        self.results_combo.set(labels[0])

        first_id = str(items[0]["id"])
        self.appid_entry.delete(0, "end")
        self.appid_entry.insert(0, first_id)
        self.status_lbl.configure(text=f"Correspondance trouvée : {items[0]['name']} ({first_id})", text_color=ACCENT_GREEN)
        self._load_previews()

    def _on_result_selected(self, choice: str):
        m = re.search(r"\(ID:\s*(\d+)\)$", choice)
        if m:
            self.appid_entry.delete(0, "end")
            self.appid_entry.insert(0, m.group(1))
            self._load_previews()

    def _load_previews(self):
        appid = self.appid_entry.get().strip()
        if not appid.isdigit():
            return

        urls = [
            (f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg", (85, 128)),
            (f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_hero.jpg", (160, 52)),
            (f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/logo.png", (140, 75)),
            (f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg", (150, 70)),
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

        self.btn_inject.configure(state="disabled")
        self.status_lbl.configure(text="Fermeture obligatoire de Steam en cours...", text_color=ACCENT_BLUE)

        def worker():
            try:
                # 1. Fermeture obligatoire de Steam avant toute modification
                SteamBackend.force_close_steam(self.steam_path)

                self.after(0, lambda: self.status_lbl.configure(text="Injection du raccourci dans Steam...", text_color=ACCENT_BLUE))
                non_steam_id = SteamBackend.inject_shortcut(self.user_dir, app_name, exe_path)

                # 2. Téléchargement et injection des 4 visuels
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

                # 3. Relancement automatique de Steam après injection
                self.after(0, lambda: self.status_lbl.configure(text="Relancement automatique de Steam...", text_color=ACCENT_BLUE))
                SteamBackend.launch_steam(self.steam_path)

                self.after(0, lambda: self._on_injection_done(app_name, non_steam_id, ok_count))
            except Exception as exc:
                err_msg = str(exc) or f"{type(exc).__name__} (aucun détail renvoyé)"
                self.after(0, lambda: self._on_injection_error(err_msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_injection_done(self, app_name: str, non_steam_id: int, ok_count: int):
        self.btn_inject.configure(state="normal")
        self.status_lbl.configure(
            text=f"Terminé ! '{app_name}' ajouté (ID: {non_steam_id}) — {ok_count}/4 visuels injectés. Steam redémarré.",
            text_color=ACCENT_GREEN,
        )
        messagebox.showinfo(
            "Opération terminée",
            f"'{app_name}' a été ajouté à votre bibliothèque Steam avec {ok_count}/4 visuels.\n\nSteam vient d'être relancé automatiquement.",
        )

    def _on_injection_error(self, err: str):
        self.btn_inject.configure(state="normal")
        self.status_lbl.configure(text=f"Erreur : {err}", text_color="#FF5252")
        messagebox.showerror("Erreur lors de l'injection", err)


if __name__ == "__main__":
    app = App()
    app.mainloop()