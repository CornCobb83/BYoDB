import pygame
import sys
import tkinter as tk
import math
from tkinter import filedialog, messagebox
import re
from collections import deque
import tkinter as tk
import os
from collections import defaultdict
from datetime import datetime
import sqlite3

insert_blocks = []

def draw_curved_arrow(surface, start, end, color=(50, 150, 50), width=2):
    # Midpoint with a slight vertical curve
    ctrl = ((start[0] + end[0]) // 2, min(start[1], end[1]) - 50)
    points = [start, ctrl, end]

    # Use quadratic Bezier curve
    def bezier(t):
        x = (1 - t)**2 * start[0] + 2 * (1 - t) * t * ctrl[0] + t**2 * end[0]
        y = (1 - t)**2 * start[1] + 2 * (1 - t) * t * ctrl[1] + t**2 * end[1]
        return (int(x), int(y))

    bezier_points = [bezier(t / 20.0) for t in range(21)]
    pygame.draw.lines(surface, color, False, bezier_points, width)

    # Arrowhead
    if len(bezier_points) >= 2:
        arrow_end = bezier_points[-1]
        arrow_prev = bezier_points[-2]
        draw_arrowhead(surface, arrow_prev, arrow_end, color=color, size=15)

def draw_arrowhead(surface, start, end, color=(50, 150, 50), size=20):
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    left = (end[0] - size * math.cos(angle - 0.3), end[1] - size * math.sin(angle - 0.3))
    right = (end[0] - size * math.cos(angle + 0.3), end[1] - size * math.sin(angle + 0.3))
    pygame.draw.polygon(surface, color, [end, left, right])

def make_window(title="Window", bg="#c8c8ff", resize_height=False, resize_width=False, min_size=(400, 300)):
    win = tk.Toplevel()
    win.title(title)
    win.configure(bg=bg)

    def set_min_size():
        win.update_idletasks()
        w, h = win.winfo_width(), win.winfo_height()
        if resize_height or resize_width:
            w = max(w, min_size[0])
            h = max(h, min_size[1])
            win.geometry(f"{w}x{h}")
            win.resizable(resize_width, resize_height)
        else:
            win.minsize(w, h)   # user can resize larger, but never shrink too far
            win.resizable(resize_width, resize_height)

    # Run once after layout is computed
    win.after(50, set_min_size)

    return win

def topological_sort_tables(tables):
    graph = defaultdict(set)         # table -> set of tables it depends on
    reverse_graph = defaultdict(set) # table -> set of tables depending on it
    table_map = {t.name: t for t in tables}

    # Step 1: Build dependency graph, ignoring self-dependencies
    for table in tables:
        for field in table.fields:
            is_fk = len(field) > 3 and field[3]
            fk_target = field[4] if len(field) > 4 else None
            if is_fk and fk_target in table_map and fk_target != table.name:
                graph[table.name].add(fk_target)
                reverse_graph[fk_target].add(table.name)

    # Ensure every table appears in graph even if it has no deps
    for t in tables:
        graph.setdefault(t.name, set())

    # Step 2: Kahn's algorithm
    in_degree = {t.name: len(graph[t.name]) for t in tables}
    queue = deque([t.name for t in tables if in_degree[t.name] == 0])
    sorted_names = []

    while queue:
        current = queue.popleft()
        sorted_names.append(current)
        for dependent in reverse_graph[current]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    # Step 3: Detect real cycles (excluding self-loops we skipped earlier)
    if len(sorted_names) != len(tables):
        raise ValueError("Cycle detected in table foreign key references")

    return [table_map[name] for name in sorted_names]

def export_to_sql(tables):
    sql_statements = []

    # Sort tables based on FK dependencies
    sorted_tables = topological_sort_tables(tables)

    # Drop tables first
    for table in reversed(sorted_tables):
        sql_statements.append(f"DROP TABLE {table.name} CASCADE CONSTRAINTS;")

    # Create tables
    for table in sorted_tables:
        column_lines = []
        table_constraints = []

        pk_fields = [f[0] for f in table.fields if len(f) > 2 and f[2]]

        # Inline PK if single PK field
        for field in table.fields:
            fname = field[0]
            ftype = field[1]
            is_pk = field[2] if len(field) > 2 else False
            is_fk = field[3] if len(field) > 3 else False
            fk_target = field[4] if len(field) > 4 else None
            fk_ref_col = field[5] if len(field) > 5 else None

            line = f"  {fname} {ftype}"
            if is_pk and len(pk_fields) == 1:
                line += " PRIMARY KEY"
            column_lines.append(line)

        # Table-level PK for composite keys
        if len(pk_fields) > 1:
            table_constraints.append(f"  PRIMARY KEY ({', '.join(pk_fields)})")

        # Add composite foreign keys from new attribute, if present
        if hasattr(table, 'composite_foreign_keys'):
            for local_cols, ref_table, ref_cols in table.composite_foreign_keys:
                if len(local_cols) != len(ref_cols):
                    print(f"[Warning] FK length mismatch in table {table.name}")
                    continue
                local_cols_str = ", ".join(local_cols)
                ref_cols_str = ", ".join(ref_cols)
                constraint = f"  FOREIGN KEY ({local_cols_str}) REFERENCES {ref_table}({ref_cols_str})"
                table_constraints.append(constraint)

        else:
            # Fallback: handle single-column foreign keys, grouped by target table
            fk_groups = {}  # target_table -> list of (local_col, ref_col)
            for field in table.fields:
                fname = field[0]
                is_fk = field[3] if len(field) > 3 else False
                fk_target = field[4] if len(field) > 4 else None
                fk_ref_col = field[5] if len(field) > 5 else None

                if is_fk and fk_target:
                    ref_col = fk_ref_col if fk_ref_col else 'ID'
                    fk_groups.setdefault(fk_target, []).append((fname, ref_col))

            for target, pairs in fk_groups.items():
                local_cols = ", ".join(local for local, _ in pairs)
                ref_cols   = ", ".join(remote for _, remote in pairs)
                constraint = f"  FOREIGN KEY ({local_cols}) REFERENCES {target}({ref_cols})"
                table_constraints.append(constraint)

        all_lines = column_lines + table_constraints
        create_stmt = f"CREATE TABLE {table.name} (\n" + ",\n".join(all_lines) + "\n);"
        sql_statements.append(create_stmt)

    return "\n\n".join(sql_statements)

def import_sql():
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(filetypes=[("SQL files", "*.sql")])
    if not file_path:
        return

    with open(file_path, 'r') as f:
        sql = f.read()

    tables.clear()

    create_statements = re.findall(r'create table (\w+)\s*\((.*?)\);', sql, re.IGNORECASE | re.DOTALL)

    for idx, (table_name, body) in enumerate(create_statements):
        table = Table(100 + (idx % 5) * 180, 100 + (idx // 5) * 160, name=table_name.upper())
        lines = [line.strip().rstrip(',') for line in body.splitlines() if line.strip()]

        pk_fields = set()
        pending_fks = []  # list of (local_cols[], ref_table, ref_cols[])

        for line in lines:
            lower = line.lower()

            # --- Table-level PRIMARY KEY (composite or not) ---
            if lower.startswith("primary key"):
                match = re.search(r'\((.*?)\)', line)
                if match:
                    pk_fields.update(f.strip().upper() for f in match.group(1).split(','))
                continue

            # --- Table-level FOREIGN KEY (composite or single column) ---
            if lower.startswith("foreign key"):
                fk_match = re.search(
                    r'foreign key\s*\((.*?)\)\s*references\s+(\w+)(?:\s*\((.*?)\))?',
                    line, re.IGNORECASE)
                if fk_match:
                    local_cols = [col.strip().upper() for col in fk_match.group(1).split(',')]
                    ref_table = fk_match.group(2).upper()
                    if fk_match.group(3):
                        ref_cols = [col.strip().upper() for col in fk_match.group(3).split(',')]
                    else:
                        ref_cols = local_cols[:]
                    pending_fks.append((local_cols, ref_table, ref_cols))
                continue

            # --- Inline field definition ---
            field_match = re.match(r'^(\w+)\s+(\w+(?:\(\d+\))?)(.*)$', line, re.IGNORECASE)
            if field_match:
                fname = field_match.group(1).upper()
                ftype = field_match.group(2).strip()
                constraints = field_match.group(3).strip().lower()

                is_pk = 'primary key' in constraints
                is_fk = 'references' in constraints
                ref_table = None
                ref_col = None

                if is_fk:
                    ref_match = re.search(r'references\s+(\w+)\s*(?:\((\w+)\))?', constraints, re.IGNORECASE)
                    if ref_match:
                        ref_table = ref_match.group(1).upper()
                        ref_col = ref_match.group(2).upper() if ref_match.group(2) else 'ID'

                table.fields.append((fname, ftype, is_pk, is_fk, ref_table, ref_col))

        # --- Apply table-level primary key flags ---
        if pk_fields:
            for i, f in enumerate(table.fields):
                if f[0] in pk_fields:
                    table.fields[i] = (f[0], f[1], True, f[3], f[4], f[5])

        # --- Store composite PK if needed ---
        if len(pk_fields) > 1:
            table.composite_primary_keys = list(pk_fields)
        else:
            table.composite_primary_keys = []

        # --- Apply table-level foreign key relationships ---
        for local_cols, ref_table, ref_cols in pending_fks:
            if len(local_cols) != len(ref_cols):
                print(f"[WARNING] FK length mismatch in table {table.name}")
                continue
            for local_col, ref_col in zip(local_cols, ref_cols):
                for i, f in enumerate(table.fields):
                    if f[0] == local_col:
                        table.fields[i] = (f[0], f[1], f[2], True, ref_table, ref_col)

        tables.append(table)

pygame.init()

# Screen settings
WIDTH, HEIGHT = 1000, 700
screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
pygame.display.set_caption("BYoDB - Build Your own Data Base")

# Colors and fonts
BG_COLOR = (245, 245, 245)
TABLE_COLOR = (200, 200, 255)
TABLE_BORDER = (100, 100, 200)
SELECTED_COLOR = (180, 180, 250)
TEXT_COLOR = (0, 0, 0)
BUTTON_COLOR = (100, 180, 100)
BUTTON_HOVER_COLOR = (120, 200, 120)
FONT = pygame.font.SysFont("Arial", 18)
BUTTON_FONT = pygame.font.SysFont("Arial", 20, bold=True)

def update_ui_layout():
    global info_button_rect, save_button_rect, import_button_rect, query_button_rect, pop_table_button_rect, trigger_button_rect, update_generator_button_rect
    screen_w, screen_h = screen.get_size()
    info_button_rect = pygame.Rect(screen_w - 40, 10, 35, 35)
    save_button_rect = pygame.Rect(10, 10, 140, 35)
    import_button_rect = pygame.Rect(160, 10, 140, 35)
    query_button_rect = pygame.Rect(160, screen_h - 50, 140, 40)  # adjust x, y, width, height
    pop_table_button_rect = pygame.Rect(10, screen_h - 50, 140, 40)  # adjust x, y, width, height
    trigger_button_rect = pygame.Rect(310, screen_h - 50, 140, 40)  # adjust x, y, width, height
    update_generator_button_rect = pygame.Rect(460, screen_h - 50, 140, 40)  # adjust x, y, width, height



def open_edit_window(table):
    root = tk.Tk()
    root.withdraw()
    edit_win = make_window(
        "Edit Table Schema", 
        bg="#c8c8ff", 
        resize_height=True, 
        resize_width=False,
        min_size=(600, 400)  # Minimum size for the edit window
    )
    
    default_font = ("Consolas", 11)
    label_font = ("Consolas", 12, "bold")
    
    # Center main frame
    edit_win.columnconfigure(0, weight=1)
    edit_win.rowconfigure(0, weight=1)
    
    main_frame = tk.Frame(edit_win, bg="#c8c8ff")
    main_frame.grid(row=0, column=0, sticky="nsew")
    
    def tech_label(text, **kwargs):
        return tk.Label(main_frame, text=text, fg="#1a1a66", bg="#c8c8ff", font=label_font, **kwargs)
    
    # Header
    tech_label("🧠 Edit Table Schema").pack(pady=(10, 5))
    
    # Table name
    tech_label("Table Name:").pack()
    name_entry = tk.Entry(main_frame, width=30, font=default_font, bg="#e8e8ff", fg="#1a1a66")
    name_entry.insert(0, table.name)
    name_entry.pack(pady=5)
    
    tech_label("Fields").pack(pady=(10, 0))
    tk.Label(main_frame, text="Name, Type, PK (🔑), FK ↴", fg="#4b4b7d", bg="#c8c8ff",
             font=("Consolas", 9)).pack()
    
    # Scrollable frame for fields
    container = tk.Frame(main_frame, bg="#c8c8ff")
    container.pack(pady=5, padx=10, fill="both", expand=True)
    
    canvas = tk.Canvas(container, bg="#c8c8ff", highlightthickness=0)
    scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas, bg="#c8c8ff")
    
    scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    
    canvas.create_window((0, 0), window=scrollable_frame, anchor="n")  # top-center
    canvas.configure(yscrollcommand=scrollbar.set)
    
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    
    field_entries = []
    
    def add_field_row(field_name="", field_type="", is_pk=False, _is_fk=False, fk_target=None, fk_column=None):
        row = tk.Frame(scrollable_frame, bg="#e8e8ff", padx=5, pady=4, bd=1, relief="ridge")
        row.pack(pady=4)
        
        fname = tk.Entry(row, width=18, font=default_font, bg="#ffffff")
        fname.insert(0, field_name)
        fname.pack(side=tk.LEFT, padx=(4, 2))
        
        ftype = tk.Entry(row, width=10, font=default_font, bg="#ffffff")
        ftype.insert(0, field_type)
        ftype.pack(side=tk.LEFT, padx=2)
        
        pk_var = tk.BooleanVar(value=is_pk)
        tk.Checkbutton(row, text="🔑", variable=pk_var, bg="#e8e8ff").pack(side=tk.LEFT, padx=2)
        
        fk_target_var = tk.StringVar(value=fk_target or "-None-")
        fk_options = ["-None-"] + [t.name for t in tables if t != table]
        fk_menu = tk.OptionMenu(row, fk_target_var, *fk_options)
        fk_menu.config(width=12)
        fk_menu.pack(side=tk.LEFT, padx=2)
        
        fk_column_var = tk.StringVar(value=fk_column or "")
        fk_col_menu = tk.OptionMenu(row, fk_column_var, "")
        fk_col_menu.config(width=12)
        fk_col_menu.pack(side=tk.LEFT, padx=2)
        
        def update_fk_columns(*_):
            target_table = next((t for t in tables if t.name == fk_target_var.get()), None)
            if target_table:
                fk_col_menu["menu"].delete(0, "end")
                for f in target_table.fields:
                    fk_col_menu["menu"].add_command(label=f[0], command=tk._setit(fk_column_var, f[0]))
                if fk_column_var.get() not in [f[0] for f in target_table.fields]:
                    fk_column_var.set("")
        
        fk_target_var.trace_add("write", update_fk_columns)
        update_fk_columns()
        
        def delete_row():
            field_entries.remove(entry)
            row.destroy()
        
        del_btn = tk.Button(row, text="❌", fg="#990000", command=delete_row, bg="#e8e8ff")
        del_btn.pack(side=tk.LEFT, padx=(6, 2))
        
        entry = (fname, ftype, pk_var, fk_target_var, fk_column_var)
        field_entries.append(entry)
    
    for field in table.fields:
        add_field_row(*field[:6])
    
    # Bottom buttons centered
    control_frame = tk.Frame(main_frame, bg="#c8c8ff")
    control_frame.pack(pady=10)
    
    add_button = tk.Button(control_frame, text="➕ Add Field", command=add_field_row,
                           font=default_font, bg="#ffffff")
    add_button.pack(side=tk.LEFT, padx=5)
    
    def save_and_close():
        table.name = name_entry.get()
        table.fields.clear()
        for fname, ftype, pk_var, fk_target_var, fk_column_var in field_entries:
            name = fname.get().strip()
            type_ = ftype.get().strip()
            is_pk = pk_var.get()
            fk_table = fk_target_var.get().strip()
            if fk_table == "-None-":
                fk_table = None
            fk_field = fk_column_var.get().strip() or None
            if name and type_:
                is_fk = fk_table is not None and fk_field is not None
                table.fields.append((name, type_, is_pk, is_fk, fk_table, fk_field))
        edit_win.destroy()
    
    save_button = tk.Button(control_frame, text="💾 Save Table", command=save_and_close,
                            font=default_font, bg="#ffffff")
    save_button.pack(side=tk.LEFT, padx=5)
    
    def delete_table():
        if table in tables:
            tables.remove(table)
        edit_win.destroy()
    
    delete_button = tk.Button(control_frame, text="🗑️ Delete Table", command=delete_table,
                              font=default_font, bg="#ffffff", fg="#990000")
    delete_button.pack(side=tk.LEFT, padx=5)
    
    edit_win.grab_set()
    edit_win.wait_window()
    root.destroy()

def save_triggers_to_file(trigger_blocks, filename="triggers.sql"):
    """Save triggers to an SQL file."""
    with open(filename, "w", encoding="utf-8") as f:
        for trig in trigger_blocks:
            trigger_sql = f"""CREATE TRIGGER {trig[0]}
{trig[2]} {trig[3]} ON {trig[1]}
FOR EACH ROW
BEGIN
{trig[5]}
END;
"""
            f.write(trigger_sql + "\n\n")

def load_triggers_from_file(filename="triggers.sql"):
    """Load triggers from an SQL file (very simple parser)."""
    if not os.path.exists(filename):
        return []

    with open(filename, "r", encoding="utf-8") as f:
        sql_text = f.read()

    # Split on CREATE TRIGGER statements
    triggers = []
    chunks = [chunk.strip() for chunk in sql_text.split("CREATE TRIGGER") if chunk.strip()]
    for chunk in chunks:
        lines = chunk.splitlines()
        header = lines[0].strip()
        name = header.split()[0]
        timing, event, table = None, None, None

        # crude parse
        for line in lines:
            if "BEFORE" in line or "AFTER" in line:
                parts = line.split()
                timing = parts[0]
                event = parts[1]
                table = parts[-1]
                break

        body_start = next((i for i, l in enumerate(lines) if l.strip() == "BEGIN"), None)
        body_end = next((i for i, l in enumerate(lines) if l.strip() == "END;"), None)
        body = "\n".join(lines[body_start+1:body_end]) if body_start and body_end else ""

        triggers.append((name, table, timing, event, [], body))

    return triggers

trigger_blocks = []  # (name, table, timing, event, columns, body)

def open_trigger_window():
    global trigger_window_open, trigger_blocks, tables

    if trigger_window_open or not tables:
        return
    
    trigger_window_open = True

    win = make_window(
        "Triggers Management", 
        bg="#c8c8ff",
        resize_height=False,
        resize_width=False
        )

    def on_close():
        global trigger_window_open
        trigger_window_open = False
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)
    win.resizable(False, False)

    default_font = ("Consolas", 11)
    label_font = ("Consolas", 10, "bold")

    # --- Data structures ---
    currently_editing_index = [None]

    # --- Top Frame: Trigger Properties ---
    top_frame = tk.Frame(win, bg="#c8c8ff")
    top_frame.pack(fill='x', pady=10, padx=10)

    tk.Label(top_frame, text="Trigger Name:", bg="#c8c8ff", font=label_font).grid(row=0, column=0, sticky="w")
    trigger_name_var = tk.StringVar()
    tk.Entry(top_frame, textvariable=trigger_name_var, width=30, font=default_font).grid(row=0, column=1, sticky="w", padx=5)

    tk.Label(top_frame, text="Timing:", bg="#c8c8ff", font=label_font).grid(row=0, column=2, sticky="w", padx=10)
    timing_var = tk.StringVar(value="AFTER")
    tk.OptionMenu(top_frame, timing_var, "BEFORE", "AFTER").grid(row=0, column=3, sticky="w")

    tk.Label(top_frame, text="Event:", bg="#c8c8ff", font=label_font).grid(row=1, column=0, sticky="w")
    event_var = tk.StringVar(value="INSERT")
    tk.OptionMenu(top_frame, event_var, "INSERT", "UPDATE", "DELETE").grid(row=1, column=1, sticky="w")

    tk.Label(top_frame, text="Target Table:", bg="#c8c8ff", font=label_font).grid(row=1, column=2, sticky="w")
    table_var = tk.StringVar(value="")
    table_options = [t.name for t in tables]
    table_dropdown = tk.OptionMenu(top_frame, table_var, *table_options)
    table_dropdown.grid(row=1, column=3, sticky="w")

    # --- Column Audit List ---
    col_frame = tk.LabelFrame(win, text="Columns to Audit", padx=10, pady=10, bg="#c8c8ff", fg="#1a1a66", font=label_font)
    col_frame.pack(fill='both', padx=10, pady=5)

    col_listbox = tk.Listbox(col_frame, selectmode=tk.MULTIPLE, height=6, bg="#f0f0ff", font=default_font)
    col_listbox.pack(fill='both', expand=True)

    def update_columns(*_):
        col_listbox.delete(0, tk.END)
        target_table = next((t for t in tables if t.name == table_var.get()), None)
        if target_table:
            audit_table_name = f"{target_table.name}_AUDIT"
            
            # Auto-create audit table if it doesn't exist
            if audit_table_name not in [t.name for t in tables]:
                # Minimal audit table definition
                audit_fields = [
                    ("ID", "INTEGER PRIMARY KEY AUTOINCREMENT"),
                    ("TRIGGER_TIME", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
                    ("TABLE_NAME", "TEXT"),
                    ("COLUMN_NAME", "TEXT"),
                    ("OLD_VALUE", "TEXT"),
                    ("NEW_VALUE", "TEXT")
                ]
                new_audit_table = Table(50, 50, name=audit_table_name)
                new_audit_table.fields = audit_fields
                tables.append(new_audit_table)
            
            for field in target_table.fields:
                col_listbox.insert(tk.END, field[0])

    table_var.trace_add("write", update_columns)

    # --- Trigger Body ---
    body_frame = tk.LabelFrame(win, text="Trigger Body (SQL)", padx=10, pady=10, bg="#c8c8ff", fg="#1a1a66", font=label_font)
    body_frame.pack(fill='both', padx=10, pady=5, expand=True)

    body_text = tk.Text(body_frame, wrap="none", height=8, bg="#f8f8ff", font=default_font)
    body_text.pack(fill='both', expand=True)

    # --- Trigger Listbox ---
    list_frame = tk.Frame(win, bg="#c8c8ff")
    list_frame.pack(fill='both', pady=5, padx=10)

    trigger_listbox = tk.Listbox(list_frame, width=120, height=6, bg="#f0f0ff", font=default_font)
    trigger_listbox.pack(side="left", fill='both', expand=True)
    v_scroll = tk.Scrollbar(list_frame, orient="vertical", command=trigger_listbox.yview)
    trigger_listbox.config(yscrollcommand=v_scroll.set)
    v_scroll.pack(side="right", fill="y")

    # --- Functions ---
    def refresh_trigger_list():
        trigger_listbox.delete(0, tk.END)
        for trig in trigger_blocks:
            trigger_listbox.insert(tk.END, f"{trig[0]} ({trig[2]} {trig[3]} ON {trig[1]})")

    def generate_trigger():
        name = trigger_name_var.get().strip()
        table = table_var.get().strip()
        timing = timing_var.get()
        event = event_var.get()

        if not name or not table:
            messagebox.showwarning("Missing Info", "Please provide trigger name and table.")
            return

        selected_cols = [col_listbox.get(i) for i in col_listbox.curselection()]

        # Only generate audit statements for this trigger
        trigger_body = "\n".join([
            f"INSERT INTO {table}_audit (column_name, old_value, new_value) "
            f"VALUES ('{col}', :OLD.{col}, :NEW.{col});"
            for col in selected_cols
        ])

        # Check if trigger exists
        existing_index = next((i for i, t in enumerate(trigger_blocks) if t[0] == name), None)

        if existing_index is not None:
            # Update existing trigger
            trigger_blocks[existing_index] = (name, table, timing, event, selected_cols, trigger_body)
            updated_index = existing_index
        else:
            # Create new trigger
            trigger_blocks.append((name, table, timing, event, selected_cols, trigger_body))
            updated_index = len(trigger_blocks) - 1

        refresh_trigger_list()

        # Display only this trigger’s CREATE SQL
        trig = trigger_blocks[updated_index]
        full_sql = f"CREATE TRIGGER {trig[0]} {trig[2]} {trig[3]} ON {trig[1]} FOR EACH ROW\nBEGIN\n{trig[5]}\nEND;"
        body_text.delete("1.0", tk.END)
        body_text.insert(tk.END, full_sql)

        # Reset editing state for next trigger
        currently_editing_index[0] = None

    def edit_selected_trigger():
        selection = trigger_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a trigger to edit.")
            return
        idx = selection[0]
        trig = trigger_blocks[idx]
        trigger_name_var.set(trig[0])
        table_var.set(trig[1])
        timing_var.set(trig[2])
        event_var.set(trig[3])
        body_text.delete("1.0", tk.END)
        body_text.insert(tk.END, trig[5])
        # select columns
        update_columns()
        for i, col in enumerate(col_listbox.get(0, tk.END)):
            if col in trig[4]:
                col_listbox.selection_set(i)
        currently_editing_index[0] = idx

    def delete_selected_trigger():
        selection = trigger_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a trigger to delete.")
            return
        idx = selection[0]
        del trigger_blocks[idx]
        refresh_trigger_list()

    def copy_trigger_to_clipboard():
        selection = trigger_listbox.curselection()
        if not selection:
            return
        idx = selection[0]
        trig = trigger_blocks[idx]
        trigger_sql = f"CREATE TRIGGER {trig[0]} {trig[2]} {trig[3]} ON {trig[1]} FOR EACH ROW\nBEGIN\n{trig[5]}\nEND;"
        win.clipboard_clear()
        win.clipboard_append(trigger_sql)
        messagebox.showinfo("Copied", f"Trigger SQL copied to clipboard.")

    # --- Buttons ---
    btn_frame = tk.Frame(win, bg="#c8c8ff")
    btn_frame.pack(fill='x', pady=5, padx=10)

    def save_triggers():
        filename = filedialog.asksaveasfilename(
            defaultextension=".sql",
            filetypes=[("SQL Files", "*.sql"), ("All Files", "*.*")]
        )
        if filename:
            save_triggers_to_file(trigger_blocks, filename)
            messagebox.showinfo("Saved", f"Triggers saved to {filename}")

    def load_triggers():
        filename = filedialog.askopenfilename(
            filetypes=[("SQL Files", "*.sql"), ("All Files", "*.*")]
        )
        if filename:
            loaded = load_triggers_from_file(filename)
            trigger_blocks.clear()
            trigger_blocks.extend(loaded)
            refresh_trigger_list()
            messagebox.showinfo("Loaded", f"Triggers loaded from {filename}")

    tk.Button(btn_frame, text="💾 Save Triggers", command=save_triggers, bg="#ffffff", fg="#1a1a66", font=default_font).pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text="📂 Load Triggers", command=load_triggers, bg="#ffffff", fg="#1a1a66", font=default_font).pack(side=tk.LEFT, padx=5)

    tk.Button(btn_frame, text="➕ Add / Update Trigger", command=generate_trigger, bg="#ffffff", fg="#1a1a66", font=default_font).pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text="✏ Edit Trigger", command=edit_selected_trigger, bg="#ffffff", fg="#1a1a66", font=default_font).pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text="🗑 Delete Trigger", command=delete_selected_trigger, bg="#ffffff", fg="#1a1a66", font=default_font).pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text="📋 Copy SQL", command=copy_trigger_to_clipboard, bg="#ffffff", fg="#1a1a66", font=default_font).pack(side=tk.LEFT, padx=5)

