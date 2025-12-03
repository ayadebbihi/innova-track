from flask import Flask, render_template, request, redirect, session, url_for, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "secret123"

DB_PATH = "database.db"

def get_db():
    """Return a new sqlite connection with foreign_keys enabled and Row factory."""
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def table_has_column(table_name: str, column_name: str) -> bool:
    """Check if a table has a given column."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table_name})")
        cols = [row["name"] for row in cur.fetchall()]
        return column_name in cols
    finally:
        conn.close()
# --- ensure star_ratings table exists (safe migration) ---
def ensure_star_ratings_table():
    conn = get_db()
    c = conn.cursor()
    # ينشئ الجدول فقط لو لم يكن موجودًا
    c.execute("""
    CREATE TABLE IF NOT EXISTS star_ratings (
        rating_id INTEGER PRIMARY KEY AUTOINCREMENT,
        idea_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5),
        UNIQUE(idea_id, user_id),
        FOREIGN KEY (idea_id) REFERENCES ideas(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );
    """)
    conn.commit()
    conn.close()

# نفّذ التأكد عند بدء التطبيق
ensure_star_ratings_table()
import re

def password_strong(passwd):
    if len(passwd) < 6:
        return "Password must be at least 6 characters."
    if not re.search("[A-Z]", passwd):
        return "Password must include at least one uppercase letter."
    if not re.search("[0-9]", passwd):
        return "Password must include at least one number."
    if not re.search("[^A-Za-z0-9]", passwd):
        return "Password must include at least one symbol (e.g. !@#$%)."
    return None

# ---------------- REGISTER ----------------
@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":
        username = request.form["username"].strip()
        email = request.form["email"].strip().lower()
        raw_password = request.form["password"]

        # -------- password validation --------
        import re
        def password_strong(p):
            if len(p) < 6:
                return "Password must be at least 6 characters."
            if not re.search("[A-Z]", p):
                return "Password must include at least one uppercase letter."
            if not re.search("[0-9]", p):
                return "Password must include at least one number."
            if not re.search("[^A-Za-z0-9]", p):
                return "Password must include at least one symbol."
            return None

        weak_msg = password_strong(raw_password)

        # ❌ Weak password → show message in same register page
        if weak_msg:
            return render_template(
                "register.html",
                weak_msg=weak_msg,
                username=username,
                email=email
            )

        # Password OK → hash it
        password_hash = generate_password_hash(raw_password)

        # Check email exists
        conn = get_db()
        c = conn.cursor()

        c.execute("SELECT * FROM users WHERE email = ?", (email,))
        if c.fetchone():
            conn.close()
            return render_template(
                "register.html",
                error="This email is already registered.",
                username=username,
                email=email
            )

        # Insert new user
        c.execute("""
            INSERT INTO users (username, email, password_hash, role)
            VALUES (?, ?, ?, ?)
        """, (username, email, password_hash, "submitter"))

        conn.commit()
        conn.close()
        return redirect("/login")

    # GET
    return render_template("register.html")


@app.route("/admin")
def admin_panel():
    if session.get("role") != "admin":
        return "Access denied"

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id, username, email, role FROM users")
    users = c.fetchall()
    conn.close()

    return render_template("admin_users.html", users=users)


@app.route("/change_role/<int:user_id>", methods=["POST"])
def change_role(user_id):
    if session.get("role") != "admin":
        return "Access denied"

    new_role = request.form.get("new_role")

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET role=? WHERE user_id=?", (new_role, user_id))
    conn.commit()
    conn.close()

    # إذا غيرنا دور المستخدم الحالي، نحدث الـ session أيضاً
    if user_id == session.get("user_id"):
        session["role"] = new_role

    return redirect("/admin")

@app.route("/auth")
def auth_home():
    return render_template("auth_home.html")

# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT user_id, password_hash, role FROM users WHERE email=?", (email,))
        user = c.fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["user_id"]
            session["role"] = user["role"]   
            return redirect("/ideas")

        return "Invalid email or password!"

    return render_template("login.html")

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ---------------- حفظ نموذج الـ Submit مؤقتًا ثم الانتقال لإضافة كاتيجوري (Submitter) ----------------
@app.route("/remember_form_before_category", methods=["POST"])
def remember_form_before_category():
    # يحفظ الحقول في session ثم يذهب إلى واجهة إضافة كاتيجوري الخاصة بالـ submitter
    session["temp_title"] = request.form.get("title", "")
    session["temp_description"] = request.form.get("description", "")
    # حفظ اختيار الكاتيجوري إن كان موجودًا (قد يكون فارغا)
    session["temp_category"] = request.form.get("category_id", "")
    return redirect(url_for("submit_add_category"))


# ---------------- إضافة كاتيجوري من طرف Submitter (لا تمنع Admin من نفس المسار) ----------------
@app.route("/submit_add_category", methods=["GET", "POST"])
def submit_add_category():
    # يجب أن يكون المستخدم مسجّل دخول
    if "user_id" not in session:
        return redirect("/login")

    # منطق: الـ submitter (أو admin) يمكنه إضافة كاتيجوري هنا لكن هذه الصفحة مخصّصة للعودة إلى /submit
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            return "<h3 style='color:red;'>Name required</h3><a href='{}'>Back</a>".format(url_for("submit_add_category"))
        conn = get_db()
        c = conn.cursor()
        try:
            c.execute("INSERT INTO categories (name) VALUES (?)", (name,))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return "<h3 style='color:red;'>Category already exists!</h3><a href='{}'>Back</a>".format(url_for("submit_add_category"))
        conn.close()
        # بعد الإضافة نعيد المستخدم إلى صفحة الإرسال (submit) — ونبقي القيم المحفوظة في session لتظهر في الفورم
        return redirect(url_for("submit_idea"))
    # GET -> عرض النموذج لإضافة كاتيجوري
    # يمكنك إعادة استخدام قالب add_category.html بنفس الشكل
    return render_template("add_category.html", origin="submit")



# ---------------- ADD CATEGORY ----------------
@app.route("/add_category", methods=["GET", "POST"])
def add_category():
    role = session.get("role")

    # فقط امنع الـ reviewer
    if role not in ("admin", "submitter"):
        return "Access Denied"

    if request.method == "POST":
        name = request.form["name"].strip()
        if not name:
            return "<h3 style='color:red;'>Name required</h3><a href='/add_category'>Back</a>"

        conn = get_db()
        c = conn.cursor()
        try:
            c.execute("INSERT INTO categories (name) VALUES (?)", (name,))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return "<h3 style='color:red;'>Category already exists!</h3><a href='/add_category'>Back</a>"

        conn.close()

        # إذا كانت العودة بسبب SUBMIT IDEA → ارجع له هناك
        go_back = session.pop("return_to_submit", None)
        if go_back:
            return redirect("/submit")

        
        return redirect("/submit")

    return render_template("add_category.html")


# ---------------- MANAGE CATEGORIES ----------------
@app.route("/manage_categories")
def manage_categories():
    if "role" not in session or session["role"] != "admin":
        return "<h3 style='color:red;'>Access denied – Admins only</h3><a href='/ideas'>Back</a>"

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT category_id, name FROM categories ORDER BY name")
    categories = c.fetchall()
    conn.close()

    return render_template("manage_categories.html", categories=categories)

# ---------------- EDIT CATEGORY ----------------
@app.route("/edit_category/<int:category_id>", methods=["GET", "POST"])
def edit_category(category_id):
    if session.get("role") != "admin":
     return "Access Denied"

    conn = get_db()
    c = conn.cursor()
    if request.method == "POST":
        newname = request.form["name"].strip()
        try:
            c.execute("UPDATE categories SET name = ? WHERE category_id = ?", (newname, category_id))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return "<h3 style='color:red;'>Category name already exists!</h3><a href='/manage_categories'>Back</a>"
        conn.close()
        return redirect("/manage_categories")
    c.execute("SELECT category_id, name FROM categories WHERE category_id = ?", (category_id,))
    cat = c.fetchone()
    conn.close()
    if not cat:
        return "Category not found!"
    return render_template("edit_category.html", category=cat)
def get_all_categories():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT category_id, name FROM categories ORDER BY name ASC")
    rows = c.fetchall()
    conn.close()
    return rows

# ---------------- DELETE CATEGORY ----------------
@app.route("/delete_category/<int:category_id>", methods=["POST"])
def delete_category(category_id):
    if session.get("role") != "admin":
        return "Access Denied"

    conn = get_db()
    c = conn.cursor()

    try:
        c.execute("DELETE FROM categories WHERE category_id=?", (category_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return render_template(
            "manage_categories.html",
            categories=get_all_categories(),
            error="⚠️ This category is used by an idea and cannot be deleted."
        )

    conn.close()
    return redirect("/manage_categories")

# ---------------- SUBMIT IDEA ----------------
@app.route("/submit", methods=["GET", "POST"])
def submit_idea():
    if "user_id" not in session:
        return redirect("/login")

    if session.get("role") == "reviewer":
        return "<h3 style='color:red;'>Reviewers cannot submit ideas.</h3><a href='/ideas'>Back</a>"

    conn = get_db()
    c = conn.cursor()

    # جلب كل التصنيفات
    c.execute("SELECT category_id, name FROM categories ORDER BY name")
    categories = c.fetchall()

    # استرجاع البيانات المحفوظة في السشن (في حال رجع من Add Category)
    saved_title = session.get("temp_title", "")
    saved_desc = session.get("temp_description", "")
    saved_cat = session.get("temp_category", "")

    if request.method == "POST":
        title = request.form["title"].strip()
        description = request.form["description"].strip()
        category_id = request.form.get("category_id")
        user_id = session["user_id"]

        # 🔴 1 — التحقق هل يوجد عنوان فكرة مشابه سابقاً؟
        c.execute("SELECT id FROM ideas WHERE LOWER(title) = LOWER(?)", (title,))
        existing = c.fetchone()
        if existing:
            conn.close()
            return render_template("submit_idea.html",
                       categories=categories,
                       error="This idea already exists!")


        # إذا لم توجد → أضف الفكرة
        c.execute("""
            INSERT INTO ideas (title, description, category_id, submitter_id, submission_date)
            VALUES (?, ?, ?, ?, datetime('now'))
        """, (title, description, category_id, user_id))

        conn.commit()
        conn.close()

        # احذف قيم السشن بعد الإدخال الناجح فقط
        session.pop("temp_title", None)
        session.pop("temp_description", None)
        session.pop("temp_category", None)

        return redirect("/ideas")

    conn.close()
    return render_template("submit_idea.html",
                           categories=categories,
                           saved_title=saved_title,
                           saved_desc=saved_desc,
                           saved_cat=saved_cat)

# ---------------- LIST IDEAS ----------------
@app.route("/ideas")
def ideas():
    search = request.args.get("search", "").strip()

    conn = get_db()
    c = conn.cursor()

    if search:
        c.execute("""
            SELECT ideas.id, ideas.title, ideas.description, 
       categories.name AS category,
       ideas.submission_date, 
       ideas.submitter_id,
       users.username AS submitter_name
       FROM ideas
            LEFT JOIN categories ON ideas.category_id = categories.category_id
            LEFT JOIN users ON ideas.submitter_id = users.user_id
            WHERE ideas.id = ?
        """, (f"%{search}%", f"%{search}%"))
    else:
        c.execute("""
            SELECT ideas.id, ideas.title, categories.name AS category, ideas.submission_date
            FROM ideas
            LEFT JOIN categories ON ideas.category_id = categories.category_id
        """)

    idea_rows = c.fetchall()
    ideas_with_extra = []

    for idea in idea_rows:
        idea_id = idea["id"]

        # ⭐ Average stars
        c.execute("SELECT AVG(stars) FROM star_ratings WHERE idea_id = ?", (idea_id,))
        avg_stars = c.fetchone()[0] or 0

        # 🔼 Score
        c.execute("SELECT COALESCE(SUM(vote_value),0) FROM votes WHERE idea_id = ?", (idea_id,))
        score = c.fetchone()[0]

        ideas_with_extra.append({
            "id": idea["id"],
            "title": idea["title"],
            "category": idea["category"],
            "stars": round(avg_stars, 1),
            "score": score,
            "date": idea["submission_date"],
        })

    conn.close()

    sorted_ideas = sorted(
        ideas_with_extra,
        key=lambda x: (-x["stars"], -x["score"], x["date"]),
    )

    return render_template("ideas.html", ideas=sorted_ideas)

# ---------------- VIEW IDEA ----------------
from datetime import datetime, timedelta

@app.route("/ideas/<int:id>")
def view_idea(id):
    conn = get_db()
    c = conn.cursor()

    # ──────────────────────────────
    # جلب الفكرة
    # ──────────────────────────────
    c.execute("""
        SELECT ideas.id, ideas.title, ideas.description, ideas.submission_date,
               categories.name AS category, ideas.submitter_id,users.username AS submitter_username
        FROM ideas
        LEFT JOIN categories ON ideas.category_id = categories.category_id
        LEFT JOIN users ON ideas.submitter_id = users.user_id
        WHERE ideas.id = ?
    """, (id,))
    
    idea = c.fetchone()
    if not idea:
        conn.close()
        return "Idea not found!"

    # ──────────────────────────────
    # تعديل توقيت الفكرة +1 ساعة
    # ──────────────────────────────
    raw_time = idea["submission_date"]
    converted_time = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S") + timedelta(hours=1)
    idea_time = converted_time.strftime("%Y-%m-%d %H:%M:%S")

    # ──────────────────────────────
    # حساب السكور
    # ──────────────────────────────
    c.execute("SELECT COALESCE(SUM(vote_value),0) FROM votes WHERE idea_id=?", (id,))
    score = c.fetchone()[0]

    # ──────────────────────────────
    # حساب النجوم (Average)
    # ──────────────────────────────
    c.execute("SELECT AVG(stars) FROM star_ratings WHERE idea_id=?", (id,))
    avg_row = c.fetchone()
    avg_stars = round(avg_row[0], 1) if avg_row and avg_row[0] else 0

    # ──────────────────────────────
    # نجوم المستخدم (نظهرها فقط للمستخدم)
    # ──────────────────────────────
    user_stars = 0
    if "user_id" in session:
        c.execute("SELECT stars FROM star_ratings WHERE idea_id=? AND user_id=?", (id, session["user_id"]))
        r = c.fetchone()
        if r:
            user_stars = r[0]

    # ──────────────────────────────
    # تحميل التعليقات + تعديل الوقت +1 ساعة
    # ──────────────────────────────
    c.execute("""
        SELECT comments.comment_id, comments.user_id, comments.content, comments.timestamp,
               comments.parent_id, users.username,
               COALESCE((SELECT SUM(vote_value) FROM comment_votes WHERE comment_id = comments.comment_id), 0) AS score
        FROM comments
        LEFT JOIN users ON comments.user_id = users.user_id
        WHERE comments.idea_id = ?
        ORDER BY comments.timestamp ASC
    """, (id,))
    
    comments_raw = c.fetchall()
    comments = []

    for cmt in comments_raw:
        raw_t = cmt["timestamp"]
        fixed_t = datetime.strptime(raw_t, "%Y-%m-%d %H:%M:%S") + timedelta(hours=1)
        final_time = fixed_t.strftime("%Y-%m-%d %H:%M:%S")

        comments.append({
            "comment_id": cmt["comment_id"],
            "user_id": cmt["user_id"],
            "content": cmt["content"],
            "timestamp": final_time,
            "parent_id": cmt["parent_id"],
            "username": cmt["username"],
            "score": cmt["score"]
        })

    conn.close()

    return render_template(
        "view_idea.html",
        idea=idea,
        idea_time=idea_time,           # ← الوقت المصحح
        score=score,
        avg_stars=avg_stars,
        user_stars=user_stars,         # ← عدد النجوم الخاصة بالمستخدم فقط
        comments=comments,
        
    )


# ---------------- EDIT IDEA ----------------
@app.route("/edit/<int:idea_id>", methods=["GET", "POST"])
def edit_idea(idea_id):
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()
    c = conn.cursor()

    # 1) جلب صاحب الفكرة
    c.execute("SELECT submitter_id FROM ideas WHERE id = ?", (idea_id,))
    row = c.fetchone()

    if not row:
        conn.close()
        return "Idea not found!"

    owner_id = row["submitter_id"]
    current_user = session["user_id"]
    role = session.get("role")

    if role != "admin" and owner_id != current_user:
        conn.close()
        return "<h3 style='color:red;'>You can edit ONLY your own ideas.</h3><a href='/ideas'>Back</a>"


    c.execute("SELECT category_id, name FROM categories ORDER BY name")
    cats = c.fetchall()

    if request.method == "POST":
        title = request.form["title"].strip()
        description = request.form["description"].strip()
        category_id = request.form.get("category_id")

        c.execute("""UPDATE ideas 
                     SET title=?, description=?, category_id=? 
                     WHERE id=?""",
                  (title, description, category_id, idea_id))
        conn.commit()
        conn.close()
        return redirect(f"/ideas/{idea_id}")

    # تحميل الفكرة
    c.execute("SELECT id, title, description, category_id FROM ideas WHERE id=?", (idea_id,))
    idea = c.fetchone()
    conn.close()

    return render_template("edit_idea.html", idea=idea, categories=cats)

# ---------------- DELETE IDEA ----------------
@app.route('/delete/<int:idea_id>', methods=["POST", "GET"])
def delete_idea(idea_id):
    if "user_id" not in session:
        return redirect("/login")

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT submitter_id FROM ideas WHERE id = ?", (idea_id,))
    row = c.fetchone()

    if not row:
        conn.close()
        return "Idea not found!"

    owner_id = row["submitter_id"]
    current_user = session["user_id"]
    role = session.get("role")

    # 2) السماح فقط:
    # - للـ admin
    # - أو لصاحب الفكرة
    if role != "admin" and owner_id != current_user:
        conn.close()
        return "<h3 style='color:red;'>You can delete ONLY your own ideas.</h3><a href='/ideas'>Back</a>"

    # 3) حذف الأصوات والتعليقات
    c.execute("DELETE FROM votes WHERE idea_id = ?", (idea_id,))
    c.execute("DELETE FROM comments WHERE idea_id = ?", (idea_id,))

    # 4) حذف الفكرة
    c.execute("DELETE FROM ideas WHERE id = ?", (idea_id,))
    conn.commit()
    conn.close()

    return redirect("/ideas")

# ---------------- VOTE (UP / DOWN) ----------------
@app.route("/vote/<int:idea_id>/<action>")
def vote(idea_id, action):
    if "user_id" not in session:
        return redirect("/login")
    role = session.get("role")

    if role not in ("submitter", "reviewer", "admin"):
     return redirect(f"/ideas/{idea_id}")

    if action not in ("up", "down"):
        return redirect(f"/ideas/{idea_id}")
    user_id = session["user_id"]
    vote_value = 1 if action == "up" else -1
    conn = get_db()
    c = conn.cursor()
    # ensure votes table exists with vote_value column
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='votes'")
    if not c.fetchone():
        conn.close()
        return "<h3>Voting is not set up in the database.</h3><a href='/ideas'>Back</a>"
    # see existing vote
    c.execute("SELECT vote_value FROM votes WHERE idea_id = ? AND user_id = ?", (idea_id, user_id))
    row = c.fetchone()
    if row:
        prev = row["vote_value"]
        if prev == vote_value:
            # same vote -> remove (unvote)
            c.execute("DELETE FROM votes WHERE idea_id = ? AND user_id = ?", (idea_id, user_id))
        else:
            # change vote
            c.execute("UPDATE votes SET vote_value = ? WHERE idea_id = ? AND user_id = ?", (vote_value, idea_id, user_id))
    else:
        # insert vote
        try:
            c.execute("INSERT INTO votes (idea_id, user_id, vote_value) VALUES (?, ?, ?)", (idea_id, user_id, vote_value))
        except sqlite3.IntegrityError:
            # unique constraint violation or other -> try update
            c.execute("UPDATE votes SET vote_value = ? WHERE idea_id = ? AND user_id = ?", (vote_value, idea_id, user_id))
    conn.commit()
    conn.close()
    return redirect(f"/ideas/{idea_id}")

@app.route("/rate/<int:idea_id>/<int:stars>")
def rate(idea_id, stars):
    if "user_id" not in session:
        return redirect("/login")

    if stars < 1 or stars > 5:
        return "<h3 style='color:red;'>Invalid rating value!</h3>"

    user_id = session["user_id"]

    conn = get_db()
    c = conn.cursor()

    # أدخل أو عدّل التقييم
    try:
        c.execute("""
            INSERT INTO star_ratings (idea_id, user_id, stars)
            VALUES (?, ?, ?)
            ON CONFLICT(idea_id, user_id) DO UPDATE SET stars=excluded.stars
        """, (idea_id, user_id, stars))
    except Exception as e:
        print("Rating error:", e)

    conn.commit()
    conn.close()

    return redirect(f"/ideas/{idea_id}")

@app.route("/add_comment/<int:idea_id>", methods=["POST"])
def add_comment(idea_id):
    if "user_id" not in session:
        return redirect("/login")

    content = request.form.get("content", "").strip()
    parent_id = request.form.get("parent_id")  # قد يكون None

    if not content:
        return "Comment cannot be empty"

    conn = get_db()
    c = conn.cursor()

    # تأكد أن idea_id موجود
    c.execute("SELECT id FROM ideas WHERE id=?", (idea_id,))
    if not c.fetchone():
        conn.close()
        return "Idea not found"

    # parent_id يجب أن يشير لتعليق موجود أو NULL
    if parent_id:
        c.execute("SELECT comment_id FROM comments WHERE comment_id=?", (parent_id,))
        if not c.fetchone():
            parent_id = None  # حماية

    # إضافة التعليق
    c.execute("""
        INSERT INTO comments (idea_id, user_id, content, parent_id, timestamp)
        VALUES (?, ?, ?, ?, datetime('now'))
    """, (idea_id, session["user_id"], content, parent_id))
    
    conn.commit()
    conn.close()

    return redirect(f"/ideas/{idea_id}")

@app.route("/delete_comment/<int:comment_id>", methods=["POST"])
def delete_comment(comment_id):
    if "user_id" not in session:
        return "Access denied"

    conn = get_db()
    c = conn.cursor()

    # تأكد أن الكومنت ملك لصاحبه فقط
    c.execute("SELECT user_id, idea_id FROM comments WHERE comment_id=?", (comment_id,))
    row = c.fetchone()

    if not row:
        conn.close()
        return "Comment not found"

    if row["user_id"] != session["user_id"]:
        conn.close()
        return "You can delete only your own comments."

    # حذف الكومنت (والردود عليه إذا موجودة)
    c.execute("DELETE FROM comments WHERE parent_id=?", (comment_id,))
    c.execute("DELETE FROM comments WHERE comment_id=?", (comment_id,))
    conn.commit()
    conn.close()

    return redirect(f"/ideas/{row['idea_id']}")

@app.route("/admin_dashboard")
def admin_dashboard():
    if "user_id" not in session or session.get("role") != "admin":
        return "<h3 style='color:red;'>Access denied — Admins only.</h3>"

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id, username, email, role FROM users")
    users = c.fetchall()
    conn.close()

    return render_template("admin_dashboard.html", users=users)

@app.route("/comment_vote/<int:comment_id>/<action>")
def comment_vote(comment_id, action):
    if "user_id" not in session:
        return redirect("/login")

    user_id = session["user_id"]
    if action not in ("up", "down"):
        return redirect(request.referrer)

    vote_value = 1 if action == "up" else -1

    conn = get_db()
    c = conn.cursor()

    # هل قام المستخدم بالتصويت مسبقاً؟
    c.execute("SELECT vote_value FROM comment_votes WHERE comment_id=? AND user_id=?", 
              (comment_id, user_id))
    row = c.fetchone()

    if row:
        if row["vote_value"] == vote_value:
            # نفس التصويت → إزالة
            c.execute("DELETE FROM comment_votes WHERE comment_id=? AND user_id=?",
                      (comment_id, user_id))
        else:
            # تغيير التصويت
            c.execute("""
                UPDATE comment_votes 
                SET vote_value=? 
                WHERE comment_id=? AND user_id=?
            """, (vote_value, comment_id, user_id))
    else:
        # تصويت جديد
        c.execute("""
            INSERT INTO comment_votes (comment_id, user_id, vote_value)
            VALUES (?, ?, ?)
        """, (comment_id, user_id, vote_value))

    conn.commit()
    conn.close()

    return redirect(request.referrer)

@app.route("/admin/delete_user/<int:user_id>", methods=["POST"])
def delete_user(user_id):
    if session.get("role") != "admin":
        return "Unauthorized!", 403

    conn = get_db()
    c = conn.cursor()

    # لا نحذف الأفكار الخاصة باليوزر
    c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    flash("User deleted successfully.", "success")
    return redirect(url_for("admin_panel"))

# ---------------- Home redirect ----------------
@app.route("/")
def home():
    return render_template("auth_home.html")


# ---------------- Run ----------------
if __name__ == "__main__":
    # ensure DB exists
    if not os.path.exists(DB_PATH):
        print("database.db not found. Please run your init_db.py to create the database, then re-run this app.")
    app.run(debug=True)
