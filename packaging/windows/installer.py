from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


APP_NAME = "UDME Agent"
SERVER_URL = "https://udme-ollm.onrender.com"


def _payload_path() -> Path:
    bundle_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return bundle_dir / "payload" / "udme-agent.exe"


def install_agent(destination: Path, *, create_shortcuts: bool = True) -> Path:
    payload = _payload_path()
    if not payload.is_file():
        raise FileNotFoundError(f"Agent executable is missing from installer: {payload}")

    target = destination.expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    executable = target / "udme-agent.exe"

    fd, temp_name = tempfile.mkstemp(prefix=".udme-agent-", suffix=".tmp", dir=target)
    os.close(fd)
    try:
        shutil.copyfile(payload, temp_name)
        os.replace(temp_name, executable)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)

    launcher = (
        "@echo off\r\n"
        f'"{executable}" find-databases --gui --upload %*\r\n'
    )
    if create_shortcuts:
        appdata = os.environ.get("APPDATA")
        if appdata:
            start_menu = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME
            start_menu.mkdir(parents=True, exist_ok=True)
            (start_menu / "Démarrer UDME Agent.cmd").write_text(launcher, encoding="utf-8")

        desktop = Path.home() / "Desktop"
        if desktop.is_dir():
            (desktop / "UDME Agent.cmd").write_text(launcher, encoding="utf-8")

    instructions = (
        "UDME Agent est installé.\n\n"
        "1. Connectez-vous au portail UDME et générez un nouveau jeton d'enrôlement.\n"
        "2. Dans PowerShell, exécutez :\n\n"
        "$token = Read-Host \"Jeton d'enrôlement\"\n"
        f'& "{executable}" enroll --server {SERVER_URL} --token $token\n'
        "Remove-Variable token\n\n"
        "3. Recherchez les bases avec « Démarrer UDME Agent » dans le menu Démarrer.\n"
        "Le jeton est à usage unique. Ne le partagez pas. Les identifiants de l'agent "
        "sont stockés dans %USERPROFILE%\\.udme\\agent.json."
    )
    (target / "LISEZ-MOI.txt").write_text(instructions, encoding="utf-8")
    return executable


def _self_test() -> None:
    payload = _payload_path()
    if not payload.is_file():
        raise FileNotFoundError(f"Bundled agent executable not found: {payload}")

    with tempfile.TemporaryDirectory(prefix="udme-installer-test-") as temp_dir:
        installed = install_agent(Path(temp_dir) / APP_NAME, create_shortcuts=False)
        result = subprocess.run(
            [str(installed), "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 or "usage:" not in result.stdout.lower():
            raise RuntimeError(f"Installed agent smoke test failed: {result.stderr}")


def _show_installer() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("Installation de UDME Agent")
    root.resizable(False, False)

    default_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / APP_NAME
    destination = tk.StringVar(value=str(default_dir))
    desktop_shortcut = tk.BooleanVar(value=True)

    frame = ttk.Frame(root, padding=18)
    frame.grid(sticky="nsew")
    ttk.Label(frame, text="Installer UDME Agent", font=("", 14, "bold")).grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
    )
    ttk.Label(
        frame,
        text=(
            "L'agent analyse localement les métadonnées des bases choisies. "
            "Il ne lit ni n'envoie les lignes de données."
        ),
        wraplength=460,
    ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 14))
    ttk.Label(frame, text="Dossier d'installation :").grid(row=2, column=0, columnspan=2, sticky="w")
    ttk.Entry(frame, textvariable=destination, width=58).grid(row=3, column=0, sticky="ew", pady=5)

    def browse() -> None:
        selected = filedialog.askdirectory(initialdir=destination.get(), mustexist=False)
        if selected:
            destination.set(selected)

    ttk.Button(frame, text="Parcourir…", command=browse).grid(row=3, column=1, padx=(8, 0), pady=5)
    ttk.Checkbutton(
        frame,
        text="Créer les raccourcis du menu Démarrer et du Bureau",
        variable=desktop_shortcut,
    ).grid(
        row=4, column=0, columnspan=2, sticky="w", pady=(5, 14)
    )

    def install() -> None:
        try:
            path_text = destination.get().strip()
            if not path_text:
                raise ValueError("Choisissez un dossier d'installation.")
            path = Path(path_text)
            if (path / "udme-agent.exe").exists() and not messagebox.askyesno(
                "Confirmation", "Une installation existe déjà. La remplacer ?", parent=root
            ):
                return
            installed = install_agent(path, create_shortcuts=desktop_shortcut.get())
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror("Installation impossible", str(exc), parent=root)
            return

        messagebox.showinfo(
            "Installation terminée",
            f"Agent installé dans :\n{installed.parent}\n\n"
            "Consultez LISEZ-MOI.txt dans ce dossier pour l'enrôlement. "
            "Générez un nouveau jeton dans le portail ; ne le partagez pas.",
            parent=root,
        )
        root.destroy()

    ttk.Button(frame, text="Installer", command=install).grid(row=5, column=1, sticky="e")
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Installateur UDME Agent pour Windows")
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return
    if os.name != "nt":
        raise SystemExit("Cet installateur est prévu pour Windows.")
    _show_installer()


if __name__ == "__main__":
    main()