def open_populate_window():
    global populate_window_open

    if populate_window_open or not tables:
        return

    populate_window_open = True

    win = make_window(
        "Populate Tables with Data",
        bg="#c8c8ff",
        min_size=(600, 400)
    )

    def on_close():
        global populate_window_open
        populate_window_open = False
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)

    default_font = ("Consolas", 11)
    label_font = ("Consolas", 10, "bold")

    selected_table_var = tk.StringVar()
    insert_entries = {}
    global insert_blocks
    existing_pk_values = defaultdict(set)
    filtered_insert_blocks = []
    currently_editing_index = [None]

    # -------- Search + Listbox Frame with Scrollbars --------
    list_frame = tk.Frame(win, bg="#c8c8ff")
    list_frame.pack(fill='both', expand=False, padx=10, pady=5)

    search_frame = tk.Frame(list_frame, bg="#c8c8ff")
    search_frame.pack(fill='x', pady=5)

    tk.Label(search_frame, text="🔍 Search:", bg="#c8c8ff", fg="#1a1a66", font=label_font).pack(side=tk.LEFT, padx=5)
    search_entry = tk.Entry(search_frame, width=40, font=default_font)
    search_entry.pack(side=tk.LEFT, expand=True, fill='x', padx=5)

    # Listbox with vertical and horizontal scrollbars
    listbox_frame = tk.Frame(list_frame)
    listbox_frame.pack(fill='both', expand=True)

    insert_listbox = tk.Listbox(listbox_frame, width=120, height=12, bg="#f0f0ff", fg="#1a1a66", font=("Consolas", 10))
    v_scroll = tk.Scrollbar(listbox_frame, orient="vertical", command=insert_listbox.yview)
    h_scroll = tk.Scrollbar(listbox_frame, orient="horizontal", command=insert_listbox.xview)

    insert_listbox.config(yscrollcommand=v_scroll.set, xscrollcommand=h_scroll.set)
    insert_listbox.pack(side="left", fill='both', expand=True)
    v_scroll.pack(side="right", fill="y")
    h_scroll.pack(side="bottom", fill="x")

    search_entry.bind("<KeyRelease>", lambda e: update_insert_listbox())

    # -------- Control Buttons --------
    control_frame = tk.Frame(win, bg="#c8c8ff")
    control_frame.pack(pady=5)

    def edit_selected_row():
        selection = insert_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a row to edit.")
            return

        idx_in_list = selection[0]
        original_index, table_name, stmt = filtered_insert_blocks[idx_in_list]

        target_table = next((t for t in tables if t.name == table_name), None)
        if not target_table:
            return

        # Set dropdown and trigger update
        selected_table_var.set(table_name)
        update_fields()

        # Extract field values
        match = re.match(
            r"insert\s+into\s+(\w+)\s*(?:\((.*?)\))?\s*values\s*\((.*?)\)\s*;",
            stmt.strip(), re.IGNORECASE | re.DOTALL
        )

        matched_table, fields_str, values_str = match.groups()
        raw_values = [v.strip() for v in re.split(r",(?![^()]*\))", values_str)]

        # Autofill column names if missing
        if fields_str:
            fields = [f.strip().upper() for f in fields_str.split(",")]
        else:
            if target_table and len(raw_values) == len(target_table.fields):
                fields = [f[0].upper() for f in target_table.fields]
            else:
                messagebox.showerror("Missing Fields", "Cannot infer field names without matching table structure.")
                return

        # Clean up value formatting (remove quotes, etc.)
        cleaned_values = []
        for val in raw_values:
            if val.upper() == "NULL":
                cleaned_values.append("")
            elif val.startswith("'") and val.endswith("'"):
                cleaned_values.append(val[1:-1])
            else:
                cleaned_values.append(val)

        # Fill entries
        for field_name, value in zip(fields, cleaned_values):
            if field_name in insert_entries:
                entry, include_var = insert_entries[field_name]
                entry.delete(0, tk.END)
                entry.insert(0, value)
                include_var.set(True)

        # Track index for replacement on "Add"
        currently_editing_index[0] = original_index

    # Bind selection event to enable Edit/Delete buttons
    def on_listbox_select(event):
        selection = insert_listbox.curselection()
        if selection:
            edit_btn.config(state=tk.NORMAL)
            delete_btn.config(state=tk.NORMAL)
        else:
            edit_btn.config(state=tk.DISABLED)
            delete_btn.config(state=tk.DISABLED)

    def update_insert_listbox():
        search_term = search_entry.get().strip().lower()
        insert_listbox.delete(0, tk.END)
        filtered_insert_blocks.clear()
        for i, (table_name, stmt) in enumerate(insert_blocks):
            if search_term in stmt.lower():
                insert_listbox.insert(tk.END, f"[{table_name}] {stmt}")
                filtered_insert_blocks.append((i, table_name, stmt))

    def delete_selected_row():
        selection = insert_listbox.curselection()
        if not selection:
            messagebox.showwarning("No Selection", "Please select a row to delete.")
            return

        idx_to_remove, table_name, stmt = filtered_insert_blocks[selection[0]]
        del insert_blocks[idx_to_remove]

        # Remove PK cache entry for deleted stmt
        target_table = next((t for t in tables if t.name == table_name), None)
        if target_table:
            pk_fields = [f[0] for f in target_table.fields if len(f) > 2 and f[2]]
            for pk in existing_pk_values[table_name].copy():
                if all(str(val) in stmt for val in pk):
                    existing_pk_values[table_name].remove(pk)
                    break

        refresh_insert_text()
        update_insert_listbox()

    delete_btn = tk.Button(control_frame, text="🗑 Delete Row", width=15, state=tk.DISABLED,
                       bg="#ffffff", fg="#1a1a66", font=default_font, command=delete_selected_row)
    edit_btn = tk.Button(control_frame, text="✏ Edit Row", width=15, state=tk.DISABLED,
                        bg="#ffffff", fg="#1a1a66", font=default_font, command=edit_selected_row)
    delete_btn.pack(side=tk.LEFT, padx=5)
    edit_btn.pack(side=tk.LEFT, padx=5)

    insert_listbox.bind("<<ListboxSelect>>", on_listbox_select)

    # -------- Field Frame (dropdown + fields) --------
    top_frame = tk.Frame(win, bg="#c8c8ff")
    top_frame.pack(fill='x', pady=10, padx=10)

    tk.Label(top_frame, text="Select Table:", bg="#c8c8ff", fg="#1a1a66", font=label_font).pack(side=tk.LEFT, padx=5)
    table_options = [t.name for t in tables]
    selected_table_var.set("")  # Start with empty

    table_dropdown = tk.OptionMenu(top_frame, selected_table_var, *table_options)
    table_dropdown.config(bg="#d0d0f0", fg="#1a1a66", font=default_font)
    table_dropdown.pack(side=tk.LEFT)

    # Bind dropdown changes to update_fields
    selected_table_var.trace_add("write", lambda *args: update_fields())

    field_frame = tk.LabelFrame(win, text="Fields to Insert", padx=10, pady=10, bg="#c8c8ff", fg="#1a1a66", font=label_font)
    field_frame.pack(fill='x', padx=10, pady=10)

    def generate_insert():
        table_name = selected_table_var.get()
        if not table_name:
            messagebox.showwarning("No Table Selected", "Please select a table first.")
            return

        target_table = next((t for t in tables if t.name == table_name), None)
        if not target_table:
            return

        values = []
        field_names = []
        pk_fields = [f[0] for f in target_table.fields if len(f) > 2 and f[2]]
        pk_values = []

        for field, (entry, include_var) in insert_entries.items():
            if not include_var.get():
                continue

            val = entry.get().strip()
            field_names.append(field)

            if not val:
                if field in pk_fields:
                    messagebox.showerror("Missing PK Value", f"Primary Key '{field}' cannot be NULL or empty.")
                    return
                values.append("NULL")
            elif val.isdigit():
                values.append(val)
                if field in pk_fields:
                    pk_values.append(val)
            else:
                quoted_val = f"'{val}'"
                values.append(quoted_val)
                if field in pk_fields:
                    pk_values.append(val.lower())

        if not field_names:
            messagebox.showwarning("No Fields Selected", "Please select at least one field.")
            return

        if pk_fields:
            pk_tuple = tuple(pk_values)

            # Are we editing an existing row?
            if currently_editing_index[0] is not None:
                old_stmt = insert_blocks[currently_editing_index[0]][1]
                old_match = re.match(r"insert\s+into\s+\w+\s*\((.*?)\)\s*values\s*\((.*?)\)\s*;", old_stmt.strip(), re.IGNORECASE | re.DOTALL)
                if old_match:
                    old_fields_str, old_values_str = old_match.groups()
                    old_fields = [f.strip().upper() for f in old_fields_str.split(",")]
                    old_raw_values = [v.strip() for v in re.split(r",(?![^()]*\))", old_values_str)]
                    old_cleaned_values = []
                    for val in old_raw_values:
                        if val.upper() == "NULL":
                            old_cleaned_values.append("")
                        elif val.startswith("'") and val.endswith("'"):
                            old_cleaned_values.append(val[1:-1])
                        else:
                            old_cleaned_values.append(val)
                    old_pk_values = [old_cleaned_values[old_fields.index(pk)] for pk in pk_fields if pk in old_fields]
                    old_pk_tuple = tuple(old_pk_values)
                else:
                    old_pk_tuple = None

                # Only check for duplication if the new PK is different
                if pk_tuple != old_pk_tuple and pk_tuple in existing_pk_values[table_name]:
                    messagebox.showerror("Duplicate Primary Key", f"An insert with primary key {pk_tuple} already exists.")
                    return

                # Replace the old PK with the new one
                if old_pk_tuple in existing_pk_values[table_name]:
                    existing_pk_values[table_name].remove(old_pk_tuple)

            elif pk_tuple in existing_pk_values[table_name]:
                messagebox.showerror("Duplicate Primary Key", f"An insert with primary key {pk_tuple} already exists.")
                return

            existing_pk_values[table_name].add(pk_tuple)

        field_str = ", ".join(field_names)
        value_str = ", ".join(values)
        stmt = f"INSERT INTO {table_name} ({field_str}) VALUES ({value_str});"

        # If we're editing an existing row, replace it
        if currently_editing_index[0] is not None:
            insert_blocks[currently_editing_index[0]] = (table_name, stmt)
            currently_editing_index[0] = None  # Reset edit mode
        else:
            insert_blocks.append((table_name, stmt))

        refresh_insert_text()

    def remove_last_insert():
        if insert_blocks:
            table_name, stmt = insert_blocks.pop()
            target_table = next((t for t in tables if t.name == table_name), None)
            if target_table:
                pk_fields = [f[0] for f in target_table.fields if len(f) > 2 and f[2]]
                for pk in existing_pk_values[table_name].copy():
                    if all(str(val) in stmt for val in pk):
                        existing_pk_values[table_name].remove(pk)
                        break
            refresh_insert_text()
        else:
            messagebox.showinfo("Nothing to Remove", "There are no INSERT statements to remove.")

    def validate_inputs():
        errors = []

        if errors:
            messagebox.showerror("Validation Errors", "\n\n".join(errors))
        else:
            messagebox.showinfo("Validation Passed", "All insert statements are valid.")

    def load_insert_statements():
        path = filedialog.askopenfilename(filetypes=[("SQL Files", "*.sql")])
        if not path:
            return
        with open(path, 'r') as f:
            new_text = f.read()
        clear_all()

        current_stmt = ""
        for line in new_text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.lower().startswith("prompt"):
                continue

            current_stmt += " " + stripped
            if stripped.endswith(";"):
                # Remove leading comments before INSERT
                stmt = current_stmt.strip()
                insert_pos = stmt.lower().find("insert into")
                if insert_pos >= 0:
                    stmt = stmt[insert_pos:]
                    match = re.search(
                        r"insert\s+into\s+(\w+)\s*(?:\((.*?)\))?\s*values\s*\((.*?)\)\s*;",
                        stmt,
                        re.IGNORECASE | re.DOTALL
                    )
                    if match:
                        table_name, fields_str, values_str = match.groups()
                        table_name = table_name.upper().strip()
                        fields = [f.strip().upper() for f in fields_str.split(",")] if fields_str else []

                        # Extract values as-is (preserving quoted strings)
                        raw_values = values_str.strip()
                        values = [v.strip() for v in re.split(r",(?![^()]*\))", raw_values)]

                        # Store PKs
                        target_table = next((t for t in tables if t.name == table_name), None)
                        if target_table:
                            pk_fields = [f[0] for f in target_table.fields if len(f) > 2 and f[2]]
                            try:
                                pk_values = [values[fields.index(pk)] for pk in pk_fields if pk in fields]
                                existing_pk_values[table_name].add(tuple(pk_values))
                            except Exception as e:
                                print(f"[WARNING] Couldn't extract PK values for {table_name}: {e}")

                        insert_blocks.append((table_name, stmt))
                    else:
                        print(f"[SKIPPED] Invalid INSERT: {current_stmt.strip()}")
                else:
                    print(f"[SKIPPED] No INSERT found: {current_stmt.strip()}")

                current_stmt = ""  # Reset after processing

        refresh_insert_text()

    def save_insert_statements():
        path = filedialog.asksaveasfilename(defaultextension=".sql", filetypes=[("SQL Files", "*.sql")])
        if not path:
            return
        with open(path, 'w') as f:
            f.write(insert_text.get("1.0", tk.END))
        messagebox.showinfo("Saved", f"Insert statements saved to {os.path.basename(path)}")

    def clear_all():
        insert_blocks.clear()
        existing_pk_values.clear()
        insert_text.delete("1.0", tk.END)
        selected_table_var.set("")
        for widget in field_frame.winfo_children():
            widget.destroy()
        insert_entries.clear()

    def copy_to_clipboard():
        win.clipboard_clear()
        win.clipboard_append(insert_text.get("1.0", tk.END))
        messagebox.showinfo("Copied", "Insert statements copied to clipboard!")

    def update_fields(*_):
        table_name = selected_table_var.get()
        target_table = next((t for t in tables if t.name == table_name), None)
        if not target_table:
            for widget in field_frame.winfo_children():
                widget.destroy()
            return

        for widget in field_frame.winfo_children():
            widget.destroy()
        insert_entries.clear()

        for field in target_table.fields:
            row = tk.Frame(field_frame, bg="#e8e8ff")
            row.pack(padx=10, pady=2, anchor='w')

            include_var = tk.BooleanVar(value=True)
            check = tk.Checkbutton(row, variable=include_var, bg="#e8e8ff", fg="#1a1a66", selectcolor="#c8c8ff")
            check.pack(side=tk.LEFT)

            field_name = field[0]
            field_type = field[1]

            name_label = tk.Label(row, text=field_name, width=20, anchor='w', bg="#e8e8ff", fg="#1a1a66", font=label_font)
            name_label.pack(side=tk.LEFT)

            entry = tk.Entry(row, width=40, bg="#ffffff", fg="#1a1a66", insertbackground="#1a1a66", font=default_font)
            entry.pack(side=tk.LEFT)

            type_label = tk.Label(row, text=f"[{field_type}]", fg="gray", anchor='w', bg="#e8e8ff", font=default_font)
            type_label.pack(side=tk.LEFT, padx=5)

            insert_entries[field_name] = (entry, include_var)

    def refresh_insert_text():
        def topological_sort_table_names(tables):
            graph = defaultdict(set)
            reverse_graph = defaultdict(set)
            table_map = {t.name: t for t in tables}

            for table in tables:
                for field in table.fields:
                    is_fk = len(field) > 3 and field[3]
                    fk_target = field[4] if len(field) > 4 else None
                    if is_fk and fk_target in table_map:
                        graph[table.name].add(fk_target)
                        reverse_graph[fk_target].add(table.name)

            in_degree = {t.name: len(graph[t.name]) for t in tables}
            queue = deque([t.name for t in tables if not graph[t.name]])
            sorted_names = []

            while queue:
                current = queue.popleft()
                sorted_names.append(current)
                for dependent in reverse_graph[current]:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)

            if len(sorted_names) != len(tables):
                raise ValueError("Cycle detected in table foreign key references")

            return sorted_names

        sorted_inserts = defaultdict(list)
        for table_name, stmt in insert_blocks:
            sorted_inserts[table_name].append(stmt)

        insert_text.delete("1.0", tk.END)

        try:
            table_order = topological_sort_table_names(tables)
        except ValueError as e:
            messagebox.showerror("Dependency Error", str(e))
            return

        for table_name in table_order:
            stmts = sorted_inserts.get(table_name, [])
            if not stmts:
                continue
            insert_text.insert(tk.END, f"-- Inserts for {table_name}\n")
            for stmt in stmts:
                insert_text.insert(tk.END, stmt + "\n")
            insert_text.insert(tk.END, "\n")
            
        update_insert_listbox()

    # Add / Remove / Validate buttons
    tk.Button(control_frame, text="➕ Add Row", width=15, command=generate_insert, bg="#ffffff", fg="#1a1a66", font=default_font).pack(side=tk.LEFT, padx=5)
    tk.Button(control_frame, text="➖ Remove Last", width=15, command=remove_last_insert, bg="#ffffff", fg="#1a1a66", font=default_font).pack(side=tk.LEFT, padx=5)
    tk.Button(control_frame, text="✔ Validate Inputs", width=18, command=validate_inputs, bg="#ffffff", fg="#1a1a66", font=default_font).pack(side=tk.LEFT, padx=5)

    # -------- Insert Text Frame with Scrollbars --------
    text_frame = tk.Frame(win)
    text_frame.pack(fill='both', expand=True, padx=10, pady=5)

    insert_text = tk.Text(text_frame, wrap="none", height=12, bg="#f8f8ff", fg="#1a1a66", insertbackground="#1a1a66", font=default_font)
    v_text_scroll = tk.Scrollbar(text_frame, orient="vertical", command=insert_text.yview)
    h_text_scroll = tk.Scrollbar(text_frame, orient="horizontal", command=insert_text.xview)

    insert_text.config(yscrollcommand=v_text_scroll.set, xscrollcommand=h_text_scroll.set)
    insert_text.pack(side="left", fill='both', expand=True)
    v_text_scroll.pack(side="right", fill="y")
    h_text_scroll.pack(side="bottom", fill="x")

    # -------- Bottom Buttons --------
    bottom_frame = tk.Frame(win, bg="#c8c8ff")
    bottom_frame.pack(fill='x', pady=10, padx=10)
    tk.Button(bottom_frame, text="📄 Import INSERTs", command=load_insert_statements, bg="#ffffff", fg="#1a1a66", font=default_font).pack(side=tk.LEFT, padx=5)
    tk.Button(bottom_frame, text="💾 Save INSERTs", command=save_insert_statements, bg="#ffffff", fg="#1a1a66", font=default_font).pack(side=tk.LEFT, padx=5)
    tk.Button(bottom_frame, text="❌ Clear All", command=clear_all, bg="#ffffff", fg="#990000", font=default_font).pack(side=tk.LEFT, padx=5)
    tk.Button(bottom_frame, text="📋 Copy to Clipboard", command=copy_to_clipboard, bg="#ffffff", fg="#1a1a66", font=default_font).pack(side=tk.RIGHT, padx=5)

