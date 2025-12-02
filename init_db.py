import sqlite3
import os
from werkzeug.security import generate_password_hash

DB = "database.db"

if os.path.exists(DB):
    os.remove(DB)
    print("Old database removed.")

conn = sqlite3.connect(DB)
c = conn.cursor()

# ---- USERS ----
c.execute("""
CREATE TABLE users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT DEFAULT 'submitter'
);
""")

# ---- CATEGORIES ----
c.execute("""
CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);
""")

# ---- IDEAS ----
c.execute("""
CREATE TABLE ideas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    submitter_id INTEGER,
    submission_date TEXT,
    FOREIGN KEY (category_id) REFERENCES categories(category_id) ON DELETE SET NULL,
    FOREIGN KEY (submitter_id) REFERENCES users(user_id) ON DELETE SET NULL
);
""")

# ---- VOTES ----
c.execute("""
CREATE TABLE votes (
    vote_id INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    vote_value INTEGER NOT NULL,
    UNIQUE(idea_id, user_id),
    FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
""")

# ---- COMMENTS ----
c.execute("""
CREATE TABLE comments (
    comment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id INTEGER NOT NULL,
    user_id INTEGER,
    content TEXT NOT NULL,
    timestamp TEXT,
    parent_id INTEGER,
    FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL,
    FOREIGN KEY (parent_id) REFERENCES comments(comment_id) ON DELETE CASCADE
);
""")
c.execute("""
CREATE TABLE comment_votes (
    vote_id INTEGER PRIMARY KEY AUTOINCREMENT,
    comment_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    vote_value INTEGER NOT NULL CHECK(vote_value IN (1, -1)),
    UNIQUE(comment_id, user_id),
    FOREIGN KEY (comment_id) REFERENCES comments(comment_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
""")

c.execute("""
CREATE TABLE star_ratings (
    rating_id INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5),
    UNIQUE(idea_id, user_id),
    FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
""")
# -------- DEFAULT CATEGORIES --------
default_categories = ["Technology", "Process Improvement", "Customer Experience", "Health"]
for cat in default_categories:
    c.execute("INSERT INTO categories (name) VALUES (?)", (cat,))

# -------- CREATE ADMIN USER --------
admin_email = "ayadebbihi@gmail.com"
admin_username = "Aya"
admin_pass = generate_password_hash("26112002Ad@")   
c.execute("""
    INSERT INTO users (username, email, password_hash, role)
    VALUES (?, ?, ?, 'admin')
""", (admin_username, admin_email, admin_pass))

conn.commit()
conn.close()

print("Database created successfully with admin user!")
