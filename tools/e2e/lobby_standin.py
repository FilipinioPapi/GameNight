#!/usr/bin/env python3
"""CI only: a stand-in Couch Play lobby window for couch_lobby_test.py (not Game Night's app). A dark window
with a magenta box where the live game should show. Prints "READY <box window> <lobby window>" once it's up."""
import tkinter as tk

BG, BOX = "#1a0f2e", "#ff00ff"
root = tk.Tk()
root.geometry("1000x700+0+0")
root.title("Couch Play lobby (stand-in)")
root.configure(bg=BG)
box = tk.Frame(root, width=512, height=448, bg=BOX)
box.place(x=440, y=140)
tk.Label(root, text="COUCH PLAY  K7QM2X", fg="white", bg=BG, font=("Arial", 24)).place(x=20, y=20)
root.update()
print("READY", box.winfo_id(), int(root.wm_frame(), 16), flush=True)
root.mainloop()