def reset_fk_mode():
    global adding_fk, fk_source
    adding_fk = False
    fk_source = None

class Table:
    def __init__(self, x, y, width=160, height=100, name="NewTable"):
        self.base_width = width
        self.base_height = height
        self.x = x
        self.y = y
        self.rect = pygame.Rect(x, y, width, height)
        self.last_click_time = 0
        self.foreign_keys = []
        self.color = TABLE_COLOR
        self.name = name
        self.fields = []
        self.dragging = False

    def draw(self, surface):
        padding_x = 20
        padding_y_top = 10
        line_spacing = 25
        shadow_offset = 5

        # 1. Measure width of table name
        max_width = FONT.size(self.name)[0]

        # 2. Measure width of each field label
        for field in self.fields:
            fname, ftype = field[0], field[1]
            is_pk = field[2] if len(field) > 2 else False
            is_fk = field[3] if len(field) > 3 else False
            fk_target = field[4] if len(field) > 4 else ""

            label = f"{fname} ({ftype})"
            if is_pk:
                label = "🔑 " + label
            if is_fk:
                label += f" → {fk_target}"

            text_width = FONT.size(label)[0]
            max_width = max(max_width, text_width)

        # 3. Calculate total height: name + field lines
        num_fields = len(self.fields)
        total_height = padding_y_top + 20 + num_fields * line_spacing + padding_y_top

        # 4. Update the rect size
        self.rect.width = max_width + padding_x
        self.rect.height = total_height

        # 5. Draw the shadow
        shadow_rect = self.rect.copy()
        shadow_rect.x += shadow_offset
        shadow_rect.y += shadow_offset
        pygame.draw.rect(surface, (200, 200, 200), shadow_rect, border_radius=10)

        # 6. Draw the table box
        pygame.draw.rect(surface, self.color, self.rect, border_radius=10)
        pygame.draw.rect(surface, TABLE_BORDER, self.rect, 2, border_radius=10)

        # 7. Draw the table name
        name_surface = FONT.render(self.name, True, TEXT_COLOR)
        surface.blit(name_surface, (self.rect.x + 10, self.rect.y + padding_y_top))

        # 8. Draw the fields
        for i, field in enumerate(self.fields):
            fname, ftype = field[0], field[1]
            is_pk = field[2] if len(field) > 2 else False
            is_fk = field[3] if len(field) > 3 else False
            fk_target = field[4] if len(field) > 4 else ""

            label = f"{fname} ({ftype})"
            color = TEXT_COLOR
            if is_pk:
                label = "🔑 " + label
                color = (160, 0, 0)
            if is_fk:
                # Detect broken reference
                referenced = any(t.name == fk_target for t in tables)
                if not referenced:
                    color = (200, 0, 0)
                    label += f" → ❌ {fk_target}"
                else:
                    color = (0, 0, 150)
                    label += f" → {fk_target}"

            field_surface = FONT.render(label, True, color)
            surface.blit(field_surface, (self.rect.x + 10, self.rect.y + 35 + i * line_spacing))

    def resolve_overlap(self, all_tables):
        for other in all_tables:
            if other is self:
                continue
            if self.rect.colliderect(other.rect):
                dx = self.rect.centerx - other.rect.centerx
                dy = self.rect.centery - other.rect.centery

                # Avoid zero vector
                if dx == 0 and dy == 0:
                    dx, dy = 1, 1

                distance = max(1, (dx**2 + dy**2) ** 0.5)
                push_x = int(2 * dx / distance)  # adjust 2 for push strength
                push_y = int(2 * dy / distance)

                self.rect.x += push_x
                self.rect.y += push_y

                self.clamp_to_screen(screen.get_width(), screen.get_height())

    def clamp_to_screen(self, screen_width, screen_height):
        self.rect.x = max(0, min(self.rect.x, screen_width - self.rect.width))
        self.rect.y = max(0, min(self.rect.y, screen_height - self.rect.height))

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            if self.rect.collidepoint(event.pos):
                if event.button == 1:
                    now = pygame.time.get_ticks()
                    if now - self.last_click_time < 400:  # Double-click
                        open_edit_window(self)
                    else:
                        if adding_fk:
                            if fk_source and fk_source != self:
                                if self not in fk_source.foreign_keys:
                                    fk_source.foreign_keys.append(self)

                                    # Auto-generate foreign key field in source table
                                    fk_field_name = f"{self.name.lower()}_id"

                                    existing_names = [f[0] for f in fk_source.fields]
                                    # Find actual PK field in the target table
                                    target_pk = next((f[0] for f in self.fields if len(f) > 2 and f[2]), "id")

                                    fk_source.fields.append((
                                        fk_field_name,  # name
                                        "INT",          # type
                                        False,          # is_pk
                                        True,           # is_fk
                                        self.name,      # fk_target table
                                        target_pk       # ✅ Use actual PK name!
                                    ))

                                    if not any(f[2] for f in self.fields if len(f) > 2):
                                        self.fields.insert(0, (
                                            "id", "INT", True, False, None
                                        ))

                            reset_fk_mode()
                        else:
                            self.dragging = True
                            self.offset_x = self.rect.x - event.pos[0]
                            self.offset_y = self.rect.y - event.pos[1]
                            self.color = SELECTED_COLOR
                    self.last_click_time = now

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.dragging = False
            self.color = TABLE_COLOR

        elif event.type == pygame.MOUSEMOTION and self.dragging:
            self.rect.x = event.pos[0] + self.offset_x
            self.rect.y = event.pos[1] + self.offset_y
            self.clamp_to_screen(screen.get_width(), screen.get_height())

