import sys
import configparser
import customtkinter as ctk
from tkinter import messagebox, ttk
from openalgo.orders import api  # Import the OpenAlgo package

class AppStyles:
    BG_COLOR = "#1E1E1E"
    INPUT_COLOR = "#2B2B2B"
    LE_COLOR = "#4CAF50"
    LX_COLOR = "#F44336"
    SE_COLOR = "#FF9800"
    SX_COLOR = "#0066cc"
    SETTINGS_COLOR = "#2196F3"

class SettingsDialog(ctk.CTkToplevel):
    EXCHANGES = [
        "NSE", "NFO", "CDS", "BSE", "BFO", "BCD", "MCX", "NCDEX"
    ]
    PRODUCTS = [
        "CNC", "NRML", "MIS"
    ]

    def __init__(self, parent, title, initial_values):
        super().__init__(parent)
        self.title(title)
        self.initial_values = initial_values
        self.result = {}
        self.create_widgets()
        self.grab_set()

        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def create_widgets(self):
        self.entries = {}
        for i, (key, value) in enumerate(self.initial_values.items()):
            if key in ['exchange', 'product']:
                ctk.CTkLabel(self, text=f"{key.capitalize()}:").grid(row=i, column=0, sticky="e", padx=5, pady=2)
                combo = ttk.Combobox(self, values=self.EXCHANGES if key == 'exchange' else self.PRODUCTS, width=30)
                combo.set(value)
                combo.grid(row=i, column=1, sticky="we", padx=5, pady=2)
                self.entries[key] = combo
            else:
                ctk.CTkLabel(self, text=f"{key.capitalize()}:").grid(row=i, column=0, sticky="e", padx=5, pady=2)
                entry = ctk.CTkEntry(self, width=120)
                entry.insert(0, value)
                entry.grid(row=i, column=1, sticky="we", padx=5, pady=2)
                self.entries[key] = entry

        button_frame = ctk.CTkFrame(self)
        button_frame.grid(row=len(self.initial_values), column=0, columnspan=2, pady=5)

        ctk.CTkButton(button_frame, text="OK", command=self.on_ok, width=60).pack(side="left", padx=2)
        ctk.CTkButton(button_frame, text="Cancel", command=self.on_cancel, width=60).pack(side="left", padx=2)

    def on_ok(self):
        for key, widget in self.entries.items():
            self.result[key] = widget.get()
        self.destroy()

    def on_cancel(self):
        self.result = None
        self.destroy()

