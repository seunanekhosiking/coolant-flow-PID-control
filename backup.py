import tkinter as tk
from tkinter import ttk
from pymodbus.client import ModbusTcpClient
import threading
import time
from collections import deque

# --- Modbus Setup ---
client = ModbusTcpClient(host='192.168.0.149', port=502)
client.connect()

# --- GUI Setup ---
root = tk.Tk()
root.title("Coolant System Dashboard")

# --- Global State ---
system_running = False
current_mode = None
last_flows = {0: None, 1: None}
target_flow = 2.0
flow_history = deque(maxlen=20)
fill_timestamps = []

# --- GUI Variables ---
level_var = tk.StringVar()
flow_var = tk.StringVar()
max_flow_var = tk.StringVar()
avg_flow_var = tk.StringVar()
valve_var = tk.StringVar()
target_var = tk.StringVar()
fill_time_var = tk.StringVar()
valve_status = {"fill_valve": tk.StringVar(), "fill_pump": tk.StringVar(),
                "disch_valve": tk.StringVar(), "disch_pump": tk.StringVar()}

# --- Helpers ---
def write_valve_flow(register, flow_value):
    flow = int(flow_value)
    if last_flows.get(register) != flow:
        client.write_register(address=register, value=flow)
        last_flows[register] = flow
        valve_var.set(f"{flow} / 1000")

def delayed_start(pump_coil, label_key):
    time.sleep(3)
    client.write_coil(address=pump_coil, value=True)
    valve_status[label_key].set("🟢 ON")

def stop_all():
    client.write_coils(address=0, values=[False]*4)
    write_valve_flow(0, 0)
    write_valve_flow(1, 0)
    for var in valve_status.values():
        var.set("🔴 OFF")

def update_target(avg_flow):
    global target_flow
    if avg_flow < 1.95:
        target_flow = min(2.2, target_flow + 0.01)
    elif avg_flow > 2.05:
        target_flow = max(1.8, target_flow - 0.01)
    target_var.set(f"{target_flow:.2f}")

def control_logic(level_raw, flow_raw):
    global current_mode, system_running

    level = round(level_raw, 1)
    flow = round(flow_raw, 1)

    # Update GUI
    flow_var.set(f"{flow:.1f} L/min")
    level_var.set(f"{level:.1f} / 10.0")

    if not system_running:
        stop_all()
        current_mode = None
        return

    # --- FILL Logic ---
    if level < 3.0:
        if current_mode != 'filling':
            stop_all()
            client.write_coil(0, True)
            valve_status["fill_valve"].set("🟢 ON")
            threading.Thread(target=lambda: delayed_start(1, "fill_pump"), daemon=True).start()
            write_valve_flow(0, 1000)
            fill_timestamps.append(time.time())
            current_mode = 'filling'
    elif level >= 10.0 and current_mode == 'filling':
        stop_all()
        current_mode = None
        if len(fill_timestamps) >= 2:
            intervals = [t2 - t1 for t1, t2 in zip(fill_timestamps[:-1], fill_timestamps[1:])]
            avg_fill_sec = sum(intervals) / len(intervals)
            fill_time_var.set(f"{avg_fill_sec:.1f} sec")

    # --- DISCHARGE Logic ---
    client.write_coil(2, True)
    valve_status["disch_valve"].set("🟢 ON")
    threading.Thread(target=lambda: delayed_start(3, "disch_pump"), daemon=True).start()

    flow_history.append(flow)
    if len(flow_history) == flow_history.maxlen:
        avg = sum(flow_history) / len(flow_history)
        update_target(avg)
        avg_flow_var.set(f"{avg:.2f}")
        max_flow_var.set(f"{max(flow_history):.1f}")

    error = target_flow - flow
    if abs(error) < 0.01:
        valve = last_flows.get(1, 500)
    else:
        gain = 100
        valve = last_flows.get(1, 500) + int(gain * error)
        valve = max(0, min(1000, valve))

    write_valve_flow(1, valve)

# --- Polling Loop ---
def update_loop():
    while True:
        reg = client.read_input_registers(address=0, count=2)
        if not reg.isError():
            level = reg.registers[0] / 100.0
            flow = reg.registers[1] / 100.0
            progress["value"] = level
            control_logic(level, flow)
        time.sleep(1)

# --- GUI Layout ---
row = 0
tk.Label(root, text="Tank Level").grid(row=row, column=0, sticky='w')
tk.Label(root, textvariable=level_var).grid(row=row, column=1, sticky='w'); row += 1

progress = ttk.Progressbar(root, orient="horizontal", length=250, mode="determinate", maximum=10)
progress.grid(row=row, column=0, columnspan=2, pady=5); row += 1

tk.Label(root, text="Flow Rate").grid(row=row, column=0, sticky='w')
tk.Label(root, textvariable=flow_var).grid(row=row, column=1, sticky='w'); row += 1

tk.Label(root, text="Valve Output").grid(row=row, column=0, sticky='w')
tk.Label(root, textvariable=valve_var).grid(row=row, column=1, sticky='w'); row += 1

tk.Label(root, text="Target Flow").grid(row=row, column=0, sticky='w')
tk.Label(root, textvariable=target_var).grid(row=row, column=1, sticky='w'); row += 1

tk.Label(root, text="Max Flow").grid(row=row, column=0, sticky='w')
tk.Label(root, textvariable=max_flow_var).grid(row=row, column=1, sticky='w'); row += 1

tk.Label(root, text="Avg Flow").grid(row=row, column=0, sticky='w')
tk.Label(root, textvariable=avg_flow_var).grid(row=row, column=1, sticky='w'); row += 1

tk.Label(root, text="Avg Fill Interval").grid(row=row, column=0, sticky='w')
tk.Label(root, textvariable=fill_time_var).grid(row=row, column=1, sticky='w'); row += 1

for label in ["Fill Valve", "Fill Pump", "Disch Valve", "Disch Pump"]:
    key = label.lower().replace(" ", "_")
    tk.Label(root, text=label).grid(row=row, column=0, sticky='w')
    tk.Label(root, textvariable=valve_status[key]).grid(row=row, column=1, sticky='w')
    valve_status[key].set("🔴 OFF")
    row += 1

def toggle_system():
    global system_running, current_mode
    system_running = not system_running
    current_mode = None
    system_btn.config(
        text="STOP SYSTEM" if system_running else "START SYSTEM",
        bg='red' if system_running else 'green'
    )

system_btn = tk.Button(root, text="START SYSTEM", width=22, bg='green', fg='white', command=toggle_system)
system_btn.grid(row=row, column=0, columnspan=2, pady=10)

# --- Launch ---
threading.Thread(target=update_loop, daemon=True).start()
root.mainloop()
client.close()