def open_query_builder():
    global query_builder_open
    global insert_blocks

    if query_builder_open:
        return

    if not tables:
        return

    query_builder_open = True

    qb = make_window(
        "SQL Query Builder",
        bg="#c8c8ff",
        min_size=(700, 900)  # Minimum size for the query builder window
    )

    def on_close():
        global query_builder_open
        query_builder_open = False
        qb.destroy()

    qb.protocol("WM_DELETE_WINDOW", on_close)

    selected_tables_cache = []

    tk.Label(qb, text="Select Tables to Use:").pack(pady=(10, 0))
    table_listbox = tk.Listbox(qb, selectmode=tk.MULTIPLE, width=40, height=6)
    for t in tables:
        table_listbox.insert(tk.END, t.name)
    table_listbox.pack(pady=5)

    tk.Label(qb, text="Select Fields to Display:").pack(pady=(10, 0))
    field_listbox = tk.Listbox(qb, selectmode=tk.MULTIPLE, width=60, height=10)
    field_listbox.pack(pady=5)

    tk.Label(qb, text="WHERE Clause (optional):").pack(pady=(10, 0))
    where_entry = tk.Entry(qb, width=70)
    where_entry.pack(pady=5)

    output_box = tk.Text(qb, height=12, width=80)
    output_box.pack(pady=10)

    result_box_label = tk.Label(qb, text="Query Result Preview:")
    result_box_label.pack()
    result_box = tk.Text(qb, height=10, width=80)
    result_box.pack(pady=5)

    def update_fields():
        nonlocal selected_tables_cache
        field_listbox.delete(0, tk.END)
        selected_indices = table_listbox.curselection()

        if not selected_indices:
            selected_tables_cache = []
            return

        selected_tables = [tables[i] for i in selected_indices]
        selected_tables_cache = selected_tables

        for t in selected_tables:
            field_listbox.insert(tk.END, f"-- {t.name} fields --")
            for field in t.fields:
                field_listbox.insert(tk.END, f"{t.name}.{field[0]}")

    table_listbox.bind("<ButtonRelease-1>", lambda e: qb.after(50, update_fields))

    # --- Generate SQL Query ---
    def build_query():
        selected_tables = selected_tables_cache
        selected_table_names = [t.name for t in selected_tables]

        # --- Field Selection ---
        selected_field_indices = field_listbox.curselection()
        selected_fields_raw = [field_listbox.get(i) for i in selected_field_indices]

        selected_fields = []
        selected_tables_starred = set()
        for f in selected_fields_raw:
            if f.startswith("--") and f.endswith("fields --"):
                table_name = f[3:-9].strip()
                selected_fields.append(f"{table_name}.*")
                selected_tables_starred.add(table_name)
            elif not f.startswith("--"):
                table_prefix = f.split(".")[0]
                if table_prefix not in selected_tables_starred:
                    selected_fields.append(f)

        where_clause = where_entry.get().strip()

        # --- Validation ---
        if not selected_tables:
            messagebox.showerror("Error", "Select at least one table.")
            return

        if not selected_fields:
            selected_fields = [f"{t.name}.*" for t in selected_tables]

        select_str = ", ".join(selected_fields)
        table_lookup = {t.name: t for t in tables}

        # --- Build Join Graph from FK Metadata ---
        graph = {t.name: set() for t in tables}
        join_edges = []

        for t in tables:
            for field in t.fields:
                if len(field) >= 6 and field[3]:  # Is FK
                    src_table = t.name
                    src_field = field[0]
                    dest_table = field[4]
                    dest_field = field[5]
                    if dest_table in table_lookup:
                        graph[src_table].add(dest_table)
                        graph[dest_table].add(src_table)
                        join_edges.append((src_table, dest_table, src_field, dest_field))

        # --- Determine Base Table by Max FK References ---
        reference_counts = {t.name: 0 for t in selected_tables}
        for src, dest, *_ in join_edges:
            if dest in reference_counts:
                reference_counts[dest] += 1

        base_table = max(reference_counts, key=reference_counts.get) if reference_counts else selected_tables[0].name

        # --- BFS to Trace Join Paths from Base Table ---
        visited = set()
        queue = deque([base_table])
        path_map = {}

        while queue:
            current = queue.popleft()
            visited.add(current)

            for neighbor in graph[current]:
                if neighbor in visited:
                    continue

                for src, dest, src_field, dest_field in join_edges:
                    if src == current and dest == neighbor:
                        path_map[neighbor] = (current, (src, dest, src_field, dest_field))
                        queue.append(neighbor)
                        break
                    elif dest == current and src == neighbor:
                        path_map[neighbor] = (current, (dest, src, dest_field, src_field))
                        queue.append(neighbor)
                        break

        # --- Build JOIN Clauses ---
        used_tables = {base_table}
        join_clauses = []

        for target in selected_table_names:
            if target == base_table:
                continue
            if target not in path_map:
                print(f"[DEBUG] No join path found for {target}")
                continue

            # Walk backward from target to base to build join path
            path = []
            current = target
            while current != base_table:
                parent, join_info = path_map.get(current, (None, None))
                if not parent:
                    break
                path.append((parent, current, join_info))
                current = parent
            path.reverse()

            for parent, child, join_info in path:
                src, dest, src_field, dest_field = join_info
                if child in used_tables:
                    continue
                join_clauses.append(f"JOIN {dest} ON {src}.{src_field} = {dest}.{dest_field}")
                used_tables.add(dest)

        # --- Compose Final SQL ---
        query = f"SELECT {select_str}\nFROM {base_table}"
        if join_clauses:
            query += "\n" + "\n".join(join_clauses)
        if where_clause:
            query += f"\nWHERE {where_clause}"
        query += ";"

        # Display result
        output_box.delete("1.0", tk.END)
        output_box.insert(tk.END, query)

    def run_query():
        global insert_blocks

        result_box.delete("1.0", tk.END)
        query = output_box.get("1.0", tk.END).strip()

        if not query:
            result_box.insert(tk.END, "No query to execute.")
            return

        try:
            conn = sqlite3.connect(":memory:")
            cursor = conn.cursor()

            # Create tables
            for t in tables:
                field_defs = []
                table_constraints = []

                has_composite_pk = hasattr(t, 'composite_primary_keys') and t.composite_primary_keys

                for f in t.fields:
                    name = f[0]
                    dtype = f[1].upper()
                    constraints = []

                    # Only use inline PK if NOT a composite PK
                    if f[2] and not has_composite_pk:
                        constraints.append("PRIMARY KEY")

                    if f[3]:
                        constraints.append(f"REFERENCES {f[4]}({f[5]})")

                    field_defs.append(f"{name} {dtype} {' '.join(constraints)}".strip())

                # Composite PK support
                if has_composite_pk:
                    composite_str = ", ".join(t.composite_primary_keys)
                    table_constraints.append(f"PRIMARY KEY ({composite_str})")

                create_sql = f"CREATE TABLE {t.name} (\n  " + ",\n  ".join(field_defs + table_constraints) + "\n);"
                cursor.execute(create_sql)

            # Insert data
            for table_name, stmt in insert_blocks:
                cursor.execute(stmt)

            # Run query
            cursor.execute(query)
            rows = cursor.fetchall()
            col_names = [desc[0] for desc in cursor.description]

            result_box.insert(tk.END, "\t".join(col_names) + "\n")
            result_box.insert(tk.END, "-" * 60 + "\n")
            for row in rows:
                result_box.insert(tk.END, "\t".join(str(v) for v in row) + "\n")

        except Exception as e:
            result_box.insert(tk.END, f"Error: {e}")
        finally:
            conn.close()

    # Buttons
    button_frame = tk.Frame(qb, bg="#c8c8ff")
    button_frame.pack(pady=10)

    tk.Button(button_frame, text="Generate Query", command=build_query,
            bg="#ffffff", fg="#1a1a66").pack(side=tk.LEFT, padx=5)
    tk.Button(button_frame, text="Run Query", command=run_query,
            bg="#ffffff", fg="#1a1a66").pack(side=tk.LEFT, padx=5)
    tk.Button(button_frame, text="Copy Query",
            command=lambda: qb.clipboard_append(output_box.get("1.0", tk.END)),
            bg="#ffffff", fg="#1a1a66").pack(side=tk.LEFT, padx=5)

