"""
Petpooja Automation GUI Dashboard.

Provides a graphical user interface for managing automation steps,
viewing real-time logs, and configuring application settings.
"""

import asyncio
import json
import logging
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from execution.browser_helper import setup_browser
from execution.data_cleaner import DataCleaner
from execution.gdrive_uploader import GDriveUploader
from execution.logger_helper import LoggerHelper
from execution.notifier_helper import NotifierHelper
from execution.petpooja_automation import PetpoojaAutomation

# --- UI THEME CONSTANTS ---
COLORS = {
    "bg_dark": "#121212",
    "bg_medium": "#1e1e1e",
    "bg_light": "#2d2d2d",
    "accent": "#007acc",
    "accent_hover": "#005a9e",
    "fg_high": "#ffffff",
    "fg_med": "#cccccc",
    "fg_low": "#858585",
    "success": "#4caf50",
    "error": "#f44336",
    "warning": "#ff9800",
}


class QueueHandler(logging.Handler):
    """Custom logging handler that pushes log records to a queue for the GUI."""

    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(record)


class PetpoojaGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Petpooja Automation Dashboard")
        self.root.geometry("1100x750")
        self.root.configure(bg=COLORS["bg_dark"])
        try:
            self.root.state("zoomed")
        except tk.TclError:
            pass

        self.settings_path = Path("settings.json")
        self.env_path = Path(".env")
        self.gdrive_config_path = Path("gdrive/config.txt")

        # Initialize Helper
        self.logger_helper = LoggerHelper()
        self.log_queue = queue.Queue()
        self.queue_handler = QueueHandler(self.log_queue)
        self.logger_helper.add_handler(self.queue_handler)

        self.setup_styles()
        self.create_widgets()

        self.is_running = False
        self.last_trigger_date = None
        self.update_log_from_queue()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TFrame", background=COLORS["bg_dark"])
        style.configure(
            "TNotebook", background=COLORS["bg_dark"], borderwidth=0, padding=0
        )
        style.configure(
            "TNotebook.Tab",
            background=COLORS["bg_light"],
            foreground=COLORS["fg_low"],
            padding=[15, 5],
            font=("Segoe UI", 10),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLORS["bg_medium"])],
            foreground=[("selected", COLORS["accent"])],
        )

        style.configure(
            "TLabel",
            background=COLORS["bg_dark"],
            foreground=COLORS["fg_med"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Header.TLabel",
            font=("Segoe UI Semibold", 18, "bold"),
            foreground=COLORS["accent"],
        )

        style.configure("TButton", font=("Segoe UI Semibold", 10), borderwidth=0)
        style.map(
            "TButton",
            background=[
                ("active", COLORS["accent_hover"]),
                ("!disabled", COLORS["accent"]),
            ],
        )

    def create_widgets(self):
        # Header
        header_frame = tk.Frame(self.root, bg=COLORS["bg_medium"], height=80)
        header_frame.pack(fill="x", side="top")

        tk.Label(
            header_frame,
            text="PETPOOJA",
            font=("Segoe UI Semibold", 20, "bold"),
            bg=COLORS["bg_medium"],
            fg=COLORS["accent"],
        ).pack(side="left", padx=(20, 5), pady=10)
        tk.Label(
            header_frame,
            text="AUTOMATION",
            font=("Segoe UI", 14),
            bg=COLORS["bg_medium"],
            fg=COLORS["fg_med"],
        ).pack(side="left", pady=(15, 0))

        # Main Tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=15, pady=10)

        # Tab 1: Control Center
        self.control_tab = tk.Frame(self.notebook, bg=COLORS["bg_dark"])
        self.notebook.add(self.control_tab, text=" Control Center ")
        self.create_control_center()

        # Tab 2: Settings
        self.settings_tab = tk.Frame(self.notebook, bg=COLORS["bg_dark"])
        self.notebook.add(self.settings_tab, text=" Settings ")
        self.create_settings_view()

        # Tab 3: Scheduler
        self.scheduler_tab = tk.Frame(self.notebook, bg=COLORS["bg_dark"])
        self.notebook.add(self.scheduler_tab, text=" Scheduler ")
        self.scheduler_vars = {}
        self.create_scheduler_view()

        # Start Scheduler Background Check
        self.root.after(60000, self.background_scheduler_check)

    def create_control_center(self):
        # Tools side
        toolbar = tk.Frame(self.control_tab, bg=COLORS["bg_dark"], pady=10)
        toolbar.pack(fill="x")

        # Swapped order: Execute first, then Setup
        self.start_btn = tk.Button(
            toolbar,
            text="Execute Automation",
            command=self.start_automation,
            bg=COLORS["accent"],
            fg="white",
            font=("Segoe UI Semibold", 10, "bold"),
            padx=25,
            borderwidth=0,
            cursor="hand2",
        )
        self.start_btn.pack(side="left", padx=(5, 20))

        self.setup_btn = tk.Button(
            toolbar,
            text="Setup Browser",
            command=self.run_setup_browser,
            bg=COLORS["bg_light"],
            fg=COLORS["fg_high"],
            font=("Segoe UI Semibold", 10),
            padx=20,
            borderwidth=0,
            cursor="hand2",
        )
        self.setup_btn.pack(side="left", padx=5)

        # Console Output
        console_label = tk.Label(
            self.control_tab,
            text="Real-time Execution Logs",
            font=("Segoe UI Semibold", 10),
            bg=COLORS["bg_dark"],
            fg=COLORS["fg_low"],
        )
        console_label.pack(anchor="w", padx=5, pady=(10, 5))

        self.console = scrolledtext.ScrolledText(
            self.control_tab,
            bg="#0d0d0d",
            fg="#d4d4d4",
            font=("Consolas", 11),
            state="disabled",
            borderwidth=0,
            padx=10,
            pady=10,
        )
        self.console.pack(fill="both", expand=True)

    def _on_mousewheel(self, event, canvas):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def create_scheduler_view(self):
        # Load existing scheduler settings
        settings = self.load_json(self.settings_path)
        sched = settings.get("scheduler", {})

        container = tk.Frame(self.scheduler_tab, bg=COLORS["bg_dark"], padx=30, pady=30)
        container.pack(fill="both", expand=True)

        self.add_section_header(container, "Automation Scheduler")

        # Enable Toggle
        self.scheduler_vars["enabled"] = tk.BooleanVar(
            value=sched.get("enabled", False)
        )
        tk.Checkbutton(
            container,
            text="Enable Background Scheduler",
            variable=self.scheduler_vars["enabled"],
            bg=COLORS["bg_dark"],
            fg=COLORS["fg_high"],
            selectcolor=COLORS["bg_medium"],
            activebackground=COLORS["bg_dark"],
            activeforeground=COLORS["accent"],
            font=("Segoe UI Semibold", 11),
            pady=10,
        ).pack(anchor="w")

        # Days of Week
        days_frame = tk.LabelFrame(
            container,
            text=" Days to Run ",
            bg=COLORS["bg_dark"],
            fg=COLORS["accent"],
            font=("Segoe UI Semibold", 10),
            padx=15,
            pady=15,
        )
        days_frame.pack(fill="x", pady=20)

        self.scheduler_vars["days"] = {}
        days = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        saved_days = sched.get("days", days)  # Default to all days if not set

        for i, day in enumerate(days):
            var = tk.BooleanVar(value=day in saved_days)
            self.scheduler_vars["days"][day] = var
            tk.Checkbutton(
                days_frame,
                text=day,
                variable=var,
                bg=COLORS["bg_dark"],
                fg=COLORS["fg_med"],
                selectcolor=COLORS["bg_medium"],
                activebackground=COLORS["bg_dark"],
                font=("Segoe UI", 10),
            ).grid(row=i // 4, column=i % 4, sticky="w", padx=10, pady=5)

        # Time Picker
        time_frame = tk.Frame(container, bg=COLORS["bg_dark"], pady=10)
        time_frame.pack(fill="x")

        tk.Label(
            time_frame,
            text="Execution Time (24h format HH:MM):",
            bg=COLORS["bg_dark"],
            fg=COLORS["fg_med"],
        ).pack(side="left")

        self.scheduler_vars["time"] = tk.Entry(
            time_frame,
            bg=COLORS["bg_medium"],
            fg=COLORS["fg_high"],
            insertbackground="white",
            borderwidth=0,
            font=("Segoe UI", 11),
            width=10,
        )
        self.scheduler_vars["time"].insert(0, sched.get("time", "09:00"))
        self.scheduler_vars["time"].pack(side="left", padx=15)

        # Save Button
        tk.Button(
            container,
            text="Save Scheduler Settings",
            command=self.save_scheduler_settings,
            bg=COLORS["accent"],
            fg="white",
            font=("Segoe UI Semibold", 10),
            padx=20,
            pady=8,
            borderwidth=0,
        ).pack(anchor="w", pady=30)

        tk.Label(
            container,
            text="Note: The dashboard must be kept open for the scheduler to trigger automation.",
            bg=COLORS["bg_dark"],
            fg=COLORS["fg_low"],
            font=("Segoe UI Italic", 9),
        ).pack(anchor="w")

    def background_scheduler_check(self):
        """Check regularly if automation should run."""
        if not self.is_running:
            settings = self.load_json(self.settings_path)
            sched = settings.get("scheduler", {})

            if sched.get("enabled"):
                now = datetime.now()
                current_day = now.strftime("%A")
                current_time = now.strftime("%H:%M")
                current_date = now.strftime("%Y-%m-%d")

                # Verify if it's the right day and time, and NOT already triggered today
                if (
                    current_day in sched.get("days", [])
                    and current_time == sched.get("time")
                    and self.last_trigger_date != current_date
                ):
                    self.last_trigger_date = current_date
                    self.log_gui(
                        f"Scheduler: Triggering scheduled run for {current_day} {current_time}",
                        "INFO",
                    )
                    self.start_automation()

        # Schedule next check in 30 seconds (narrower window to avoid missing)
        self.root.after(30000, self.background_scheduler_check)

    def save_scheduler_settings(self):
        try:
            settings = self.load_json(self.settings_path)

            enabled = self.scheduler_vars["enabled"].get()
            time_val = self.scheduler_vars["time"].get().strip()
            # Simple validation
            try:
                datetime.strptime(time_val, "%H:%M")
            except ValueError:
                messagebox.showerror(
                    "Error", "Invalid time format. Use HH:MM (e.g., 09:30)"
                )
                return

            selected_days = [
                day for day, var in self.scheduler_vars["days"].items() if var.get()
            ]

            settings["scheduler"] = {
                "enabled": enabled,
                "days": selected_days,
                "time": time_val,
            }

            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=4)

            messagebox.showinfo("Success", "Scheduler settings saved!")
            self.log_gui("Scheduler settings updated.", "INFO")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save scheduler: {e}")

    def create_settings_view(self):
        canvas = tk.Canvas(
            self.settings_tab, bg=COLORS["bg_dark"], highlightthickness=0
        )
        scrollbar = ttk.Scrollbar(
            self.settings_tab, orient="vertical", command=canvas.yview
        )
        scrollable_frame = tk.Frame(canvas, bg=COLORS["bg_dark"])

        scrollable_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        # Mouse Wheel Binding Fix
        canvas.bind_all("<MouseWheel>", lambda e: self._on_mousewheel(e, canvas))

        canvas.pack(side="left", fill="both", expand=True, padx=20, pady=20)
        scrollbar.pack(side="right", fill="y")

        self.setting_entries = {}

        # 1. settings.json Configuration
        self.add_section_header(
            scrollable_frame, "General & Email Settings (settings.json)"
        )
        settings_data = self.load_json(self.settings_path)

        # General
        for key in [
            "download_dir",
            "processed_dir",
            "browser_profile_dir",
            "petpooja_url",
            "login_url",
            "email_enabled",
        ]:
            self.add_setting_row(
                scrollable_frame, key, settings_data.get(key, ""), "settings"
            )

        # Email (settings.json)
        self.add_section_header(scrollable_frame, "Email Configuration (settings.json)")
        email_fields = [
            ("smtp_host", "SMTP Host (e.g. smtp.gmail.com)"),
            ("smtp_port", "SMTP Port (e.g. 587)"),
            ("smtp_user", "SMTP User (Sender Email)"),
            ("smtp_pass", "App Password "),
            ("email_receivers", "Receivers (comma separated)"),
        ]
        for key, label in email_fields:
            val = settings_data.get(key, "")
            if isinstance(val, list):
                val = ", ".join(val)
            self.add_setting_row(scrollable_frame, key, val, "settings", label)

        # 2. Petpooja Credentials (.env)
        self.add_section_header(scrollable_frame, "Petpooja Credentials (.env)")
        env_data = self.load_env(self.env_path)
        self.add_setting_row(
            scrollable_frame,
            "PETPOOJA_USERNAME",
            env_data.get("PETPOOJA_USERNAME", ""),
            "env",
            "Petpooja Login Email",
        )
        self.add_setting_row(
            scrollable_frame,
            "PETPOOJA_PASSWORD",
            env_data.get("PETPOOJA_PASSWORD", ""),
            "env",
            "Petpooja Password",
        )

        # 3. GDrive Settings (gdrive/config.txt)
        self.add_section_header(scrollable_frame, "Google Drive (gdrive/config.txt)")
        gdrive_data = self.load_env(self.gdrive_config_path)
        self.add_setting_row(
            scrollable_frame,
            "GDRIVE_FOLDER_ID",
            gdrive_data.get("GDRIVE_FOLDER_ID", ""),
            "gdrive",
            "Drive Folder ID",
        )

        # Save & Cleanup Buttons
        button_frame = tk.Frame(scrollable_frame, bg=COLORS["bg_dark"], pady=30)
        button_frame.pack()

        save_btn = tk.Button(
            button_frame,
            text="Save All Settings",
            command=self.save_all_settings,
            bg=COLORS["success"],
            fg="white",
            font=("Segoe UI Semibold", 10, "bold"),
            borderwidth=0,
            padx=30,
            pady=10,
        )
        save_btn.pack(side="left", padx=10)

        cleanup_btn = tk.Button(
            button_frame,
            text="Cleanup (Old Files)",
            command=self.run_local_cleanup,
            bg=COLORS["warning"],
            fg="white",
            font=("Segoe UI Semibold", 10, "bold"),
            borderwidth=0,
            padx=30,
            pady=10,
        )
        cleanup_btn.pack(side="left", padx=10)

    def run_local_cleanup(self):
        """Deletes files in logs/ and processed/ older than 1 year."""
        if not messagebox.askyesno(
            "Confirm Cleanup",
            "This will permanently delete all logs and processed reports older than 1 year. Proceed?",
        ):
            return

        try:
            count = 0
            size_saved = 0
            now = datetime.now().timestamp()
            one_year_seconds = 365 * 24 * 60 * 60

            # Directories to clean
            target_dirs = [
                Path("logs"),
                Path(
                    self.load_json(self.settings_path).get(
                        "processed_dir", ".tmp/downloads/processed"
                    )
                ),
            ]

            for d in target_dirs:
                if d.exists() and d.is_dir():
                    for f in d.iterdir():
                        if f.is_file():
                            file_age = now - f.stat().st_mtime
                            if file_age > one_year_seconds:
                                size_saved += f.stat().st_size
                                f.unlink()
                                count += 1

            msg = f"Cleanup complete! Removed {count} files. Saved {size_saved / (1024 * 1024):.2f} MB."
            messagebox.showinfo("Success", msg)
            self.log_gui(msg, "INFO")
        except Exception as e:
            messagebox.showerror("Error", f"Cleanup failed: {e}")

    def add_section_header(self, parent, text):
        lbl = tk.Label(
            parent,
            text=text,
            font=("Segoe UI Semibold", 12),
            bg=COLORS["bg_dark"],
            fg=COLORS["accent"],
            pady=15,
        )
        lbl.pack(anchor="w")

    def add_setting_row(self, parent, key, value, category, label_text=None):
        frame = tk.Frame(parent, bg=COLORS["bg_dark"], pady=5)
        frame.pack(fill="x")

        display_text = label_text if label_text else key
        tk.Label(
            frame,
            text=display_text,
            bg=COLORS["bg_dark"],
            fg=COLORS["fg_med"],
            width=30,
            anchor="w",
        ).pack(side="left")

        entry = tk.Entry(
            frame,
            bg=COLORS["bg_medium"],
            fg=COLORS["fg_high"],
            insertbackground="white",
            borderwidth=0,
            font=("Segoe UI", 10),
            width=60,
        )
        entry.insert(0, str(value))
        entry.pack(side="left", padx=10)

        self.setting_entries[key] = (entry, category)

    def load_json(self, path):
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def load_env(self, path):
        data = {}
        if not path.exists():
            return data
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if "=" in line and not line.startswith("#"):
                        parts = line.strip().split("=", 1)
                        if len(parts) == 2:
                            k, v = parts
                            data[k.strip()] = v.strip()
        except Exception:
            pass
        return data

    def save_all_settings(self):
        try:
            # 1. Load existing data to avoid overwriting unrelated keys
            current_settings = self.load_json(self.settings_path)
            current_env = self.load_env(self.env_path)
            current_gdrive = self.load_env(self.gdrive_config_path)

            # 2. Update with GUI values
            for key, (entry, cat) in self.setting_entries.items():
                val = entry.get().strip()
                processed_val = val
                if val.lower() == "true":
                    processed_val = True
                elif val.lower() == "false":
                    processed_val = False
                elif val.isdigit():
                    processed_val = int(val)

                if cat == "settings":
                    if key == "email_receivers":
                        # Convert comma-separated string to list
                        current_settings[key] = [
                            r.strip() for r in val.split(",") if r.strip()
                        ]
                    else:
                        current_settings[key] = processed_val
                elif cat == "env":
                    current_env[key] = val
                elif cat == "gdrive":
                    current_gdrive[key] = val

            # 3. Save merged results
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(current_settings, f, indent=4)

            with open(self.env_path, "w", encoding="utf-8") as f:
                for k, v in current_env.items():
                    f.write(f"{k}={v}\n")

            os.makedirs("gdrive", exist_ok=True)
            with open(self.gdrive_config_path, "w", encoding="utf-8") as f:
                for k, v in current_gdrive.items():
                    f.write(f"{k}={v}\n")

            messagebox.showinfo(
                "Success",
                "Settings saved successfully and merged with existing configurations!",
            )
            self.log_gui("Settings updated.", "INFO")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save settings: {e}")

    def log_gui(self, message, level="INFO"):
        """Internal GUI logger."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.console.config(state="normal")
        self.console.insert("end", f"{timestamp} [{level}] {message}\n")
        self.console.see("end")
        self.console.config(state="disabled")

    def update_log_from_queue(self):
        try:
            while True:
                record = self.log_queue.get_nowait()
                self.console.config(state="normal")
                ts = datetime.fromtimestamp(record.created).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                # Add color tags based on level
                tag = record.levelname
                self.console.insert("end", f"{ts} [{tag}] ", tag)
                self.console.insert("end", f"{record.getMessage()}\n")

                self.console.tag_config("ERROR", foreground=COLORS["error"])
                self.console.tag_config("WARNING", foreground=COLORS["warning"])
                self.console.tag_config("INFO", foreground=COLORS["accent"])

                # Log Truncation Logic (Keep last 500 lines)
                num_lines = int(self.console.index("end-1c").split(".")[0])
                if num_lines > 500:
                    self.console.delete("1.0", f"{num_lines - 500}.0")

                self.console.see("end")
                self.console.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(100, self.update_log_from_queue)

    def run_setup_browser(self):
        def _task():
            asyncio.run(setup_browser())

        self.log_gui("Launching browser setup. Check browser window...", "INFO")
        threading.Thread(target=_task, daemon=True).start()

    def start_automation(self):
        if self.is_running:
            return
        self.is_running = True
        self.start_btn.config(state="disabled", text="Running...")
        self.console.config(state="normal")
        self.console.delete("1.0", tk.END)
        self.console.config(state="disabled")

        threading.Thread(target=self.automation_thread, daemon=True).start()

    def automation_thread(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        success = False
        try:
            # Re-init logger for this run
            logger = self.logger_helper.logger
            logger.info("Starting Petpooja Order Summary Report Automation")

            automation = PetpoojaAutomation()
            loop.run_until_complete(automation.run())

            cleaner = DataCleaner()
            _ = cleaner.process_latest_report()

            uploader = GDriveUploader()
            uploader.process_files()

            success = True
        except Exception as e:
            self.logger_helper.logger.error(f"Automation sequence failed: {e}")
            success = False
        finally:
            # Handle email notification
            try:
                notifier = NotifierHelper()
                log_content = ""
                if os.path.exists(self.logger_helper.log_file):
                    with open(self.logger_helper.log_file, "r", encoding="utf-8") as f:
                        log_content = f.read()
                notifier.send_status_email(success, log_content)
            except Exception as e:
                self.logger_helper.logger.error(f"Email notification failed: {e}")

            self.is_running = False
            self.root.after(
                0,
                lambda: self.start_btn.config(
                    state="normal", text="Execute Automation"
                ),
            )
            self.log_gui("Process finished.", "SUCCESS" if success else "ERROR")


if __name__ == "__main__":
    root = tk.Tk()
    app = PetpoojaGUI(root)
    root.mainloop()
