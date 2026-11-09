"""Optional Tk window (ships with Python on Windows): scan the PC, pick a file. Same engine as the CLI."""
from __future__ import annotations
import threading
from udme_core.finder import find_databases
from .picker import human


def pick_with_gui(roots=None, include_noise=False) -> str | None:
    import tkinter as tk
    from tkinter import ttk, messagebox
    root = tk.Tk(); root.title("UDME — choisir une base de données"); root.geometry("980x520")
    status = tk.StringVar(value="Recherche en cours… (lecture des en-têtes uniquement, rien n'est envoyé)")
    ttk.Label(root, textvariable=status).pack(anchor="w", padx=8, pady=6)
    cols = ("kind", "size", "hdr", "path")
    tv = ttk.Treeview(root, columns=cols, show="headings", selectmode="browse")
    for c, t, w in (("kind", "Type", 140), ("size", "Taille", 80), ("hdr", "En-tête", 80), ("path", "Chemin", 640)):
        tv.heading(c, text=t); tv.column(c, width=w)
    tv.pack(fill="both", expand=True, padx=8); result: list[str] = []; cancel = threading.Event(); cands = []
    def work():
        res = find_databases(roots, include_noise=include_noise, cancel=cancel,
                             progress=lambda n, f, d: root.after(0, status.set, f"{n:,} éléments parcourus · {f} trouvé(s) · {d[:70]}"))
        def fill():
            cands.extend(res)
            for c in res: tv.insert("", "end", values=(c.kind, human(c.size), "verrouillé" if c.locked else ("✔" if c.header_verified else "extension"), c.path))
            status.set(f"{len(res)} fichier(s). Sélectionnez-en un puis « Utiliser ce fichier ».")
        root.after(0, fill)
    threading.Thread(target=work, daemon=True).start()
    def use():
        s = tv.selection()
        if not s: return messagebox.showinfo("UDME", "Sélectionnez un fichier.")
        p = tv.item(s[0])["values"][3]
        if messagebox.askyesno("Confirmer", f"Utiliser :\n{p}\n\nAucune écriture ne sera faite sur ce fichier."): result.append(str(p)); root.destroy()
    def stop(): cancel.set(); root.destroy()
    bar = ttk.Frame(root); bar.pack(fill="x", padx=8, pady=8)
    ttk.Button(bar, text="Utiliser ce fichier", command=use).pack(side="right"); ttk.Button(bar, text="Annuler", command=stop).pack(side="right", padx=6)
    root.protocol("WM_DELETE_WINDOW", stop); root.mainloop()
    return result[0] if result else None


def ask_enrollment_token() -> str | None:
    import tkinter as tk
    from tkinter import simpledialog

    root = tk.Tk()
    root.withdraw()
    try:
        return simpledialog.askstring(
            "Connexion au portail UDME",
            "Collez le jeton d'enrôlement généré sur le portail UDME.\n"
            "Le jeton est à usage unique et sa saisie est masquée :",
            show="*",
            parent=root,
        )
    finally:
        root.destroy()


def confirm_action(title: str, message: str) -> bool:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    try:
        return messagebox.askyesno(title, message, parent=root)
    finally:
        root.destroy()


def show_message(title: str, message: str) -> None:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    try:
        messagebox.showinfo(title, message, parent=root)
    finally:
        root.destroy()