# --- Helper: load SQL from file path ---
def load_sql_file_from_path(file_path):
    """Parse a SQL file into a list of Table objects."""
    with open(file_path, 'r') as f:
        sql = f.read()

    parsed_tables = []

    # Find all CREATE TABLE statements
    create_statements = re.findall(r'create table (\w+)\s*\((.*?)\);', sql, re.IGNORECASE | re.DOTALL)

    for idx, (table_name, body) in enumerate(create_statements):
        table = Table(100 + (idx % 5) * 180, 100 + (idx // 5) * 160, name=table_name.upper())
        lines = [line.strip().rstrip(',') for line in body.splitlines() if line.strip()]

        pk_fields = set()
        pending_fks = []  # list of (local_cols[], ref_table, ref_cols[])

        for line in lines:
            lower = line.lower()

            # Table-level PRIMARY KEY
            if lower.startswith("primary key"):
                match = re.search(r'\((.*?)\)', line)
                if match:
                    pk_fields.update(f.strip().upper() for f in match.group(1).split(','))
                continue

            # Table-level FOREIGN KEY
            if lower.startswith("foreign key"):
                fk_match = re.search(
                    r'foreign key\s*\((.*?)\)\s*references\s+(\w+)(?:\s*\((.*?)\))?',
                    line, re.IGNORECASE)
                if fk_match:
                    local_cols = [col.strip().upper() for col in fk_match.group(1).split(',')]
                    ref_table = fk_match.group(2).upper()
                    ref_cols = [col.strip().upper() for col in fk_match.group(3).split(',')] if fk_match.group(3) else local_cols[:]
                    pending_fks.append((local_cols, ref_table, ref_cols))
                continue

            # Inline field definition
            field_match = re.match(r'^(\w+)\s+(\w+(?:\(\d+\))?)(.*)$', line, re.IGNORECASE)
            if field_match:
                fname = field_match.group(1).upper()
                ftype = field_match.group(2).strip()
                constraints = field_match.group(3).strip().lower()

                is_pk = 'primary key' in constraints
                is_fk = 'references' in constraints
                ref_table = None
                ref_col = None

                if is_fk:
                    ref_match = re.search(r'references\s+(\w+)\s*(?:\((\w+)\))?', constraints, re.IGNORECASE)
                    if ref_match:
                        ref_table = ref_match.group(1).upper()
                        ref_col = ref_match.group(2).upper() if ref_match.group(2) else 'ID'

                table.fields.append((fname, ftype, is_pk, is_fk, ref_table, ref_col))

        # Apply table-level primary key flags
        if pk_fields:
            for i, f in enumerate(table.fields):
                if f[0] in pk_fields:
                    table.fields[i] = (f[0], f[1], True, f[3], f[4], f[5])

        # Composite PK
        table.composite_primary_keys = list(pk_fields) if len(pk_fields) > 1 else []

        # Apply table-level foreign keys
        for local_cols, ref_table, ref_cols in pending_fks:
            if len(local_cols) != len(ref_cols):
                print(f"[WARNING] FK length mismatch in table {table.name}")
                continue
            for local_col, ref_col in zip(local_cols, ref_cols):
                for i, f in enumerate(table.fields):
                    if f[0] == local_col:
                        table.fields[i] = (f[0], f[1], f[2], True, ref_table, ref_col)

        parsed_tables.append(table)

    return parsed_tables

def save_schema_and_image():
    # Draw everything first (to ensure it's fully rendered)
    draw_scene()

    # Use tkinter to prompt for file save location
    root = tk.Tk()
    root.withdraw()  # Hide the root window

    # Prompt for base file path
    base_path = filedialog.asksaveasfilename(
        defaultextension=".sql",
        filetypes=[("SQL files", "*.sql"), ("All files", "*.*")],
        title="Save Schema As (base filename)..."
    )
    if not base_path:
        print("Save canceled.")
        return

    # Derive the correct paths
    if base_path.lower().endswith(".sql"):
        sql_path = base_path
        image_path = base_path[:-4] + ".jpg"
    elif base_path.lower().endswith(".jpg"):
        image_path = base_path
        sql_path = base_path[:-4] + ".sql"
    else:
        sql_path = base_path + ".sql"
        image_path = base_path + ".jpg"

    # Save image
    pygame.image.save(screen, image_path)

    # Save SQL
    sql_text = export_to_sql(tables)
    with open(sql_path, "w") as f:
        f.write(sql_text)

    print(f"Schema saved to {sql_path} and image saved to {image_path}")



# Main program variables
tables = []
adding_fk = False
fk_source = None
clock = pygame.time.Clock()
running = True

# Draw the main scene
def draw_scene():
    screen.fill(BG_COLOR)

    # Draw Save button
    mouse_pos = pygame.mouse.get_pos()
    if save_button_rect.collidepoint(mouse_pos):
        pygame.draw.rect(screen, BUTTON_HOVER_COLOR, save_button_rect)
    else:
        pygame.draw.rect(screen, BUTTON_COLOR, save_button_rect)

    # Draw Import
    if import_button_rect.collidepoint(mouse_pos):
        pygame.draw.rect(screen, BUTTON_HOVER_COLOR, import_button_rect)
    else:
        pygame.draw.rect(screen, BUTTON_COLOR, import_button_rect)
    import_text = BUTTON_FONT.render("Import SQL", True, (255, 255, 255))
    screen.blit(import_text, (import_button_rect.x + 12, import_button_rect.y + 7))

    # Draw Info button
    if info_button_rect.collidepoint(mouse_pos):
        pygame.draw.rect(screen, (180, 180, 250), info_button_rect)
    else:
        pygame.draw.rect(screen, (150, 150, 230), info_button_rect)

    # Draw Query button
    if query_button_rect.collidepoint(mouse_pos):
        pygame.draw.rect(screen, BUTTON_HOVER_COLOR, query_button_rect)
    else:
        pygame.draw.rect(screen, BUTTON_COLOR, query_button_rect)

    # Draw Populate button
    if pop_table_button_rect.collidepoint(mouse_pos):
        pygame.draw.rect(screen, BUTTON_HOVER_COLOR, pop_table_button_rect)
    else:
        pygame.draw.rect(screen, BUTTON_COLOR, pop_table_button_rect)

    # Draw Trigger button
    if trigger_button_rect.collidepoint(mouse_pos):
        pygame.draw.rect(screen, BUTTON_HOVER_COLOR, trigger_button_rect)
    else:
        pygame.draw.rect(screen, BUTTON_COLOR, trigger_button_rect)

    # Draw Update Generator button
    if update_generator_button_rect.collidepoint(mouse_pos):
        pygame.draw.rect(screen, BUTTON_HOVER_COLOR, update_generator_button_rect)
    else:
        pygame.draw.rect(screen, BUTTON_COLOR, update_generator_button_rect)

    query_text = BUTTON_FONT.render("Query", True, (255, 255, 255))
    screen.blit(query_text, (query_button_rect.x + 10, query_button_rect.y + 7))

    info_text = BUTTON_FONT.render("i", True, (255, 255, 255))
    screen.blit(info_text, (info_button_rect.x + 12, info_button_rect.y + 5))

    save_text = BUTTON_FONT.render("Save Tables", True, (255, 255, 255))
    screen.blit(save_text, (save_button_rect.x + 12, save_button_rect.y + 7))

    import_text = BUTTON_FONT.render("Import SQL", True, (255, 255, 255))
    screen.blit(import_text, (import_button_rect.x + 12, import_button_rect.y + 7))

    populate_text = BUTTON_FONT.render("Populate", True, (255, 255, 255))
    screen.blit(populate_text, (pop_table_button_rect.x + 10, pop_table_button_rect.y + 7))

    trigger_text = BUTTON_FONT.render("Triggers", True, (255, 255, 255))
    screen.blit(trigger_text, (trigger_button_rect.x + 10, trigger_button_rect.y + 7))

    update_gen_text = BUTTON_FONT.render("Update Gen", True, (255, 255, 255))
    screen.blit(update_gen_text, (update_generator_button_rect.x + 10, update_generator_button_rect.y + 7))

    # Draw FK lines from fields specifying target table
    for table in tables:
        for field in table.fields:
            if len(field) >= 5 and field[3] and field[4]:
                target_name = field[4]
                for target_table in tables:
                    if target_table.name == target_name:
                        start = table.rect.center
                        end = target_table.rect.center
                        draw_curved_arrow(screen, start, end)

    for table in tables:
        table.draw(screen)

def open_update_generator_window():
    global update_generator_open
    if update_generator_open:
        return
    update_generator_open = True

    win = make_window("Database Update Generator", bg="#c8c8ff")

    def on_close():
        global update_generator_open
        update_generator_open = False
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)

    default_font = ("Consolas", 11)
    label_font = ("Consolas", 10, "bold")

    top_frame = tk.Frame(win, bg="#c8c8ff")
    top_frame.pack(fill='x', pady=10, padx=10)

    # --- File Variables ---
    old_file_var = tk.StringVar()
    new_file_var = tk.StringVar()
    old_inserts_var = tk.StringVar()
    new_inserts_var = tk.StringVar()
    old_triggers_var = tk.StringVar()
    new_triggers_var = tk.StringVar()

    # Helper function to extract filename from path
    def get_filename(path):
        return path.split('/')[-1].split('\\')[-1]

    # --- Schema Files ---
    tk.Label(top_frame, text="Old SQL File:", bg="#c8c8ff", font=label_font).grid(row=0, column=0, sticky="w")
    tk.Entry(top_frame, textvariable=old_file_var, width=40, font=default_font, state='readonly').grid(row=0, column=1, padx=5)
    old_file_btn = tk.Button(top_frame, text="Select", 
                            command=lambda: old_file_var.set(filedialog.askopenfilename(filetypes=[("SQL files", "*.sql")])) )
    old_file_btn.grid(row=0, column=2, padx=5)
    old_file_label = tk.Label(top_frame, text="", bg="#c8c8ff", font=default_font)
    old_file_label.grid(row=0, column=3, sticky="w", padx=5)

    tk.Label(top_frame, text="New SQL File:", bg="#c8c8ff", font=label_font).grid(row=1, column=0, sticky="w", pady=5)
    tk.Entry(top_frame, textvariable=new_file_var, width=40, font=default_font, state='readonly').grid(row=1, column=1, padx=5)
    new_file_btn = tk.Button(top_frame, text="Select", 
                            command=lambda: new_file_var.set(filedialog.askopenfilename(filetypes=[("SQL files", "*.sql")])) )
    new_file_btn.grid(row=1, column=2, padx=5)
    new_file_btn.config(state='disabled')
    new_file_label = tk.Label(top_frame, text="", bg="#c8c8ff", font=default_font)
    new_file_label.grid(row=1, column=3, sticky="w", padx=5)

    # --- Insert Files ---
    tk.Label(top_frame, text="Old Inserts File:", bg="#c8c8ff", font=label_font).grid(row=2, column=0, sticky="w")
    tk.Entry(top_frame, textvariable=old_inserts_var, width=40, font=default_font, state='readonly').grid(row=2, column=1, padx=5)
    old_inserts_btn = tk.Button(top_frame, text="Select", 
                                command=lambda: old_inserts_var.set(filedialog.askopenfilename(filetypes=[("SQL files", "*.sql")])) )
    old_inserts_btn.grid(row=2, column=2, padx=5)
    old_inserts_label = tk.Label(top_frame, text="", bg="#c8c8ff", font=default_font)
    old_inserts_label.grid(row=2, column=3, sticky="w", padx=5)

    tk.Label(top_frame, text="New Inserts File:", bg="#c8c8ff", font=label_font).grid(row=3, column=0, sticky="w", pady=5)
    tk.Entry(top_frame, textvariable=new_inserts_var, width=40, font=default_font, state='readonly').grid(row=3, column=1, padx=5)
    new_inserts_btn = tk.Button(top_frame, text="Select", 
                                command=lambda: new_inserts_var.set(filedialog.askopenfilename(filetypes=[("SQL files", "*.sql")])) )
    new_inserts_btn.grid(row=3, column=2, padx=5)
    new_inserts_btn.config(state='disabled')
    new_inserts_label = tk.Label(top_frame, text="", bg="#c8c8ff", font=default_font)
    new_inserts_label.grid(row=3, column=3, sticky="w", padx=5)

    # --- Trigger Files ---
    tk.Label(top_frame, text="Old Triggers File:", bg="#c8c8ff", font=label_font).grid(row=4, column=0, sticky="w", pady=5)
    tk.Entry(top_frame, textvariable=old_triggers_var, width=40, font=default_font, state='readonly').grid(row=4, column=1, padx=5)
    old_triggers_btn = tk.Button(top_frame, text="Select", 
                                command=lambda: old_triggers_var.set(filedialog.askopenfilename(filetypes=[("SQL files", "*.sql")])) )
    old_triggers_btn.grid(row=4, column=2, padx=5)
    old_triggers_label = tk.Label(top_frame, text="", bg="#c8c8ff", font=default_font)
    old_triggers_label.grid(row=4, column=3, sticky="w", padx=5)

    tk.Label(top_frame, text="New Triggers File:", bg="#c8c8ff", font=label_font).grid(row=5, column=0, sticky="w")
    tk.Entry(top_frame, textvariable=new_triggers_var, width=40, font=default_font, state='readonly').grid(row=5, column=1, padx=5)
    new_triggers_btn = tk.Button(top_frame, text="Select", 
                                command=lambda: new_triggers_var.set(filedialog.askopenfilename(filetypes=[("SQL files", "*.sql")])) )
    new_triggers_btn.grid(row=5, column=2, padx=5)
    new_triggers_btn.config(state='disabled')
    new_triggers_label = tk.Label(top_frame, text="", bg="#c8c8ff", font=default_font)
    new_triggers_label.grid(row=5, column=3, sticky="w", padx=5)

    # --- Trace Updates ---
    old_file_var.trace_add("write", lambda *_: old_file_label.config(text=get_filename(old_file_var.get())) or new_file_btn.config(state='normal'))
    new_file_var.trace_add("write", lambda *_: new_file_label.config(text=get_filename(new_file_var.get())))
    old_inserts_var.trace_add("write", lambda *_: old_inserts_label.config(text=get_filename(old_inserts_var.get())) or new_inserts_btn.config(state='normal'))
    new_inserts_var.trace_add("write", lambda *_: new_inserts_label.config(text=get_filename(new_inserts_var.get())))
    old_triggers_var.trace_add("write", lambda *_: old_triggers_label.config(text=get_filename(old_triggers_var.get())) or new_triggers_btn.config(state='normal'))
    new_triggers_var.trace_add("write", lambda *_: new_triggers_label.config(text=get_filename(new_triggers_var.get())))

    # --- Update Commands Display ---
    commands_frame = tk.LabelFrame(win, text="Auto-Generated SQL Updates", padx=10, pady=10, bg="#c8c8ff", fg="#1a1a66", font=label_font)
    commands_frame.pack(fill='both', expand=True, padx=10, pady=5)

    commands_text = tk.Text(commands_frame, wrap="none", bg="#f8f8ff", font=default_font)
    commands_text.pack(fill='both', expand=True)

    # --- Button Frame ---
    btn_frame = tk.Frame(win, bg="#c8c8ff")
    btn_frame.pack(fill='x', pady=5, padx=10)

    # --- Helper Functions ---
    def parse_inserts(file_path):
        inserts = {}
        if not file_path:
            return inserts
        with open(file_path, 'r') as f:
            sql = f.read()
        statements = re.findall(r'insert into (\w+)\s*\((.*?)\)\s*values\s*\((.*?)\);', sql, re.IGNORECASE | re.DOTALL)
        for tbl, cols, vals in statements:
            tbl = tbl.upper()
            cols = [c.strip().upper() for c in cols.split(',')]
            vals = [v.strip() for v in re.split(r",(?![^\(]*\))", vals)]
            row = dict(zip(cols, vals))
            inserts.setdefault(tbl, []).append(row)
        return inserts

    def parse_triggers(file_path):
        triggers = []
        if not file_path:
            return triggers
        with open(file_path, 'r') as f:
            sql = f.read()
        parts = re.split(r'CREATE TRIGGER', sql, flags=re.IGNORECASE)
        for part in parts[1:]:
            header = re.search(r'(\w+)\s+(AFTER|BEFORE)\s+(INSERT|UPDATE|DELETE)\s+ON\s+(\w+)', part, re.IGNORECASE)
            if not header:
                continue
            name, timing, event, table = header.groups()
            body = part[header.end():].strip().rstrip(';')

            # Remove outer BEGIN/END if present
            body_clean = re.sub(r'^\s*BEGIN\s*', '', body, flags=re.IGNORECASE)
            body_clean = re.sub(r'\s*END\s*;?\s*$', '', body_clean, flags=re.IGNORECASE)

            triggers.append(type('Trigger', (), {
                'name': name.strip(),
                'timing': timing.upper(),
                'event': event.upper(),
                'table': table.upper(),
                'sql': f"CREATE TRIGGER {name} {timing} {event} ON {table} FOR EACH ROW\nBEGIN\n{body_clean}\nEND;"
            })())

        return triggers

    # --- Generate Updates ---
    def generate_updates():
        # Check missing files properly
        if (bool(old_file_var.get()) ^ bool(new_file_var.get())) \
            or (bool(old_inserts_var.get()) ^ bool(new_inserts_var.get())) \
            or (bool(old_triggers_var.get()) ^ bool(new_triggers_var.get())):
            messagebox.showwarning("Missing Files", "Please select BOTH old and new files for each section.")
            return

        try:
            old_tables = {t.name: t for t in load_sql_file_from_path(old_file_var.get())} if old_file_var.get() else {}
            new_tables = {t.name: t for t in load_sql_file_from_path(new_file_var.get())} if new_file_var.get() else {}
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load SQL files:\n{e}")
            return

        old_inserts = parse_inserts(old_inserts_var.get())
        new_inserts = parse_inserts(new_inserts_var.get())
        old_triggers = parse_triggers(old_triggers_var.get())
        new_triggers = parse_triggers(new_triggers_var.get())

        commands = []
        table_cmds = []

        # --- Deleted Tables ---
        for tname in old_tables.keys():
            if tname not in new_tables:
                table_cmds.append(f"-- Table {tname} was dropped")
                table_cmds.append(f"DROP TABLE {tname};")

        # --- TABLE CHANGES ---
        for tname, tnew in new_tables.items():
            told = old_tables.get(tname)
            if not told:
                table_cmds.append(f"-- Table {tname} is new, CREATE TABLE needed")
                table_cmds.append(f"CREATE TABLE {tname} (...);")
                continue

            old_field_names = {f[0]: f for f in told.fields}
            new_field_names = {f[0]: f for f in tnew.fields}

            for fname, f in new_field_names.items():
                if fname not in old_field_names:
                    table_cmds.append(f"ALTER TABLE {tname} ADD COLUMN {f[0]} {f[1]};")
                elif f[1] != old_field_names[fname][1]:
                    table_cmds.append(f"ALTER TABLE {tname} MODIFY COLUMN {f[0]} {f[1]};")

        if table_cmds:
            commands.append("-- =========================")
            commands.append("-- Table Schema Changes")
            commands.append("-- =========================")
            commands.extend(sorted(table_cmds))
            commands.append("")

        # --- DATA (INSERTS & UPDATES) ---
        data_cmds = []
        for tname, new_rows in new_inserts.items():
            old_rows = old_inserts.get(tname, [])

            if tname in new_tables:  # strict mode
                pk_fields = [f[0] for f in new_tables[tname].fields if f[2]]
            else:
                pk_fields = []

            for new_row in new_rows:
                matched = False
                for old_row in old_rows:
                    if pk_fields and all(old_row.get(pk) == new_row.get(pk) for pk in pk_fields):
                        matched = True
                        for col, val in new_row.items():
                            if col not in pk_fields and old_row.get(col) != val:
                                data_cmds.append(
                                    f"UPDATE {tname} SET {col}={val} WHERE " +
                                    " AND ".join(f"{pk}={new_row[pk]}" for pk in pk_fields) + ";"
                                )
                        break
                    elif not pk_fields and old_row == new_row:
                        matched = True
                        break
                if not matched:
                    cols = ", ".join(new_row.keys())
                    vals = ", ".join(new_row.values())
                    data_cmds.append(f"INSERT INTO {tname} ({cols}) VALUES ({vals});")

        # --- Append data commands to main commands list ---
        if data_cmds:
            commands.append("-- =========================")
            commands.append("-- Data Changes (INSERTs/UPDATEs)")
            commands.append("-- =========================")
            commands.extend(data_cmds)
            commands.append("")

        # --- TRIGGER CHANGES ---
        trig_cmds = []
        for new_trig in new_triggers:
            old_trig = next((t for t in old_triggers if t.name == new_trig.name), None)
            if not old_trig:
                trig_cmds.append(f"-- New trigger: {new_trig.name} on {new_trig.table}")
                trig_cmds.append(new_trig.sql)
            else:
                if old_trig.sql.strip() != new_trig.sql.strip():
                    trig_cmds.append(f"-- Update trigger: {new_trig.name} on {new_trig.table}")
                    trig_cmds.append(new_trig.sql)

        if trig_cmds:
            commands.append("-- =========================")
            commands.append("-- Trigger Changes")
            commands.append("-- =========================")
            commands.extend(trig_cmds)
            commands.append("")

        # --- Output to text box ---
        commands_text.delete("1.0", tk.END)
        commands_text.insert(tk.END, "\n".join(commands))

    def copy_to_clipboard():
        text = commands_text.get("1.0", tk.END).strip()
        if text:
            win.clipboard_clear()
            win.clipboard_append(text)
            messagebox.showinfo("Copied", "SQL commands copied to clipboard.")

    tk.Button(btn_frame, text="Generate Updates", command=generate_updates, bg="#ffffff", fg="#1a1a66", font=default_font).pack(side=tk.LEFT, padx=5)
    tk.Button(btn_frame, text="📋 Copy SQL", command=copy_to_clipboard, bg="#ffffff", fg="#1a1a66", font=default_font).pack(side=tk.LEFT, padx=5)

tk_root = tk.Tk()
tk_root.withdraw()

query_builder_open = False
populate_window_open = False
trigger_window_open = False
update_generator_open = False

# Main loop
while running:
    update_ui_layout()

    for table in tables:
        table.resolve_overlap(tables)

    draw_scene()

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1 and save_button_rect.collidepoint(event.pos):
                save_schema_and_image()

            elif event.button == 1 and info_button_rect.collidepoint(event.pos):
                # Display help using tkinter
                messagebox.showinfo(
                    "How to Use BYoDB",
                    "🧱 Table Interaction:\n"
                    "- Right-click to create a new table\n"
                    "- Left-click and drag to move a table\n"
                    "- Double-click to open the table editor\n\n"
                    "🔗 Foreign Keys:\n"
                    "- Press 'C', then click another table to create a foreign key"
                )

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    if query_button_rect.collidepoint(event.pos):
                        open_query_builder()
                    elif save_button_rect.collidepoint(event.pos):
                        save_schema_and_image()
                    elif import_button_rect.collidepoint(event.pos):
                        import_sql()
                    elif pop_table_button_rect.collidepoint(event.pos):
                        open_populate_window()
                    elif trigger_button_rect.collidepoint(event.pos):
                        open_trigger_window()
                    elif update_generator_button_rect.collidepoint(event.pos):
                        open_update_generator_window()

                elif event.button == 3:
                    mx, my = event.pos
                    clicked_on_table = False
                    for table in tables:
                        if table.rect.collidepoint((mx, my)):
                            clicked_on_table = True
                            break
                    if not clicked_on_table:
                        tables.append(Table(mx, my, name=f"Table{len(tables)+1}"))

        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_c:
                mx, my = pygame.mouse.get_pos()
                for table in tables:
                    if table.rect.collidepoint((mx, my)):
                        adding_fk = True
                        fk_source = table
                        break

        elif event.type == pygame.VIDEORESIZE:
            screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
            for table in tables:
                table.clamp_to_screen(event.w, event.h)

        '''
        elif event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            
            for table in tables:
                if table.rect.collidepoint(mx, my):
                    old_scale = table.scale
                    
                    # Decide zoom factor
                    zoom_amount = 0.1
                    if event.y > 0:
                        table.scale *= 1 + zoom_amount
                    elif event.y < 0:
                        table.scale *= 1 - zoom_amount

                    # Clamp the scale so it doesn't get too tiny or huge
                    table.scale = max(0.2, min(3.0, table.scale))

                    # Calculate offset so zoom is centered on mouse pointer
                    scale_ratio = table.scale / old_scale
                    table.x = mx - (mx - table.x) * scale_ratio
                    table.y = my - (my - table.y) * scale_ratio
                    
                    # Update rect after position change
                    table.rect.topleft = (table.x, table.y)
                    table.rect.width = int(table.base_width * table.scale)
                    table.rect.height = int(table.base_height * table.scale)
        '''

        for table in tables:
            table.handle_event(event)

    # ✅ Process pending Tkinter events
    try:
        tk_root.update()
    except tk.TclError:
        # This happens when all Tkinter windows are closed
        pass

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
sys.exit()
