import sqlite3

db = sqlite3.connect("yallago.db")
rows = db.execute(
    "SELECT username, display_name, role, is_active FROM employees WHERE role = 'admin'"
).fetchall()

print(rows)
db.close()