class TradingApp:
    def __init__(self, master):
        self.master = master
        master.title("FastScalper")
        master.configure(bg=AppStyles.BG_COLOR)

        self.config = configparser.ConfigParser()
        self.config_file = 'config.ini'
        self.load_config()

        self.create_widgets()
        self.center_window()

    def center_window(self):
        self.master.geometry('300x100')  # Set the explicit geometry to ensure correct size
        self.master.update_idletasks()  # Ensure all tasks are processed
        width = self.master.winfo_width()
        height = self.master.winfo_height()
        x = (self.master.winfo_screenwidth() // 2) - (width // 2)
        y = (self.master.winfo_screenheight() // 2) - (height // 2)
        self.master.geometry('{}x{}+{}+{}'.format(width, height, x, y))
        self.master.after(100, self.adjust_size)  # Adjust the size after 100ms

    def adjust_size(self):
        self.master.geometry('300x100')  # Forcefully set the size again

    def create_widgets(self):
        main_frame = ctk.CTkFrame(self.master, fg_color=AppStyles.BG_COLOR)
        main_frame.pack(fill="both", expand=True, padx=5, pady=5)

        input_frame = ctk.CTkFrame(main_frame, fg_color=AppStyles.BG_COLOR)
        input_frame.pack(fill="x", pady=(0, 5))
        self.create_input_field(input_frame, "Symbol", 0, "BHEL")
        self.create_input_field(input_frame, "Quantity", 1, "1")
        self.create_button(input_frame, "Settings", self.open_settings, AppStyles.SETTINGS_COLOR, 0, 2, rowspan=2)

        button_frame = ctk.CTkFrame(main_frame, fg_color=AppStyles.BG_COLOR)
        button_frame.pack(fill="x")

        button_config = [
            ("LE", self.trade_le, AppStyles.LE_COLOR),
            ("LX", self.trade_lx, AppStyles.LX_COLOR),
            ("SE", self.trade_se, AppStyles.SE_COLOR),
            ("SX", self.trade_sx, AppStyles.SX_COLOR)
        ]

        for i, (text, command, color) in enumerate(button_config):
            self.create_button(button_frame, text, command, color, 0, i)

    def create_input_field(self, parent, label, row, default_value):
        ctk.CTkLabel(parent, text=f"{label}:", anchor="e", width=55).grid(row=row, column=0, padx=(0, 2), pady=1, sticky="e")
        entry = ctk.CTkEntry(parent, width=120, fg_color=AppStyles.INPUT_COLOR)
        entry.insert(0, default_value)
        entry.grid(row=row, column=1, pady=1, sticky="w")
        setattr(self, label.lower(), entry)

    def create_button(self, parent, text, command, fg_color, row, column, rowspan=1):
        button = ctk.CTkButton(parent, text=text, command=command, fg_color=fg_color, text_color="black", width=70, height=25)
        button.grid(row=row, column=column, rowspan=rowspan, padx=1, pady=1)

    def trade_le(self): self.trade("BUY", self.quantity.get())
    def trade_lx(self): self.trade("SELL", 0)
    def trade_se(self): self.trade("SELL", self.quantity.get())
    def trade_sx(self): self.trade("BUY", 0)

    def trade(self, action, quantity):
        info = f"Action: {action}\n"
        info += f"Symbol: {self.symbol.get()}\n"
        info += f"Quantity: {quantity}\n"
        info += f"API Key: {self.config['DEFAULT']['api_key']}\n"
        info += f"Exchange: {self.config['DEFAULT']['exchange']}\n"
        info += f"Product: {self.config['DEFAULT']['product']}\n"

        print(f"--- {action} ---")
        print(info)
        print("--------------------")

        # OpenAlgo Smart Order Integration
        try:
            client = api(api_key=self.config['DEFAULT']['api_key'], host='http://127.0.0.1:5000')
            response = client.placesmartorder(
                strategy="FastScalper",  # Replace with your strategy
                symbol=self.symbol.get(),
                action=action,
                exchange=self.config['DEFAULT']['exchange'],
                price_type="MARKET",  # Replace with your price type
                product=self.config['DEFAULT']['product'],
                quantity=int(quantity),
                position_size=0  # Replace with your position size
            )
            '''
            if response['status'] == 'success':
                messagebox.showinfo("Order Status", f"Order placed successfully: {response['orderid']}")
            else:
                messagebox.showerror("Order Error", f"Order failed: {response['error']}")
            '''
        except Exception as e:
            messagebox.showerror("OpenAlgo Error", str(e))

    def open_settings(self):
        initial_values = {k: self.config['DEFAULT'][k] for k in ['api_key', 'exchange', 'product']}
        dialog = SettingsDialog(self.master, "Settings", initial_values)
        self.master.wait_window(dialog)
        if dialog.result:
            self.config['DEFAULT'].update(dialog.result)
            self.save_config()

    def save_config(self):
        with open(self.config_file, 'w') as configfile:
            self.config.write(configfile)
        messagebox.showinfo("Config Saved", "Configuration has been saved.")

    def load_config(self):
        self.config.read(self.config_file)
        if 'DEFAULT' not in self.config:
            self.config['DEFAULT'] = {
                'api_key': 'xxxxxx',
                'exchange': 'NSE',
                'product': 'MIS'
            }
        else:
            defaults = {'api_key': 'xxxxxx', 'exchange': 'NSE', 'product': 'MIS'}
            for key, value in defaults.items():
                if key not in self.config['DEFAULT']:
                    self.config['DEFAULT'][key] = value

def launch_trading_app():
    if sys.platform.startswith('linux'):
        # For Linux, ensure Tkinter is properly initialized
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    app = TradingApp(root)
    root.mainloop()

if __name__ == "__main__":
    launch_trading_app()
