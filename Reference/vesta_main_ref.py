import os
import subprocess
import sys
import logging
from datetime import datetime
import smtplib
from email.message import EmailMessage
import json
import sqlite3
import threading
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

# =========================
# CONFIGURATION & SETTINGS
# =========================

SETTINGS_FILE = "vestasettings.txt"

def load_settings():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        else:
            return {"DB_Path": "pro_list.db", "Document_Path": "Documents"}
    except Exception as e:
        print(f"Error loading settings: {e}")
        return {"DB_Path": "pro_list.db", "Document_Path": "Documents"}

settings = load_settings()
DB_PATH = settings.get("DB_Path", "pro_list.db")
DOCS_PATH = settings.get("Document_Path", "Documents")
SCRIPTS_DIR = "."
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
MAIN_LOG = os.path.join(LOG_DIR, "vesta_dashboard.log")

EMAIL_ENABLED = True
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_FROM = "mooncloudsoftwares@gmail.com"
EMAIL_TO = ["kumarapush123@gmail.com"]
EMAIL_PASSWORD = "ubhl xatb fcey ozap"

def init_database():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS applications (
                application_id TEXT PRIMARY KEY,
                description TEXT,
                address TEXT,
                ward TEXT,
                date_noticed TEXT,
                link TEXT,
                council TEXT,
                download_path TEXT,
                status TEXT DEFAULT 'pending',
                date_scraped TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id TEXT,
                file_name TEXT,
                file_path TEXT,
                file_url TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (application_id) REFERENCES applications (application_id)
            )
        ''')
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Database Initialization Error: {e}")
        return False

def reset_date():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE applications SET date_scraped = '2000-01-01'")
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error resetting dates: {e}")
        return False

def erase_db_data():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM documents")
        cursor.execute("DELETE FROM applications")
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error erasing database: {e}")
        return False

# =========================
# UI THEME CONSTANTS
# =========================

COLORS = {
    "bg_dark": "#121212",      # Deep charcoal
    "bg_medium": "#1e1e1e",    # VSCode style gray
    "bg_light": "#2d2d2d",     # Lighter accents
    "accent": "#007acc",       # Professional blue
    "accent_hover": "#005a9e",
    "fg_high": "#ffffff",      # White text
    "fg_med": "#cccccc",       # Light gray text
    "fg_low": "#858585",       # Dimmed text
    "success": "#4caf50",
    "error": "#f44336",
    "warning": "#ff9800",
    "info": "#007acc"
}

# =========================
# GUI APPLICATION CLASS
# =========================

class VestaDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Vesta Automation Dashboard")
        try:
            self.root.state('zoomed')  # Open maximized
        except:
            self.root.geometry("1100x750")
        self.root.configure(bg=COLORS["bg_dark"])

        self.setup_styles()
        self.create_widgets()
        self.create_reports_tab()
        self.create_settings_tab()
        
        self.scripts = []
        self.filtered_scripts = []
        self.results = []
        self.setup_logging()
        self.log_queue = queue.Queue()
        self.is_running = False
        
        self.load_scripts()
        self.prune_logs()
        self.update_log_from_queue()
        self.update_stats()

        # Handle Live Mode Auto-Start
        run_mode = settings.get("Run_Mode", "test").lower()
        if run_mode == "live":
            self.log("Live Mode detected: Auto-triggering scan in 2 seconds...", "INFO")
            self.root.after(2000, self.start_scraping)

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        
        # Configure Treeview
        style.configure("Treeview", 
                        background=COLORS["bg_medium"], 
                        foreground=COLORS["fg_med"], 
                        fieldbackground=COLORS["bg_medium"], 
                        borderwidth=0, 
                        font=("Segoe UI", 9),
                        rowheight=28)
        style.map("Treeview", background=[('selected', COLORS["accent"])], foreground=[('selected', COLORS["fg_high"])])
        style.configure("Treeview.Heading", background=COLORS["bg_light"], foreground=COLORS["fg_med"], font=("Segoe UI", 9, "bold"), borderwidth=0)
        
        # Progressbar
        style.configure("TProgressbar", thickness=8, background=COLORS["accent"], borderwidth=0, troughcolor=COLORS["bg_dark"])
        
        # Frames
        style.configure("TFrame", background=COLORS["bg_dark"])
        
        # Notebook (Tabs)
        style.configure("TNotebook", background=COLORS["bg_dark"], borderwidth=0, padding=0)
        style.configure("TNotebook.Tab", background=COLORS["bg_light"], foreground=COLORS["fg_low"], padding=[15, 5], font=("Segoe UI", 9))
        style.map("TNotebook.Tab", background=[("selected", COLORS["bg_medium"])], foreground=[("selected", COLORS["accent"])])

        # Reports View Style (Compact & Grid)
        style.configure("Reports.Treeview", 
                        background="#1a1a1a", 
                        foreground="#dcdcdc", 
                        fieldbackground="#1a1a1a", 
                        rowheight=22,
                        font=("Segoe UI", 8),
                        borderwidth=1)
        style.map("Reports.Treeview", background=[('selected', COLORS["accent"])])
        style.configure("Reports.Treeview.Heading", background=COLORS["bg_light"], font=("Segoe UI", 8, "bold"))

    def setup_logging(self):
        """Setup main persistent logging for the dashboard - FRESH for every run"""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(message)s",
            handlers=[
                logging.FileHandler(MAIN_LOG, encoding="utf-8", mode='w'),
                logging.StreamHandler(sys.stdout)
            ],
            force=True
        )
        logging.info("--- Dashboard Session Started ---")

    def create_widgets(self):
        # --- Top Header & Stats ---
        header_frame = tk.Frame(self.root, bg=COLORS["bg_medium"], height=80)
        header_frame.pack(fill="x", side="top")

        # Title & Branding
        brand_frame = tk.Frame(header_frame, bg=COLORS["bg_medium"])
        brand_frame.pack(side="left", padx=15, pady=10)
        tk.Label(brand_frame, text="VESTA", font=("Segoe UI Semibold", 18, "bold"), bg=COLORS["bg_medium"], fg=COLORS["accent"]).pack(side="left")
        tk.Label(brand_frame, text="SCRAPER", font=("Segoe UI", 14), bg=COLORS["bg_medium"], fg=COLORS["fg_med"]).pack(side="left", padx=(5,0), pady=(3,0))

        # Stats Dashboard
        self.stats_frame = tk.Frame(header_frame, bg=COLORS["bg_medium"])
        self.stats_frame.pack(side="right", padx=15)
        
        self.stat_labels = {}
        for i, (label, color) in enumerate([("Selected", COLORS["accent"]), ("Success", COLORS["success"]), ("Failed", COLORS["error"])]):
            frame = tk.Frame(self.stats_frame, bg=COLORS["bg_medium"], padx=10)
            frame.grid(row=0, column=i)
            tk.Label(frame, text=label, font=("Segoe UI", 8), bg=COLORS["bg_medium"], fg=COLORS["fg_low"]).pack()
            l = tk.Label(frame, text="0", font=("Segoe UI", 12, "bold"), bg=COLORS["bg_medium"], fg=color)
            l.pack()
            self.stat_labels[label] = l

        # --- Sub-Header / Toolbar ---
        toolbar = tk.Frame(self.root, bg=COLORS["bg_dark"], height=40)
        toolbar.pack(fill="x", padx=15, pady=(5, 2))

        # Search Bar
        search_label = tk.Label(toolbar, text="", font=("FontAwesome", 10), bg=COLORS["bg_dark"], fg=COLORS["fg_low"])
        search_label.pack(side="left", padx=(10, 5))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.filter_scripts())
        search_entry = tk.Entry(toolbar, textvariable=self.search_var, bg=COLORS["bg_medium"], fg=COLORS["fg_high"], insertbackground="white", borderwidth=0, font=("Segoe UI", 10), width=30)
        search_entry.pack(side="left", padx=5, pady=5)
        
        # Mass selection buttons
        tk.Button(toolbar, text="Select All", command=lambda: self.mass_toggle(True), bg=COLORS["bg_light"], fg=COLORS["fg_med"], borderwidth=0, activebackground=COLORS["bg_medium"], font=("Segoe UI", 9)).pack(side="left", padx=5)
        tk.Button(toolbar, text="Deselect All", command=lambda: self.mass_toggle(False), bg=COLORS["bg_light"], fg=COLORS["fg_med"], borderwidth=0, activebackground=COLORS["bg_medium"], font=("Segoe UI", 9)).pack(side="left", padx=5)
        
        # New Admin Tools
        tk.Button(toolbar, text="Reset Dates", command=self.handle_reset_dates, bg="#5d4037", fg=COLORS["fg_high"], borderwidth=0, activebackground=COLORS["bg_medium"], font=("Segoe UI", 9, "bold")).pack(side="left", padx=5)
        tk.Button(toolbar, text="Clear Data", command=self.handle_clear_data, bg="#b71c1c", fg=COLORS["fg_high"], borderwidth=0, activebackground=COLORS["bg_medium"], font=("Segoe UI", 9, "bold")).pack(side="left", padx=5)

        # --- Main Workspace (Tabs) ---
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=15, pady=(2, 5))

        # Tab 1: Control Center
        self.control_tab = tk.Frame(self.notebook, bg=COLORS["bg_dark"])
        self.notebook.add(self.control_tab, text=" Control Center ")

        paned = tk.PanedWindow(self.control_tab, orient="horizontal", bg=COLORS["bg_dark"], borderwidth=0, sashwidth=4, sashpad=0)
        paned.pack(fill="both", expand=True)

        # Left: Scraper List
        list_frame = tk.Frame(paned, bg=COLORS["bg_medium"])
        self.tree = ttk.Treeview(list_frame, columns=("File", "Run", "Status"), show="headings", selectmode="none")
        self.tree.heading("File", text="Council Program")
        self.tree.heading("Run", text="Run")
        self.tree.heading("Status", text="Current State")
        self.tree.column("File", width=160, anchor="w")
        self.tree.column("Run", width=50, anchor="center")
        self.tree.column("Status", width=120, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Button-1>", self.on_tree_click)
        paned.add(list_frame, width=380)

        # Right: Console / Output
        console_container = tk.Frame(paned, bg=COLORS["bg_dark"])
        tk.Label(console_container, text="Terminal Output", font=("Segoe UI Semibold", 9), bg=COLORS["bg_dark"], fg=COLORS["fg_low"]).pack(anchor="w", pady=(0, 5))
        self.console = scrolledtext.ScrolledText(console_container, bg="#0d0d0d", fg="#d4d4d4", font=("Consolas", 11), state="disabled", borderwidth=0, padx=10, pady=10)
        self.console.pack(fill="both", expand=True)
        paned.add(console_container)

        # Tab 2: Reports (formerly Statistics & History)
        self.reports_tab = tk.Frame(self.notebook, bg=COLORS["bg_dark"])
        self.notebook.add(self.reports_tab, text=" Reports ")

        # Tab 3: Settings
        self.settings_tab = tk.Frame(self.notebook, bg=COLORS["bg_dark"])
        self.notebook.add(self.settings_tab, text=" Settings ")

        # --- Footer ---
        footer = tk.Frame(self.root, bg=COLORS["bg_medium"], height=45)
        footer.pack(fill="x", side="bottom")

        # Progress Section
        progress_frame = tk.Frame(footer, bg=COLORS["bg_medium"])
        progress_frame.pack(side="left", fill="both", expand=True, padx=15)
        
        self.status_text = tk.Label(progress_frame, text="Ready to scan", font=("Segoe UI", 8), bg=COLORS["bg_medium"], fg=COLORS["fg_low"])
        self.status_text.pack(anchor="w", pady=(4, 0))
        
        self.progress = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate", length=400)
        self.progress.pack(fill="x", pady=(0, 5))

        # Control Buttons
        self.start_btn = tk.Button(footer, text="Execute Scan", command=self.start_scraping, bg=COLORS["accent"], fg="white", font=("Segoe UI Semibold", 9, "bold"), padx=25, borderwidth=0, cursor="hand2")
        self.start_btn.pack(side="right", padx=15, pady=8)

    def load_scripts(self):
        self.scripts = []
        run_mode = settings.get("Run_Mode", "test").lower()
        # Default selection based on Run_Mode
        default_selected = (run_mode == "live")
        
        for file in sorted(os.listdir(SCRIPTS_DIR)):
            if file.endswith(".py") and file != os.path.basename(__file__) and "_test_" not in file:
                self.scripts.append({"file": file, "selected": default_selected, "status": "⚪ Pending"})
        self.filter_scripts()

    def filter_scripts(self):
        query = self.search_var.get().lower()
        # Clear tree
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        for s in self.scripts:
            if query in s["file"].lower():
                check = "✅" if s["selected"] else "☐"
                self.tree.insert("", "end", iid=s["file"], values=(s["file"], check, s["status"]))
        self.update_stats()

    def mass_toggle(self, state):
        if self.is_running: return
        query = self.search_var.get().lower()
        for s in self.scripts:
            if query in s["file"].lower():
                s["selected"] = state
        self.filter_scripts()

    def on_tree_click(self, event):
        if self.is_running: return
        region = self.tree.identify_region(event.x, event.y)
        if region == "cell":
            item_id = self.tree.identify_row(event.y)
            column = self.tree.identify_column(event.x)
            if column == "#2":  # Checkbox column
                for s in self.scripts:
                    if s["file"] == item_id:
                        s["selected"] = not s["selected"]
                        break
                self.filter_scripts()

    def handle_reset_dates(self):
        if messagebox.askyesno("Confirm Reset", "This will reset 'date_scraped' for all applications to 2000-01-01, allowing them to be re-scraped today.\n\nContinue?"):
            if reset_date():
                self.log("Database: All application dates reset to 2000-01-01.", "SUCCESS")
                self.update_stats()
            else:
                self.log("Database: Failed to reset application dates.", "ERROR")

    def handle_clear_data(self):
        if messagebox.askyesno("Confirm Clear", "CRITICAL: This will PERMANENTLY delete all applications and documents from the database.\n\nAre you absolutely sure?"):
            if erase_db_data():
                self.log("Database: All application and document data cleared.", "SUCCESS")
                self.update_stats()
            else:
                self.log("Database: Failed to clear database.", "ERROR")

    def update_stats(self):
        selected_count = sum(1 for s in self.scripts if s["selected"])
        success_count = sum(1 for res in self.results if res[1] == "SUCCESS")
        failed_count = sum(1 for res in self.results if res[1] in ["FAILED", "CRASHED"])
        
        self.stat_labels["Selected"].config(text=str(selected_count))
        self.stat_labels["Success"].config(text=str(success_count))
        self.stat_labels["Failed"].config(text=str(failed_count))

    def create_reports_tab(self):
        # Header for the tab
        header = tk.Frame(self.reports_tab, bg=COLORS["bg_medium"], pady=10)
        header.pack(fill="x")
        
        tk.Label(header, text="Scan Date:", bg=COLORS["bg_medium"], fg=COLORS["fg_med"], font=("Segoe UI", 9)).pack(side="left", padx=(20, 10))
        
        self.date_var = tk.StringVar()
        self.date_combo = ttk.Combobox(header, textvariable=self.date_var, state="readonly", width=15)
        self.date_combo.pack(side="left", padx=5)
        self.date_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_statistics())
        
        tk.Button(header, text="Reload Data", command=self.load_available_dates, bg=COLORS["bg_light"], fg=COLORS["fg_med"], borderwidth=0, font=("Segoe UI", 8)).pack(side="left", padx=15)
        tk.Label(header, text="Tip: Select a council below to filter breakdown", bg=COLORS["bg_medium"], fg=COLORS["fg_low"], font=("Segoe UI", 8, "italic")).pack(side="right", padx=20)

        # Paned Window for split view
        paned = tk.PanedWindow(self.reports_tab, orient="vertical", bg=COLORS["bg_dark"], borderwidth=0, sashwidth=4)
        paned.pack(fill="both", expand=True, padx=10, pady=10)

        # Top Section: Council Summary
        council_frame = tk.Frame(paned, bg=COLORS["bg_medium"])
        tk.Label(council_frame, text="Council Summary", bg=COLORS["bg_medium"], fg=COLORS["accent"], font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=10, pady=5)
        
        self.stats_council_tree = ttk.Treeview(council_frame, columns=("Council", "Apps"), show="headings", height=5, style="Reports.Treeview")
        self.stats_council_tree.heading("Council", text="Council Name")
        self.stats_council_tree.heading("Apps", text="Total Apps")
        self.stats_council_tree.column("Council", width=250)
        self.stats_council_tree.column("Apps", width=150, anchor="center")
        
        # Scrollbar for Council Tree
        c_scroll = ttk.Scrollbar(council_frame, orient="vertical", command=self.stats_council_tree.yview)
        self.stats_council_tree.configure(yscrollcommand=c_scroll.set)
        
        self.stats_council_tree.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=5)
        c_scroll.pack(side="right", fill="y", pady=5, padx=(0, 5))
        self.stats_council_tree.bind("<<TreeviewSelect>>", lambda e: self.refresh_app_breakdown())
        paned.add(council_frame, minsize=100)

        # Bottom Section: Application and File breakdown
        breakdown_frame = tk.Frame(paned, bg=COLORS["bg_medium"])
        tk.Label(breakdown_frame, text="Application Breakdown", bg=COLORS["bg_medium"], fg=COLORS["accent"], font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=10, pady=5)
        
        self.stats_app_tree = ttk.Treeview(breakdown_frame, columns=("AppID", "Council", "Address", "Files", "Path"), show="headings", style="Reports.Treeview")
        self.stats_app_tree.heading("AppID", text="App ID")
        self.stats_app_tree.heading("Council", text="Council")
        self.stats_app_tree.heading("Address", text="Address")
        self.stats_app_tree.heading("Files", text="Files")
        self.stats_app_tree.heading("Path", text="Download Path")
        self.stats_app_tree.column("AppID", width=120)
        self.stats_app_tree.column("Council", width=90)
        self.stats_app_tree.column("Address", width=250)
        self.stats_app_tree.column("Files", width=60, anchor="center")
        self.stats_app_tree.column("Path", width=350)
        
        # Scrollbar for App Tree
        a_scroll = ttk.Scrollbar(breakdown_frame, orient="vertical", command=self.stats_app_tree.yview)
        self.stats_app_tree.configure(yscrollcommand=a_scroll.set)

        self.stats_app_tree.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=5)
        a_scroll.pack(side="right", fill="y", pady=5, padx=(0, 5))
        paned.add(breakdown_frame, minsize=300)
        
        self.load_available_dates()

    def create_settings_tab(self):
        # Container for settings
        container = tk.Frame(self.settings_tab, bg=COLORS["bg_dark"], padx=30, pady=20)
        container.pack(fill="both", expand=True)
        
        tk.Label(container, text="Scraper Configuration", font=("Segoe UI Semibold", 14), bg=COLORS["bg_dark"], fg=COLORS["accent"]).pack(anchor="w", pady=(0, 20))
        
        self.setting_entries = {}
        
        # Define settings to display
        setting_definitions = [
            ("DB_Path", "Path to SQLite Database"),
            ("Document_Path", "Base directory for downloads"),
            ("Max_Applications", "Limit apps per scraper (99999 for all)"),
            ("Max_Files_Per_App", "Limit files per application (99999 for all)"),
            ("Concurrent_Downloads", "Download threads per application"),
            ("Run_Mode", "Mode of operation (Live / Test)")
        ]
        
        curr_settings = load_settings()
        
        for key, label in setting_definitions:
            frame = tk.Frame(container, bg=COLORS["bg_dark"], pady=10)
            frame.pack(fill="x")
            
            tk.Label(frame, text=label, bg=COLORS["bg_dark"], fg=COLORS["fg_med"], width=30, anchor="w").pack(side="left")
            
            val = curr_settings.get(key, "99999" if "Max" in key else "")
            if isinstance(val, bool): val = str(val)
            
            # Paths need more width
            entry_width = 50 if "Path" in key else 30
            
            entry = tk.Entry(frame, bg=COLORS["bg_medium"], fg=COLORS["fg_high"], insertbackground="white", borderwidth=0, font=("Segoe UI", 10), width=entry_width)
            entry.insert(0, str(val))
            entry.pack(side="left", padx=10)
            self.setting_entries[key] = entry

        # Save Button
        btn_frame = tk.Frame(container, bg=COLORS["bg_dark"], pady=30)
        tk.Button(btn_frame, text="  Save Settings  ", command=self.save_all_settings, bg=COLORS["success"], fg="white", font=("Segoe UI Semibold", 10, "bold"), borderwidth=0, cursor="hand2", padx=20, pady=8).pack(side="left")
        btn_frame.pack(fill="x")

    def save_all_settings(self):
        new_settings = {}
        for key, entry in self.setting_entries.items():
            val = entry.get()
            # Basic type conversion
            if val.lower() == "true": val = True
            elif val.lower() == "false": val = False
            elif val.isdigit(): val = int(val)
            new_settings[key] = val
        
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(new_settings, f, indent=4)
            self.log("Settings: Successfully updated vestasettings.txt", "SUCCESS")
            # Update global settings object
            global settings
            settings = new_settings
        except Exception as e:
            self.log(f"Settings: Failed to save - {e}", "ERROR")

    def load_available_dates(self):
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT date_scraped FROM applications WHERE date_scraped != '2000-01-01' ORDER BY date_scraped DESC")
            dates = [r[0] for r in cursor.fetchall()]
            conn.close()
            
            # Add "All Dates" option
            options = ["All Dates"] + dates
            self.date_combo['values'] = options
            
            if not self.date_var.get():
                self.date_combo.current(0)
                self.refresh_statistics()
        except:
            pass

    def refresh_statistics(self):
        target_date = self.date_var.get()
        if not target_date: return
        
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            # 1. Council Summary
            if target_date == "All Dates":
                cursor.execute("SELECT council, COUNT(*) FROM applications GROUP BY council")
            else:
                cursor.execute("SELECT council, COUNT(*) FROM applications WHERE date_scraped = ? GROUP BY council", (target_date,))
            councils = cursor.fetchall()
            
            for item in self.stats_council_tree.get_children(): self.stats_council_tree.delete(item)
            for c_name, c_count in councils:
                self.stats_council_tree.insert("", "end", values=(c_name.upper(), c_count))
            
            self.refresh_app_breakdown() # Refresh detail table
            conn.close()
        except Exception as e:
            print(f"Stats Error: {e}")

    def refresh_app_breakdown(self):
        target_date = self.date_var.get()
        selected_council = ""
        
        curr_selection = self.stats_council_tree.selection()
        if curr_selection:
            selected_council = self.stats_council_tree.item(curr_selection[0])['values'][0].lower()
            
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            query = """
                SELECT a.application_id, a.council, a.address, COUNT(d.id), a.download_path
                FROM applications a 
                LEFT JOIN documents d ON a.application_id = d.application_id 
                WHERE 1=1
            """
            params = []
            
            if target_date != "All Dates":
                query += " AND a.date_scraped = ?"
                params.append(target_date)
            
            if selected_council:
                query += " AND a.council = ?"
                params.append(selected_council)
                
            query += " GROUP BY a.application_id ORDER BY a.council ASC, a.date_scraped DESC"
            
            cursor.execute(query, params)
            apps = cursor.fetchall()
            
            for item in self.stats_app_tree.get_children(): self.stats_app_tree.delete(item)
            for app_id, council, address, f_count, download_path in apps:
                address_clean = address if address else "No Address Found"
                # Only show path if it exists
                path_display = download_path if (download_path and os.path.exists(download_path)) else ""
                self.stats_app_tree.insert("", "end", values=(app_id, council.upper(), address_clean, f_count, path_display))
                
            conn.close()
        except Exception as e:
            print(f"App Breakdown Error: {e}")

    def log(self, message, level="INFO"):
        if not message: return
        self.log_queue.put((message, level))
        # Also write to persistent log file
        if level == "ERROR":
            logging.error(message)
        elif level == "SUCCESS":
            logging.info(f"SUCCESS: {message}")
        else:
            logging.info(message)

    def update_log_from_queue(self):
        try:
            while True:
                message, level = self.log_queue.get_nowait()
                self.console.config(state="normal")
                timestamp = datetime.now().strftime("%H:%M:%S")
                
                self.console.insert("end", f"[{timestamp}] ", "dim")
                self.console.insert("end", f"[{level}] ", level)
                self.console.insert("end", f"{message}\n", "text")
                
                self.console.tag_config("ERROR", foreground=COLORS["error"], font=("Consolas", 11, "bold"))
                self.console.tag_config("SUCCESS", foreground=COLORS["success"], font=("Consolas", 11, "bold"))
                self.console.tag_config("INFO", foreground=COLORS["accent"])
                self.console.tag_config("dim", foreground=COLORS["fg_low"])
                self.console.tag_config("text", foreground="#d4d4d4")
                
                self.console.see("end")
                self.console.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self.update_log_from_queue)

    def prune_logs(self, max_files=500):
        """Delete oldest run_*.log files if they exceed max_files"""
        try:
            if not os.path.exists(LOG_DIR): return
            files = [os.path.join(LOG_DIR, f) for f in os.listdir(LOG_DIR) if f.startswith("run_") and f.endswith(".log")]
            if len(files) <= max_files: return
            
            # Sort by modification time (oldest first)
            files.sort(key=os.path.getmtime)
            to_delete = files[:len(files) - max_files]
            for f in to_delete:
                try: os.remove(f)
                except: pass
            self.log(f"Cleaned up {len(to_delete)} old log files.", "INFO")
        except Exception as e:
            self.log(f"Log Pruning Error: {e}", "ERROR")

    def start_scraping(self):
        if self.is_running: return
        self.is_running = True
        self.start_btn.config(state="disabled", bg=COLORS["bg_light"], text="Running...")
        self.results = []
        self.progress["value"] = 0
        threading.Thread(target=self.run_all_scripts, daemon=True).start()

    def run_all_scripts(self):
        init_database()
        os.makedirs(LOG_DIR, exist_ok=True)
        log_file = os.path.join(LOG_DIR, f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(message)s",
            handlers=[
                logging.FileHandler(log_file, encoding="utf-8"),
                logging.FileHandler(MAIN_LOG, encoding="utf-8"), # Also append to main log
                logging.StreamHandler(sys.stdout) # Restore terminal output
            ],
            force=True # Force override for this thread's run
        )

        start_time = datetime.now()
        self.log("🚀 SCRIPT EXECUTION STARTED", "INFO")
        
        run_list = [s for s in self.scripts if s["selected"]]
        total = len(run_list)
        
        if total == 0:
            self.log("No scrapers selected. Aborting.", "INFO")
            self.finalize_run(start_time, None, None, log_file)
            return

        for i, script in enumerate(run_list):
            filename = script["file"]
            script["status"] = "🔵 Running"
            self.filter_scripts()
            
            self.log(f"Starting {filename}...", "INFO")
            self.status_text.config(text=f"Executing {filename} ({i+1}/{total})")
            
            script_path = os.path.join(SCRIPTS_DIR, filename)
            try:
                process = subprocess.Popen(
                    [sys.executable, script_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"}
                )

                stacktrace_count = 0
                for line in process.stdout:
                    l = line.strip()
                    if not l: continue
                    
                    # Detect stacktrace/long dump start (symbols, hex addresses, backtraces)
                    is_stack = "Stacktrace" in l or "backtrace" in l or l.startswith("0x")
                    
                    if is_stack:
                        stacktrace_count += 1
                        if stacktrace_count <= 4:
                            self.log(l)
                        elif stacktrace_count == 5:
                            self.log("... [Long message truncated after 4 lines] ...")
                    else:
                        stacktrace_count = 0  # Reset on normal log line
                        self.log(l)
                
                process.wait()
                
                if process.returncode == 0:
                    script["status"] = "✅ Success"
                    status = "SUCCESS"
                    self.log(f"✔ {filename} COMPLETED", "SUCCESS")
                else:
                    script["status"] = "❌ Failed"
                    status = "FAILED"
                    self.log(f"✖ {filename} FAILED (Code: {process.returncode})", "ERROR")
            except Exception as e:
                script["status"] = "💥 Crashed"
                status = "CRASHED"
                self.log(f"⚠ {filename} CRASHED: {e}", "ERROR")
            
            self.results.append((filename, status))
            self.progress["value"] = ((i + 1) / total) * 100
            self.update_stats()
            self.filter_scripts()

        end_time = datetime.now()
        duration = end_time - start_time
        self.finalize_run(start_time, end_time, duration, log_file)

    def finalize_run(self, start_time, end_time, duration, log_file):
        if end_time:
            self.log("🏁 SCRIPT EXECUTION COMPLETED", "SUCCESS")
            self.log(f"Total Duration: {duration}")
            self.status_text.config(text="Scan sequence finished")

            if EMAIL_ENABLED:
                try:
                    self.send_report(start_time, end_time, duration, log_file)
                    self.log("Report emailed successfully", "SUCCESS")
                except Exception as e:
                    self.log(f"Email failed: {e}", "ERROR")

        self.root.after(0, lambda: self.start_btn.config(state="normal", bg=COLORS["accent"], text="Execute Scan"))
        self.root.after(0, self.load_available_dates) # Refresh stats view
        self.is_running = False

    def send_report(self, start_time, end_time, duration, log_file):
        msg = EmailMessage()
        msg["Subject"] = "VESTA: Scraper Operation Summary"
        msg["From"] = EMAIL_FROM
        msg["To"] = ", ".join(EMAIL_TO)
        
        summary = "\n".join([f"• {f} → {s}" for f, s in self.results])
        body = f"""VESTA Automation Operation Report
---------------------------------
Start:    {start_time.strftime('%Y-%m-%d %H:%M:%S')}
End:      {end_time.strftime('%Y-%m-%d %H:%M:%S')}
Duration: {duration}

Execution Summary:
{summary}

See attached log for full details."""
        
        msg.set_content(body)
        with open(log_file, "rb") as f:
            msg.add_attachment(f.read(), maintype="text", subtype="plain", filename=os.path.basename(log_file))
            
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.send_message(msg)

if __name__ == "__main__":
    init_database()
    root = tk.Tk()
    # Attempt to set title bar color on Windows (Win10+)
    # This requires specific DLL calls, but we can set the app icon and title safely
    app = VestaDashboard(root)
    root.mainloop()