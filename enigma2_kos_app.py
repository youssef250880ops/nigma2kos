# -*- coding: utf-8 -*-
"""
Enigma2 KingOfSat - application portable.
1. Se connecte à KingOfSat et affiche la liste des satellites.
2. Vous cochez les satellites, les qualités (4K/HD/SD/Radio), les options.
3. Télécharge les chaînes et crée lamedb + bouquets prêts pour /etc/enigma2/.
"""
import os, sys, threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import kos_engine as K

APP_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
CACHE = os.path.join(APP_DIR, "cache")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Enigma2 KingOfSat - téléchargement des chaînes")
        self.geometry("920x700")
        self.sats = []
        self.checked = {}

        top = ttk.LabelFrame(self, text="1. Site source")
        top.pack(fill="x", padx=8, pady=6)
        self.base = tk.StringVar(value=K.BASE)
        ttk.Entry(top, textvariable=self.base, width=40).pack(side="left", padx=4, pady=4)
        ttk.Button(top, text="Charger les satellites", command=self.load_sats).pack(side="left", padx=4)
        self.flt = tk.StringVar()
        ttk.Label(top, text="Filtre :").pack(side="left", padx=(16, 2))
        e = ttk.Entry(top, textvariable=self.flt, width=18)
        e.pack(side="left")
        e.bind("<KeyRelease>", lambda ev: self.fill())

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=8)
        left = ttk.LabelFrame(mid, text="2. Satellites (cliquer pour cocher)")
        left.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(left, columns=("sat", "n", "f"), show="headings", selectmode="none")
        for col, txt, w in (("sat", "Position / satellites", 380), ("n", "Chaînes", 70), ("f", "Gratuites", 70)):
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=w, anchor="w" if col == "sat" else "e")
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(left, command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Button-1>", self.toggle)

        right = ttk.LabelFrame(mid, text="3. Préférences")
        right.pack(side="left", fill="y", padx=6)
        self.q = {k: tk.BooleanVar(value=(k != "Radio")) for k in ("4K", "HD", "SD", "Radio")}
        for k, v in self.q.items():
            ttk.Checkbutton(right, text=k, variable=v).pack(anchor="w", padx=8, pady=1)
        self.fta = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text="Chaînes gratuites\nuniquement (Clear)", variable=self.fta).pack(anchor="w", padx=8, pady=4)
        ttk.Label(right, text="Pays (ex : Morocco, France)\nvide = tous").pack(anchor="w", padx=8)
        self.country = tk.StringVar()
        ttk.Entry(right, textvariable=self.country, width=24).pack(padx=8, pady=2)
        ttk.Separator(right).pack(fill="x", pady=6)
        self.per_sat = tk.BooleanVar(value=True)
        self.per_cat = tk.BooleanVar(value=True)
        self.per_q = tk.BooleanVar(value=True)
        ttk.Label(right, text="Bouquets :").pack(anchor="w", padx=8)
        ttk.Checkbutton(right, text="par satellite", variable=self.per_sat).pack(anchor="w", padx=16)
        ttk.Checkbutton(right, text="par catégorie\n(Sport, News…)", variable=self.per_cat).pack(anchor="w", padx=16)
        ttk.Checkbutton(right, text="par qualité (4K/HD/SD)", variable=self.per_q).pack(anchor="w", padx=16)
        ttk.Separator(right).pack(fill="x", pady=6)
        self.force = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text="Ignorer le cache (24 h)", variable=self.force).pack(anchor="w", padx=8)
        ttk.Button(right, text="Tout décocher", command=lambda: self.set_all(False)).pack(fill="x", padx=8, pady=(8, 2))

        bot = ttk.LabelFrame(self, text="4. Téléchargement et export")
        bot.pack(fill="x", padx=8, pady=6)
        self.out = tk.StringVar(value=os.path.join(APP_DIR, "enigma2_export"))
        ttk.Entry(bot, textvariable=self.out).pack(side="left", fill="x", expand=True, padx=4, pady=4)
        ttk.Button(bot, text="Parcourir…", command=self.pick_out).pack(side="left", padx=2)
        self.go = ttk.Button(bot, text="Télécharger et exporter", command=self.start)
        self.go.pack(side="left", padx=4)
        self.pb = ttk.Progressbar(self)
        self.pb.pack(fill="x", padx=8)
        self.logbox = tk.Text(self, height=8)
        self.logbox.pack(fill="x", padx=8, pady=8)
        self.log("Cliquez sur « Charger les satellites ».")

    # ---------------------------------------------------------------- utils
    def log(self, m):
        self.logbox.insert("end", m + "\n")
        self.logbox.see("end")

    def ui(self, fn, *a):
        self.after(0, fn, *a)

    def pick_out(self):
        d = filedialog.askdirectory()
        if d:
            self.out.set(d)

    # ---------------------------------------------------------------- liste
    def load_sats(self):
        threading.Thread(target=self._load_sats, daemon=True).start()

    def _load_sats(self):
        try:
            base = self.base.get().rstrip("/")
            self.ui(self.log, "Connexion à %s …" % base)
            html = K.fetch(base + "/satellites", CACHE, force=self.force.get())
            self.sats = K.parse_satellites(html, base)
            if not self.sats:
                raise RuntimeError("Aucun satellite reconnu : la page a peut-être changé de structure.")
            self.checked = {s["pos"]: False for s in self.sats}
            self.ui(self.fill)
            self.ui(self.log, "%d positions orbitales trouvées." % len(self.sats))
        except Exception as e:
            self.ui(messagebox.showerror, "Erreur", "%s\n\nVérifiez la connexion Internet et l'adresse." % e)

    def label(self, s):
        return ("☑  " if self.checked.get(s["pos"]) else "☐  ") + "%s   %s" % (s["pos"], ", ".join(s["names"]))

    def fill(self):
        self.tree.delete(*self.tree.get_children())
        f = self.flt.get().strip().lower()
        for s in self.sats:
            if f and f not in (s["pos"] + " " + " ".join(s["names"])).lower():
                continue
            self.tree.insert("", "end", iid=s["pos"], values=(self.label(s), s["channels"], s["fta"]))

    def toggle(self, ev):
        iid = self.tree.identify_row(ev.y)
        if iid in self.checked:
            self.checked[iid] = not self.checked[iid]
            s = next(x for x in self.sats if x["pos"] == iid)
            self.tree.item(iid, values=(self.label(s), s["channels"], s["fta"]))

    def set_all(self, state):
        for k in self.checked:
            self.checked[k] = state
        self.fill()

    # ---------------------------------------------------------------- export
    def start(self):
        sel = [s for s in self.sats if self.checked.get(s["pos"])]
        quals = {k for k, v in self.q.items() if v.get()}
        if not sel or not quals:
            return messagebox.showwarning("Info", "Cochez au moins un satellite et une qualité.")
        self.go.state(["disabled"])
        threading.Thread(target=self._run, args=(sel, quals), daemon=True).start()

    def _run(self, sel, quals):
        try:
            data = {}
            self.ui(self.pb.configure, {"maximum": len(sel), "value": 0})
            for i, s in enumerate(sel, 1):
                self.ui(self.log, "[%d/%d] %s %s" % (i, len(sel), s["pos"], ", ".join(s["names"])))
                html = K.fetch(s["url"], CACHE, force=self.force.get())
                tps = K.parse_pos_page(html, s["pos"])
                n = sum(len(t["channels"]) for t in tps)
                self.ui(self.log, "    %d transpondeurs, %d chaînes lues" % (len(tps), n))
                data[tps[0]["label"] if tps else s["pos"]] = tps
                self.ui(self.pb.configure, {"value": i})
            countries = self.country.get().split(",") if self.country.get().strip() else []
            tp, sv = K.build_lists(data, quals, self.fta.get(), countries)
            if not sv:
                raise RuntimeError("Aucune chaîne ne correspond à vos choix (ou la page n'a pas pu être lue).")
            K.write_enigma2(self.out.get(), tp, sv, self.per_sat.get(), self.per_cat.get(),
                            self.per_q.get(), lambda m: self.ui(self.log, m))
            self.ui(messagebox.showinfo, "Terminé",
                    "Export terminé.\nCopiez le contenu du dossier dans /etc/enigma2/ du récepteur.")
        except Exception as e:
            self.ui(messagebox.showerror, "Erreur", str(e))
        finally:
            self.ui(self.go.state, ["!disabled"])


if __name__ == "__main__":
    App().mainloop()
