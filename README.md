# Steam Auto-Grid

[🇫🇷 Français](#français) • [🇬🇧 English](#english)

![Steam Auto-Grid Preview](image.png)

---

## Français

Outil Windows léger avec interface moderne permettant d'ajouter automatiquement un jeu non-Steam à votre bibliothèque et d'injecter ses 4 visuels officiels (**Couverture 600x900**, **Bannière Hero**, **Logo transparent** et **Grande couverture Header**) en un clic.

### Fonctionnalités
- **Détection automatique de Steam** et du profil utilisateur actif via le Registre Windows.
- **Scan intelligent du dossier du jeu** : repère l'exécutable principal (en ignorant les désinstalleurs/redistribuables) et détecte automatiquement l'AppID Steam officiel via les fichiers locaux (`steam_appid.txt`, `.ini`) ou via l'API publique du magasin Steam.
- **Prévisualisation en temps réel** des 4 jaquettes avant l'injection.
- **Injection native dans `shortcuts.vdf`** avec sauvegarde de sécurité automatique (`shortcuts.vdf.bak`), fermeture forcée et relancement automatique de Steam, et prévention des doublons.

### Utilisation (Version compilée)
1. Téléchargez `Steam-Auto-Grid.exe` depuis l'onglet **Releases**.
2. Lancez l'application (ou placez-la directement dans le dossier d'un jeu pour une détection immédiate).
3. Vérifiez l'aperçu des jaquettes et cliquez sur **AJOUTER À STEAM & INJECTER LES IMAGES**.

### Compilation depuis les sources
Assurez-vous d'avoir Python 3.10+ installé, puis lancez simplement :
```bat
build.bat
```
L'exécutable autonome sera généré dans `dist\Steam-Auto-Grid.exe`.

---

## English

Lightweight Windows utility with a modern dark UI that automatically adds non-Steam games to your library and injects all 4 official artwork assets (**600x900 Cover**, **Hero Banner**, **Transparent Logo**, and **Header**) in one click.

### Features
- **Automatic Steam Detection:** Locates your Steam installation and active user profile via the Windows Registry.
- **Smart Game Folder Scan:** Identifies the main executable (filtering out uninstallers/redistributables) and detects the official Steam AppID from local files (`steam_appid.txt`, `.ini`) or via the Steam Store search API.
- **Live Artwork Preview:** Previews all 4 cover assets directly inside the interface before injecting.
- **Native `shortcuts.vdf` Injection:** Creates an automatic `shortcuts.vdf.bak` backup, safely closes and relaunches Steam automatically, and prevents duplicate entries.

### Usage (Compiled Release)
1. Download `Steam-Auto-Grid.exe` from the **Releases** tab.
2. Run the application anywhere (or place it inside a game's root folder for instant auto-detection).
3. Check the artwork preview and click **AJOUTER À STEAM & INJECTER LES IMAGES**.

### Build from Source
Make sure Python 3.10+ is installed, then run:
```bat
build.bat
```
The standalone executable will be generated in `dist\Steam-Auto-Grid.exe`.

---

## Auteur / Author
Développé par / Developed by **Jessy JONKISZ**  
- GitHub : [@Jessy-JNKZ](https://github.com/Jessy-JNKZ)  
- X (Twitter) : [@JNKZJessy](https://x.com/JNKZJessy)
