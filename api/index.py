from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, timezone
from pymongo import MongoClient
from flask_socketio import SocketIO
import os
import uuid
import cloudinary
import cloudinary.uploader
import requests
from flask import abort

import logging

logging.basicConfig(level=logging.ERROR)




# ---------------- Base Directory ----------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates")
)

ADMIN_ID = "83a39908-cb47-4589-8c58-46f388f3976d"

cloudinary.config(
    cloud_name="your_cloud_name",
    api_key="your_api_key",
    api_secret="your_api_secret"
)


socketio = SocketIO(
    app,
    cors_allowed_origins="https://smartedu-dbqo.onrender.com/",
    async_mode="eventlet"
)


app.secret_key = os.environ.get("SECRET_KEY", "fallback_secret_key")

# ---------------- MongoDB Setup ----------------
MONGO_URI = "your_mongodb_connection_string"

if not MONGO_URI:
    raise Exception("MONGO_URI is not set. Add it in environment variables.")

client = MongoClient(MONGO_URI)

try:
    client.admin.command('ping')
    print("✅ MongoDB Connected")
except Exception as e:
    print("❌ MongoDB Error:", e)

db = client["SmartEduDB"]

users_col = db["users"]
classes_col = db["classes"]
user_classes_col = db["user_classes"]
comments_col = db["comments"]
poll_responses_col = db["poll_responses"]
user_courses_col = db["user_courses"]
courses_col = db["courses"]
teachers_col = db["teachers"]
reviews_col = db["reviews"]
followers_col = db["followers"]
notes_col = db["notes"]
tests_col= db["tests"]
test_attempts_col = db["test_attempts"]


# ---------------- Required Decorator ----------------

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("LPfront"))
        return f(*args, **kwargs)
    return decorated

def role_required(required_role):
    def decorator(f):
        from functools import wraps
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("LPfront"))
            if session.get("role") != required_role:
                return redirect(url_for("LPfront"))
            return f(*args, **kwargs)
        return decorated
    return decorator

def get_class_datetime(cls):
    return datetime.strptime(
        f"{cls['date']} {cls['time']}",
        "%Y-%m-%d %H:%M"
    )


def get_class_status(cls):
    class_dt = get_class_datetime(cls)
    now = datetime.now()

    diff_minutes = (class_dt - now).total_seconds() / 60

    if diff_minutes > 0:
        return "upcoming"
    elif -60 <= diff_minutes <= 0:
        return "live"
    else:
        return "completed"



# ---------------- Routes ----------------

@app.route("/")
def LPfront():
    # 🔐 Redirect if already logged in
    if "user_id" in session:
        if session.get("role") == "Teacher":
            return redirect(url_for("LPteachershome"))
        elif session.get("role") == "Admin":
            return redirect(url_for("admin_dashboard"))
        else:
            return redirect(url_for("LPstudenthome"))


    try:
        # 📊 COUNTS
        student_count = users_col.count_documents({"role": "Student"})
        teacher_count = users_col.count_documents({"role": "Teacher"})
        course_count = courses_col.count_documents({})

        # 👨‍🏫 TEACHERS (limit optional)
        teachers = list(users_col.find({"role": "Teacher"}))
        # teachers = list(users_col.find({"role": "Teacher"}).limit(3))

        # 📚 COURSES (limit optional)
        courses = list(courses_col.find())
        # courses = list(courses_col.find().limit(4))

        # ⭐ REVIEWS
        reviews = list(reviews_col.find({}))
        if len(reviews) > 0:
            total_rating = sum(int(r.get("rating", 0)) for r in reviews)
            avg_rating = total_rating / len(reviews)
            success_rate = int((avg_rating / 5) * 100)
        else:
            success_rate = 0

    except Exception as e:
        print("Stats Error:", e)
        student_count = teacher_count = course_count = success_rate = 0
        teachers = []
        courses = []

    return render_template(
        "LPfront.html",
        student_count=student_count,
        teacher_count=teacher_count,
        course_count=course_count,
        success_rate=success_rate,
        teachers=teachers,
        courses=courses
    )

@app.route("/LPbookstore") 
def LPbookstore(): 
    return render_template("LPbookstore.html") 

@app.route("/course/<course_id>")
@login_required
def course_page(course_id):

    course = courses_col.find_one({"course_id": course_id})

    classes = list(classes_col.find({
        "course_id": course_id
    }))

    classes = sorted(
        classes,
        key=lambda x: (x.get("date", ""), x.get("time", ""))
    )

    from collections import defaultdict
    grouped_classes = defaultdict(list)

    now = datetime.now()

    for c in classes:
        try:
            class_dt = datetime.strptime(
                f"{c['date']} {c['time']}",
                "%Y-%m-%d %H:%M"
            )

            # 🔥 FLAGS
            c["is_past"] = class_dt < now
            c["is_today"] = class_dt.date() == now.date()
            c["has_link"] = bool(c.get("link"))

        except:
            c["is_past"] = False
            c["is_today"] = False
            c["has_link"] = False

        grouped_classes[c["date"]].append(c)

    return render_template(
        "course_page.html",
        course=course,
        grouped_classes=grouped_classes
    )


@app.route("/teacher/<user_id>")
@login_required
def teacher_page(user_id):

    # =========================
    # 🔍 GET TEACHER PROFILE
    # =========================
    teacher = teachers_col.find_one({"user_id": user_id})

    # 🔥 AUTO CREATE PROFILE IF NOT EXISTS
    if not teacher:
        user = users_col.find_one({"id": user_id})

        if not user or user.get("role") != "Teacher":
            return "Teacher not found", 404

        teacher = {
            "teacher_id": str(uuid.uuid4()),
            "user_id": user_id,
            "fullname": user["fullname"],
            "profile_image": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2c/Default_pfp.svg/500px-Default_pfp.svg.png",
            "headline": "",
            "bio": "",
            "education": "",
            "experience": "",
            "languages": [],
            "specialization": "",
            "category": user.get("category", ""),
            "courses": [],
            "free_classes": [],
            "rating": 0,
            "total_students": 0,
            "created_at": datetime.now()
        }

        teachers_col.insert_one(teacher)

    # 🆔 TEACHER ID
    teacher_id = teacher["teacher_id"]

    # =========================
    # 📚 COURSES
    # =========================
    courses = list(courses_col.find({
        "teacher_id": teacher_id
    }))

    # =========================
    # 🎓 FREE CLASSES (🔥 UPDATED)
    # =========================
    free_classes = list(classes_col.find({
        "teacher_id": teacher_id,
        "is_free": True
    }))

    current_user = session.get("user_id")

    for fc in free_classes:
        try:
            # 🕒 Convert date + time → datetime
            class_time = datetime.strptime(
                f"{fc['date']} {fc['time']}",
                "%Y-%m-%d %H:%M"
            )

            now = datetime.now()

            # ✅ LIVE (1 hour window)
            fc["is_live"] = class_time <= now <= class_time + timedelta(hours=1)

        except:
            fc["is_live"] = False

        # ✅ ENROLLMENT CHECK
        fc["is_enrolled"] = False
        if current_user:
            exists = user_classes_col.find_one({
                "user_id": current_user,
                "class_id": fc["class_id"]
            })
            if exists:
                fc["is_enrolled"] = True

    # =========================
    # ⭐ REVIEWS
    # =========================
    reviews = list(reviews_col.find({
        "teacher_id": teacher_id
    }))

    # 🔝 TOP FEEDBACK
    top_feedback = ""
    if reviews:
        comments = [r.get("comment") for r in reviews if r.get("comment")]
        if comments:
            top_feedback = comments[0]

    # 📊 RATING BREAKDOWN
    rating_counts = {i: 0 for i in range(1, 6)}

    for r in reviews:
        try:
            rating = int(r.get("rating", 0))
            if rating in rating_counts:
                rating_counts[rating] += 1
        except:
            pass

    total_reviews = len(reviews)

    # =========================
    # 👥 FOLLOWERS
    # =========================
    followers = followers_col.count_documents({
        "teacher_id": teacher_id
    })

    is_following = followers_col.find_one({
        "follower_id": session["user_id"],
        "teacher_id": teacher_id
    })

    # =========================
    # 🚀 RENDER TEMPLATE
    # =========================
    return render_template(
        "teacher_page.html",
        teacher=teacher,
        courses=courses,
        free_classes=free_classes,
        reviews=reviews,
        top_feedback=top_feedback,
        rating_counts=rating_counts,
        total_reviews=total_reviews,
        followers=followers,
        is_following=is_following,
        is_owner=(session.get("user_id") == teacher["user_id"])
    )

@app.route("/test/<test_id>")
@login_required
def test_page(test_id):
    test = tests_col.find_one({"test_id": test_id})
    return render_template("test_page.html", test=test)
    
@app.route("/LPteachershome")
@role_required("Teacher")
def LPteachershome():

    user = users_col.find_one({"id": session["user_id"]})

    if not user:
        return redirect(url_for("LPfront"))

    teacher = teachers_col.find_one({"user_id": session["user_id"]})

    if not teacher:
        return "Teacher profile not found", 404

    teacher_id = teacher["teacher_id"]

    # 📚 COURSES
    my_courses = []
    for c in courses_col.find({"teacher_id": teacher_id}):
        c["course_id"] = c.get("course_id", str(c["_id"]))  # safe fallback
        my_courses.append(c)

    # 📅 CLASSES
    my_classes = []
    classes = list(classes_col.find({"teacher_id": teacher_id}))

    now = datetime.now()

    for c in classes:
        try:
            class_dt = get_class_datetime(c)

            if class_dt >= now:
                c["status"] = get_class_status(c)
                c["class_id"] = c.get("class_id", str(c["_id"]))  # safe fallback
                my_classes.append(c)

        except Exception as e:
            print("Class parse error:", e)

    my_classes = sorted(
        my_classes,
        key=lambda x: (x.get("date", ""), x.get("time", ""))
    )

    return render_template(
        "LPteachershome2.html",
        user=user,
        my_courses=my_courses,
        my_classes=my_classes,
        teachers=teacher
    )
    
@app.route("/LPstudenthome")
@role_required("Student")
def LPstudenthome():

    user = users_col.find_one({"id": session["user_id"]})

    # ---------------- USER COURSES ----------------
    user_courses = list(user_courses_col.find({
        "user_id": str(user["id"])
    }))

    user_course_ids = [str(uc["course_id"]) for uc in user_courses]

    # ---------------- ALL COURSES ----------------
    all_courses = list(courses_col.find())

    # ---------------- ENROLLED COURSES ----------------
    enrolled_courses = list(courses_col.find({
        "course_id": {"$in": user_course_ids}
    }))

    # ---------------- USER CLASSES ----------------
    user_classes = list(user_classes_col.find({
        "user_id": str(user["id"])
    }))

    enrolled_class_ids = [str(uc["class_id"]) for uc in user_classes]

    # ---------------- GET ENROLLED CLASSES (exact match) ----------------
    enrolled_classes = list(classes_col.find({
        "class_id": {"$in": enrolled_class_ids}
    }))
    # ---------------- ONLY ENROLLED CLASSES ----------------
    enrolled_set = set(enrolled_class_ids)
    classes = enrolled_classes

    # ---------------- USER TESTS ----------------
    tests = list(tests_col.find({
        "course_id": {"$in": user_course_ids}
    }))

    today_classes = []
    upcoming_classes = []
    today_tests = []

    now = datetime.now()

    # ---------------- TEACHERS ----------------
    teacher_ids = list(set([
        c.get("teacher_id") for c in classes if c.get("teacher_id")
    ]))

    teachers = list(teachers_col.find({
        "teacher_id": {"$in": teacher_ids}
    }))

    teacher_map = {
        t["teacher_id"]: t.get("fullname", "Unknown")
        for t in teachers
    }

    # ---------------- PROCESS CLASSES ----------------
    for c in classes:
        try:
            class_dt = get_class_datetime(c)

            c["status"] = get_class_status(c)
            c["formatted_time"] = class_dt.strftime("%I:%M %p")
            c["time"] = class_dt.strftime("%H:%M")
            c["date"] = class_dt.strftime("%Y-%m-%d")
            c["teacher_name"] = teacher_map.get(c.get("teacher_id"), "Unknown")
            c["type"] = "class"
            c["is_free"] = c.get("is_free", False)

            # ✅ Keep original class_id as string — DO NOT overwrite with wrong value
            c["class_id"] = str(c.get("class_id"))

            # ✅ Mark if user is enrolled
            c["is_enrolled"] = c["class_id"] in enrolled_set

            if class_dt.date() == now.date():
                today_classes.append(c)
            elif class_dt > now:
                upcoming_classes.append(c)

        except Exception as e:
            print("Class parse error:", e)

    # ---------------- PROCESS TESTS ----------------
    for t in tests:

        start_time = t.get("start_time")
        if not start_time:
            continue

        if isinstance(start_time, str):
            try:
                start_time = datetime.strptime(start_time, "%Y-%m-%dT%H:%M")
            except:
                try:
                    start_time = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
                except:
                    continue

        t["formatted_time"] = start_time.strftime("%I:%M %p")
        t["time"] = start_time.strftime("%H:%M")
        t["date"] = start_time.strftime("%Y-%m-%d")
        t["type"] = "test"

        if start_time.date() == now.date():
            today_tests.append(t)

    # ---------------- MERGE TODAY ----------------
    today_all = sorted(
        today_classes + today_tests,
        key=lambda x: x.get("time", "")
    )

    # ---------------- SORT UPCOMING ----------------
    upcoming_classes = sorted(
        upcoming_classes,
        key=lambda x: (x["date"], x["time"])
    )

    # ---------------- FREE CLASSES (for template) ----------------
    free_classes = [c for c in classes if c.get("is_free")]

    return render_template(
        "LPstudenthome.html",
        user=user,
        courses=enrolled_courses,
        all_courses=all_courses,
        today_classes=today_all,
        upcoming_classes=upcoming_classes,
        user_courses_ids=user_course_ids,
        user_courses=user_courses,
        tests=tests,
        free_classes=free_classes
    )
    
@app.route("/LPcourse") 
def LPcourse(): 
    return render_template("LPcourse.html") 
    
@app.route("/LPregisteryourself") 
def LPregisteryourself(): 
    return render_template("LPregisteryourself.html") 
    
@app.route("/LPliveclasses") 
@login_required 
def LPliveclasses(): 
    return render_template("LPliveclasses.html")

# ---------------- REGISTER ----------------
@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "GET":
        return render_template("LPregisteryourself.html")

    try:
        fullname = request.form.get("fullname")
        email = request.form.get("email")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        role = request.form.get("role")
        phone = request.form.get("phone")

        # ✅ Validation
        if not all([fullname, email, password, confirm_password, role, phone]):
            return render_template("LPregisteryourself.html", error="All fields are required")

        if password != confirm_password:
            return render_template("LPregisteryourself.html", error="Passwords do not match")

        existing_user = users_col.find_one({"email": email})
        if existing_user:
            return render_template("LPregisteryourself.html", error="User already exists")

        # ✅ Create user_id first
        user_id = str(uuid.uuid4())

        hashed_password = generate_password_hash(password)

        # ✅ Insert user
        users_col.insert_one({
            "id": user_id,
            "fullname": fullname,
            "email": email,
            "password": hashed_password,
            "role": role,
            "phone": phone,
            "created_at": datetime.now(timezone.utc),
            "subscribed": "no",
            "enrolled_course": "none",
            "subcription_till": "00/00/0000"
        })

        # ✅ If teacher → create public profile
        if role == "Teacher":
            teachers_col.insert_one({
                "teacher_id": str(uuid.uuid4()),
                "user_id": user_id,  # 🔗 link to users table

                "fullname": fullname,
                "profile_image": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2c/Default_pfp.svg/500px-Default_pfp.svg.png?_=20220226140232",

                "headline": "",
                "bio": "",
                "education": "",
                "experience": "",
                "languages": [],

                "specialization": "",
                "category": "",

                "courses": [],
                "free_classes": [],

                "rating": 0,
                "total_students": 0,

                "created_at": datetime.now(timezone.utc)
            })

        return redirect(url_for("LPfront"))

    except Exception as e:
        return render_template("LPregisteryourself.html", error=str(e))

# ---------------- LOGIN ----------------
@app.route("/login", methods=["POST"])
def login():
    try:
        email = request.form.get("email")
        password = request.form.get("password")

        if not email or not password:
            return render_template("LPfront.html", error="Missing email or password")

        user = users_col.find_one({"email": email})

        if not user:
            return render_template("LPfront.html", error="User not found")

        if not check_password_hash(user["password"], password):
            return render_template("LPfront.html", error="Incorrect password")

        session["user_id"] = user["id"]
        session["role"] = user["role"]

        if user["role"] == "Teacher":
            return redirect(url_for("LPteachershome"))
        else:
            return redirect(url_for("LPstudenthome"))

    except Exception as e:
        return render_template("LPfront.html", error=str(e))

# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("LPfront"))

# ------ Create Course ---------
@app.route("/create_course", methods=["POST"])
@role_required("Teacher")
def create_course():
    try:
        # 📥 GET FORM DATA
        name = request.form.get("name")
        desc = request.form.get("desc")
        total_classes = request.form.get("total_classes")
        category = request.form.get("category")
        time = request.form.get("time")
        start_date_str = request.form.get("start_date")

        # ❌ VALIDATION
        if not name or not total_classes or not category or not time or not start_date_str:
            return jsonify({"error": "Missing fields"}), 400

        try:
            total_classes = int(total_classes)
        except:
            return jsonify({"error": "Invalid number of classes"}), 400

        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
        except:
            return jsonify({"error": "Invalid start date"}), 400

        try:
            datetime.strptime(time, "%H:%M")
        except:
            return jsonify({"error": "Invalid time format"}), 400

        # 🔥 GET CORRECT TEACHER_ID
        teacher = teachers_col.find_one({"user_id": session["user_id"]})
        if not teacher:
            return jsonify({"error": "Teacher not found"}), 404

        teacher_id = teacher["teacher_id"]

        # 🆔 GENERATE COURSE ID
        course_id = str(uuid.uuid4())

        # 📚 INSERT COURSE
        courses_col.insert_one({
            "course_id": course_id,
            "name": name,
            "desc": desc,
            "category": category,
            "teacher_id": teacher_id,
            "total_classes": total_classes,
            "start_date": start_date,
            "created_at": datetime.now()
        })

        # 👨‍🏫 UPDATE TEACHER PROFILE
        teachers_col.update_one(
            {"user_id": session["user_id"]},
            {"$push": {"courses": course_id}}
        )

        # 📅 CREATE CLASSES WITH NUMBERING
        current_date = start_date

        for i in range(1, total_classes + 1):

            class_name = f"{name} - Class {i}"  # 🔥 CLASS NUMBERING

            classes_col.insert_one({
                "class_id": str(uuid.uuid4()),
                "course_id": course_id,
                "teacher_id": teacher_id,
                "subject": class_name,        # ✅ UPDATED
                "class_number": i,            # ✅ EXTRA FIELD (useful later)
                "category": category,
                "date": current_date.strftime("%Y-%m-%d"),
                "time": time,
                "status": "upcoming",
                "created_at": datetime.now()
            })

            current_date += timedelta(days=1)

        return jsonify({
            "message": "Course & classes created successfully 🚀",
            "course_id": course_id
        })

    except Exception as e:
        print("CREATE COURSE ERROR:", e)
        return jsonify({"error": "Internal server error"}), 500

# ---- enroll -------
@app.route("/enroll/<course_id>")
@login_required
def enroll(course_id):

    user_id = session["user_id"]

    # 🔒 Prevent duplicate enrollment
    existing = db.user_courses.find_one({
        "user_id": user_id,
        "course_id": course_id
    })

    if existing:
        return redirect(url_for("LPstudenthome"))

    db.user_courses.insert_one({
        "user_id": user_id,
        "course_id": course_id
    })

    # Auto-enroll in classes
    classes = db.classes.find({"course_id": course_id})

    for c in classes:
        db.user_classes.insert_one({
            "user_id": user_id,
            "class_id": c["class_id"]
        })

    return redirect(url_for("LPstudenthome"))


@app.route("/enroll-class/<class_id>", methods=["POST"])
@login_required
def enroll_class(class_id):

    print("🔥 RECEIVED CLASS ID:", class_id)  # DEBUG

    user_id = session["user_id"]

    existing = user_classes_col.find_one({
        "user_id": user_id,
        "class_id": class_id
    })

    if not existing:
        user_classes_col.insert_one({
            "user_id": user_id,
            "class_id": class_id
        })

    return jsonify({"status": "enrolled"})

# ---- TEacher catagory -----

@app.route("/set_teacher_category", methods=["POST"])
@role_required("Teacher")
def set_teacher_category():

    try:
        category = request.form.get("category")
        print("CATEGORY:", category)

        users_col.update_one(
            {"id": session["user_id"]},
            {"$set": {"category": category}}
        )

        return jsonify({"message": "Category saved"})

    except Exception as e:
        print("ERROR:", e)
        return jsonify({"error": str(e)}), 500

#--profile image 

@app.route("/upload-profile-image", methods=["POST"])
@role_required("Teacher")
def upload_profile_image():

    if "image" not in request.files:
        return "No file", 400

    file = request.files["image"]

    if file.filename == "":
        return "No selected file", 400

    teacher = teachers_col.find_one({"user_id": session["user_id"]})

    # 🔥 delete old image
    if teacher and teacher.get("profile_image_id"):
        try:
            cloudinary.uploader.destroy(teacher["profile_image_id"])
        except Exception as e:
            print("Delete failed:", e)

    # 🔥 upload new image
    result = cloudinary.uploader.upload(
        file,
        folder="profile_pics",
        transformation=[
            {"width": 300, "height": 300, "crop": "fill", "gravity": "face"}
        ]
    )

    image_url = result.get("secure_url")
    public_id = result.get("public_id")

    # 🔥 update teacher
    teachers_col.update_one(
        {"user_id": session["user_id"]},
        {
            "$set": {
                "profile_image": image_url,
                "profile_image_id": public_id
            }
        }
    )

    # ✅ update user
    users_col.update_one(
        {"id": session["user_id"]},
        {
            "$set": {
                "profileimg": image_url
            }
        }
    )

    return redirect(url_for("LPteachershome"))


#reviewwww for teachers 

@app.route("/add-review/<teacher_id>", methods=["POST"])
@login_required
def add_review(teacher_id):

    user_id = session["user_id"]
    rating = int(request.form.get("rating"))
    comment = request.form.get("comment")

    teacher = teachers_col.find_one({"teacher_id": teacher_id})

    if not teacher:
        return "Teacher not found", 404

    # ❌ prevent self review
    if teacher["user_id"] == user_id:
        return "You cannot review yourself", 400

    # 🔥 CHECK IF REVIEW EXISTS
    existing = reviews_col.find_one({
        "teacher_id": teacher_id,
        "user_id": user_id
    })

    if existing:
        # ✅ UPDATE REVIEW
        reviews_col.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "rating": rating,
                    "comment": comment,
                    "updated_at": datetime.now()
                }
            }
        )
    else:
        # ✅ INSERT NEW REVIEW
        reviews_col.insert_one({
            "teacher_id": teacher_id,
            "user_id": user_id,
            "rating": rating,
            "comment": comment,
            "created_at": datetime.now()
        })

    # 🔥 RECALCULATE RATING
    reviews = list(reviews_col.find({"teacher_id": teacher_id}))
    avg = sum(r["rating"] for r in reviews) / len(reviews)

    teachers_col.update_one(
        {"teacher_id": teacher_id},
        {
            "$set": {
                "rating": round(avg, 1),
                "total_students": len(reviews)
            }
        }
    )

    return redirect(url_for("teacher_page", user_id=teacher["user_id"]))


#-------- GET class---------
@app.route("/get-classes")
@role_required("Student")
def get_classes_by_date():

    date = request.args.get("date")   # format: "YYYY-MM-DD"
    user_id = session["user_id"]

    # ---------------- USER COURSES ----------------
    user_courses = list(user_courses_col.find({"user_id": user_id}))
    user_course_ids = [uc["course_id"] for uc in user_courses]

    # ---------------- USER CLASSES ----------------
    user_classes = list(user_classes_col.find({"user_id": user_id}))
    class_ids = [uc["class_id"] for uc in user_classes]

    classes = list(classes_col.find({
        "class_id": {"$in": class_ids},
        "date": date
    }))

    # ---------------- USER TESTS ----------------
    # Can't query by "date" field since tests store a datetime in "start_time"
    # So fetch all tests for user's courses and filter by date in Python
    all_tests = list(tests_col.find({"course_id": {"$in": user_course_ids}}))

    # ---------------- TEACHERS ----------------
    teacher_ids = list(set([c.get("teacher_id") for c in classes if c.get("teacher_id")]))
    teachers = list(users_col.find({"id": {"$in": teacher_ids}}))
    teacher_map = {t["id"]: t.get("fullname", "Unknown") for t in teachers}

    result = []

    # ---------------- ADD CLASSES ----------------
    for c in classes:
        result.append({
            "type": "class",
            "class_id": c.get("class_id"),
            "subject": c.get("subject", ""),
            "time": c.get("time", ""),
            "date": c.get("date", ""),
            "link": c.get("link", ""),
            "status": get_class_status(c),
            "teacher_name": teacher_map.get(c.get("teacher_id"), "Unknown")
        })

    # ---------------- ADD TESTS (filter by date) ----------------
    for t in all_tests:
        start_time = t.get("start_time")

        if not start_time:
            continue

        if isinstance(start_time, str):
            try:
                start_time = datetime.strptime(start_time, "%Y-%m-%dT%H:%M")
            except:
                try:
                    start_time = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
                except:
                    continue

        # only include if this test falls on the requested date
        if start_time.strftime("%Y-%m-%d") != date:
            continue

        result.append({
            "type": "test",
            "test_id": t.get("test_id"),
            "subject": t.get("name", t.get("subject", "Test")),
            "time": start_time.strftime("%H:%M"),
            "date": date,
            "duration": t.get("duration", 0)
        })

    # ---------------- SORT BY TIME ----------------
    result = sorted(result, key=lambda x: x.get("time", ""))

    return jsonify(result)

#------ subscribeee --------

@app.route("/subscribe", methods=["POST"])
@login_required
def subscribe():

    user_id = session["user_id"]
    plan = int(request.form.get("plan"))

    # calculate expiry date
    today = datetime.now()
    expiry_date = today + timedelta(days=30 * plan)

    formatted_date = expiry_date.strftime("%d/%m/%Y")

    # update DB
    users_col.update_one(
        {"id": user_id},
        {
            "$set": {
                "subscribed": "yes",
                "subcription_till": formatted_date
            }
        }
    )

    return redirect(url_for("LPstudenthome"))


#------ searchhh kar leee-----
@app.route("/search")
@login_required
def search():
    try:
        query = request.args.get("q", "").strip().lower()

        if not query:
            return jsonify([])

        regex = {"$regex": query, "$options": "i"}

        results = []

        # 🔍 Courses
        courses = list(courses_col.find({"name": regex}))
        for c in courses:
            name = c.get("name", "")
            score = 2 if name.lower().startswith(query) else 1

            results.append({
                "type": "course",
                "name": name,
                "id": c.get("course_id"),
                "score": score
            })

        # 🔍 Teachers
        teachers = list(users_col.find({
            "fullname": regex,
            "role": "Teacher"
        }))
        for t in teachers:
            name = t.get("fullname", "")
            score = 2 if name.lower().startswith(query) else 1

            results.append({
                "type": "teacher",
                "name": name,
                "id": t.get("id"),
                "score": score
            })

        # 🔍 Tests
        try:
            tests = list(tests_col.find({"name": regex}))
            for t in tests:
                name = t.get("name", "")
                score = 2 if name.lower().startswith(query) else 1

                results.append({
                    "type": "test",
                    "name": name,
                    "id": t.get("test_id"),
                    "score": score
                })
        except:
            pass

        # 🔥 Sort by score (exact match first)
        results = sorted(results, key=lambda x: x["score"], reverse=True)

        return jsonify(results[:5])

    except Exception as e:
        print("SEARCH ERROR:", e)
        return jsonify([])

@app.route("/search-page")
@login_required
def search_page():

    query = request.args.get("q", "")

    regex = {"$regex": query, "$options": "i"}

    courses = list(courses_col.find({"name": regex}))
    teachers = list(users_col.find({"fullname": regex, "role": "Teacher"}))
    tests = list(classes_col.find({"subject": regex}))

    return render_template(
        "search_results.html",
        courses=courses,
        teachers=teachers,
        tests=tests,
        query=query
    )


@app.route("/update-teacher/<teacher_id>", methods=["POST"])
@login_required
def update_teacher(teacher_id):

    teacher = teachers_col.find_one({"teacher_id": teacher_id})

    if teacher["user_id"] != session["user_id"]:
        return "Unauthorized", 403

    langs = request.form.get("languages")

    teachers_col.update_one(
        {"teacher_id": teacher_id},
        {
            "$set": {
                "headline": request.form.get("headline"),
                "education": request.form.get("education"),
                "experience": request.form.get("experience"),
                "bio": request.form.get("bio"),
                "languages": [l.strip() for l in langs.split(",")] if langs else []
            }
        }
    )

    return redirect(url_for("teacher_page", user_id=session["user_id"]))

@app.route("/toggle-follow/<teacher_id>", methods=["POST"])
@login_required
def toggle_follow(teacher_id):

    user_id = session["user_id"]

    # ❌ prevent self follow
    teacher = teachers_col.find_one({"teacher_id": teacher_id})
    if teacher["user_id"] == user_id:
        return jsonify({"status": "error"})

    existing = followers_col.find_one({
        "follower_id": user_id,
        "teacher_id": teacher_id
    })

    if existing:
        followers_col.delete_one({"_id": existing["_id"]})
        return jsonify({"status": "unfollowed"})
    else:
        followers_col.insert_one({
            "follower_id": user_id,
            "teacher_id": teacher_id
        })
        return jsonify({"status": "followed"})


@app.route("/upload-note", methods=["POST"])
@role_required("Teacher")
def upload_note():

    try:
        title = request.form.get("title")
        course_id = request.form.get("course_id")

        if "file" not in request.files:
            return jsonify({"error": "No file"}), 400

        file = request.files["file"]

        # 🔥 upload to cloudinary
        result = cloudinary.uploader.upload(
            file,
            resource_type="auto",
            folder="notes"
        )

        file_url = result.get("secure_url")

        # 🔥 FIX: correct teacher_id
        teacher = teachers_col.find_one({"user_id": session["user_id"]})

        notes_col.insert_one({
            "note_id": str(uuid.uuid4()),
            "title": title,
            "file_url": file_url,
            "course_id": course_id,
            "teacher_id": teacher["teacher_id"],  # ✅ FIXED
            "created_at": datetime.now()
        })

        return jsonify({"message": "Uploaded successfully ✅"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/teacher-course/<course_id>")
def teacher_course_page(course_id):

    course = courses_col.find_one({"course_id": course_id})

    teacher = teachers_col.find_one({"user_id": session["user_id"]})

    classes = list(classes_col.find({"course_id": course_id}))
    notes = list(notes_col.find({"course_id": course_id}))
    tests = list(db.tests.find({"course_id": course_id}))

    return render_template(
        "teacher_course.html",
        course=course,
        classes=classes,
        notes=notes,
        tests=tests,   # ✅ FIXED
        teacher_id=teacher["teacher_id"]
    )


@app.route("/teacher_class/<class_id>")
@role_required("Teacher")
def teacher_class_page(class_id):

    cls = classes_col.find_one({"class_id": class_id})

    if not cls:
        return render_template("teacher_class.html", invalid=True, cls=None)

    # 🔥 FIX: use teacher_id (NOT user_id)
    teacher = teachers_col.find_one({"user_id": session["user_id"]})

    if not teacher or cls.get("teacher_id") != teacher["teacher_id"]:
        return "Unauthorized", 403

    teacher_user = users_col.find_one({"id": session["user_id"]})

    return render_template(
        "teacher_class.html",
        cls=cls,
        teacher_name=teacher_user.get("fullname", "Teacher"),
        invalid=False
    )

@app.route("/update-class", methods=["POST"])
@role_required("Teacher")
def update_class():

    data = request.json

    classes_col.update_one(
        {"class_id": data["class_id"]},
        {
            "$set": {
                "subject": data.get("subject"),
                "class_number": int(data.get("class_number")),
                "category": data.get("category"),
                "date": data.get("date"),
                "time": data.get("time"),
                "status": data.get("status"),
                "link": data.get("link")
            }
        }
    )

    return jsonify({"message": "updated"})


@app.route("/delete-class/<class_id>", methods=["DELETE"])
def delete_class(class_id):

    try:
        # ---------- FIND CLASS ----------
        class_data = classes_col.find_one({"class_id": class_id})

        if not class_data:
            return jsonify({"error": "Class not found"}), 404

        # ---------- DELETE ----------
        classes_col.delete_one({"class_id": class_id})

        # ---------- UPDATE COURSE COUNT ----------
        courses_col.update_one(
            {"course_id": class_data["course_id"]},
            {"$inc": {"total_classes": -1}}
        )

        return jsonify({"msg": "Class deleted"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/add-class", methods=["POST"])
def add_class():
    try:
        data = request.json

        # ---------- VALIDATION ----------
        if not data.get("subject") or not data.get("date") or not data.get("time"):
            return jsonify({"error": "Missing fields"}), 400

        # ---------- ROLE CHECK ----------
        user_role = session.get("role")  # make sure you store role in session

        # Admin → Paid class, Others → Free
        is_free = False if user_role == "Admin" else True

        # ---------- CREATE CLASS ----------
        new_class = {
            "class_id": str(uuid.uuid4()),
            "course_id": data.get("course_id"),
            "teacher_id": ADMIN_ID,

            "subject": data.get("subject"),
            "date": data.get("date"),
            "time": data.get("time"),

            "class_number": data.get("class_number", 0),
            "category": data.get("category", ""),

            "status": "upcoming",
            "is_free": is_free,   # ✅ dynamic

            "created_at": datetime.utcnow(),
            "link": data.get("link", "")
        }

        classes_col.insert_one(new_class)

        # ---------- UPDATE COURSE COUNT ----------
        courses_col.update_one(
            {"course_id": data.get("course_id")},
            {"$inc": {"total_classes": 1}}
        )

        # =========================================
        # 🔥 AUTO ENROLL STUDENTS INTO NEW CLASS
        # =========================================

        course_id = data.get("course_id")

        enrolled_users = user_courses_col.find({
            "course_id": course_id
        })

        bulk_data = []
        for user in enrolled_users:
            bulk_data.append({
                "user_id": user["user_id"],
                "class_id": new_class["class_id"]
            })

        if bulk_data:
            user_classes_col.insert_many(bulk_data)

        # =========================================

        return jsonify({
            "msg": "Class added & students auto-enrolled ✅",
            "class_id": new_class["class_id"],
            "is_free": is_free
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route("/cancel-class/<class_id>", methods=["POST"])
def cancel_class(class_id):

    classes_col.update_one(
        {"class_id": class_id},
        {"$set": {"status": "cancelled"}}
    )

    return jsonify({"message":"cancelled"})

@app.route("/update-note", methods=["POST"])
def update_note():

    data = request.json

    notes_col.update_one(
        {"note_id": data["note_id"]},
        {"$set": {"title": data["title"]}}
    )

    return jsonify({"message":"updated"})

@app.route("/delete-note/<note_id>", methods=["DELETE"])
def delete_note(note_id):

    notes_col.delete_one({"note_id": note_id})

    return jsonify({"message":"deleted"})


@app.route("/student_class/<class_id>")
@login_required
def student_class_page(class_id):

    cls = classes_col.find_one({"class_id": class_id})

    # ❌ INVALID CLASS
    if not cls:
        return render_template(
            "student_class.html",
            invalid=True,
            cls=None
        )

    # ---------------- TEACHER ----------------
    teacher = users_col.find_one({"id": cls.get("teacher_id")})
    teacher_name = teacher["fullname"] if teacher else "Unknown"

    # ---------------- TIME LOGIC ----------------
    class_dt = get_class_datetime(cls)
    now = datetime.now()

    diff_minutes = (class_dt - now).total_seconds() / 60

    # ---------------- STATUS ----------------
    if diff_minutes > 0:
        status = "upcoming"
    elif -60 <= diff_minutes <= 0:
        status = "live"
    else:
        status = "completed"

    # ---------------- FLAGS ----------------
    is_live = status == "live"
    can_join = -10 <= diff_minutes <= 60

    return render_template(
        "student_class.html",
        cls=cls,
        teacher_name=teacher_name,
        status=status,
        is_live=is_live,
        can_join=can_join,
        invalid=False
    )

@app.route("/join-class", methods=["POST"])
@login_required
def join_class():

    data = request.json
    class_id = data.get("class_id")

    user = users_col.find_one({"id": session["user_id"]})

    if not class_id:
        return jsonify({"error": "Missing class_id"}), 400

    # 🔥 prevent duplicate join spam
    last_join = comments_col.find_one(
        {
            "class_id": class_id,
            "user_id": session["user_id"],
            "type": "join"
        },
        sort=[("created_at", -1)]
    )

    if last_join:
        diff = (datetime.now() - last_join["created_at"]).total_seconds()
        if diff < 30:
            return jsonify({"message": "already joined recently"})

    comments_col.insert_one({
        "comment_id": str(uuid.uuid4()),
        "class_id": class_id,
        "user_id": session["user_id"],
        "name": user.get("fullname"),
        "role": user.get("role"),
        "type": "join",  # 🔥 IMPORTANT
        "created_at": datetime.now()
    })

    return jsonify({"message": "joined"})


# ---------------- ADD COMMENT ----------------
@app.route("/add-comment", methods=["POST"])
@login_required
def add_comment():

    data = request.json
    class_id = data.get("class_id")
    text = data.get("text")

    if not class_id or not text:
        return jsonify({"error": "Missing data"}), 400

    user = users_col.find_one({"id": session["user_id"]})

    comment = {
        "comment_id": str(uuid.uuid4()),
        "class_id": class_id,
        "user_id": session["user_id"],
        "name": user.get("fullname"),
        "role": user.get("role"),
        "text": text,
        "type": "message",
        "created_at": datetime.utcnow()   # ✅ FIXED (UTC time)
    }

    comments_col.insert_one(comment)

    return jsonify({"message": "sent"})


# ---------------- GET COMMENTS ----------------
@app.route("/get-comments/<class_id>")
@login_required
def get_comments(class_id):

    comments = list(
        comments_col.find({"class_id": class_id})
        .sort("created_at", 1)
    )

    result = []
    join_buffer = []

    def flush_join_buffer():
        if not join_buffer:
            return

        if len(join_buffer) == 1:
            c = join_buffer[0]
            result.append({
                "type": "join",
                "text": f"{c['name']} joined",
                "time": c["created_at"].strftime("%I:%M:%S %p"),
                "created_at": c["created_at"].isoformat()
            })
        else:
            first = join_buffer[0]["name"]
            count = len(join_buffer) - 1
            last = join_buffer[-1]

            result.append({
                "type": "join",
                "text": f"{first} and {count} others joined",
                "time": last["created_at"].strftime("%I:%M:%S %p"),
                "created_at": last["created_at"].isoformat()
            })

        join_buffer.clear()

    for c in comments:

        created_at = c.get("created_at")

        # ✅ safety check
        if not created_at:
            continue

        # ✅ if somehow string slipped in, convert it
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        if c.get("type") == "join":
            join_buffer.append({
                **c,
                "created_at": created_at
            })

        else:
            flush_join_buffer()

            result.append({
                "type": "message",
                "name": c.get("name"),
                "role": c.get("role"),
                "text": c.get("text"),
                "time": created_at.strftime("%I:%M:%S %p"),  # ✅ FIXED
                "created_at": created_at.isoformat()
            })

    flush_join_buffer()

    return jsonify(result)

#------------ STATIC PAGESSSS by MOHD HAMZAH ---------------------# 
@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/teachers")
def teachers_page():

    teachers = list(users_col.find({"role": "Teacher"}))

    html = """
    <html>
    <head><title>Our Teachers</title></head>
    <body style="font-family:Poppins; padding:40px;">
    <h1>Our Teachers</h1>
    """

    for t in teachers:
        html += f"""
        <div style="margin-bottom:20px;">
            <h3>{t.get('fullname')}</h3>
            <p>{t.get('category', 'Teacher')}</p>
        </div>
        """

    html += '<a href="/">⬅ Back to Home</a></body></html>'

    return html

@app.route("/careers")
def careers():
    return """
    <html>
    <body style="font-family:Poppins; padding:40px;">
        <h1>Careers</h1>
        <p>Join SmartEdu and help shape the future of education 🚀</p>
        <a href="/">⬅ Back</a>
    </body>
    </html>
    """

@app.route("/blog")
def blog():
    return """
    <html>
    <body style="font-family:Poppins; padding:40px;">
        <h1>Blog</h1>
        <p>Coming soon...</p>
        <a href="/">⬅ Back</a>
    </body>
    </html>
    """

@app.route("/help")
def help_center():
    return """
    <html>
    <body style="font-family:Poppins; padding:40px;">
        <h1>Help Center</h1>
        <p>Email: support@smartedu.com</p>
        <p>Phone: +91 9876543210</p>
        <a href="/">⬅ Back</a>
    </body>
    </html>
    """

@app.route("/faq")
def faq():
    return """
    <html>
    <body style="font-family:Poppins; padding:40px;">
        <h1>FAQs</h1>

        <p><b>Q:</b> How to enroll?</p>
        <p><b>A:</b> Login and click enroll.</p>

        <p><b>Q:</b> Are courses free?</p>
        <p><b>A:</b> Some are free, some are paid.</p>

        <a href="/">⬅ Back</a>
    </body>
    </html>
    """

@app.route("/terms")
def terms():
    return """
    <html>
    <body style="font-family:Poppins; padding:40px;">
        <h1>Terms & Conditions</h1>
        <p>Use SmartEdu responsibly. Misuse may result in account suspension.</p>
        <a href="/">⬅ Back</a>
    </body>
    </html>
    """


@app.route("/privacy")
def privacy():
    return """
    <html>
    <body style="font-family:Poppins; padding:40px;">
        <h1>Privacy Policy</h1>
        <p>Your data is सुरक्षित (safe). We do not share your information.</p>
        <a href="/">⬅ Back</a>
    </body>
    </html>
    """

@app.route("/recording/<class_id>")
@login_required
def recording(class_id):

    # ✅ Get logged-in user
    user = users_col.find_one({"id": session.get("user_id")})

    if not user:
        return redirect(url_for("LPfront"))  # safety fallback

    # ✅ Get class
    cls = classes_col.find_one({"class_id": class_id})

    if not cls:
        return render_template(
            "student_class_recording.html",
            link=None,
            cls=None
        )

    # ✅ Get recording link safely
    link = cls.get("link")

    # ---------------- OPTIONAL SECURITY ----------------
    # Allow only:
    # - teacher of this class
    # - or enrolled student

    is_teacher = (cls.get("teacher_id") == user.get("id"))

    is_enrolled = user_classes_col.find_one({
        "user_id": user.get("id"),
        "class_id": class_id
    })

    if not is_teacher and not is_enrolled:
        return "⛔ Access Denied", 403

    # ✅ Render page
    return render_template(
        "student_class_recording.html",
        link=link,
        cls=cls,
        user=user,
        role=user.get("role")   # ✅ use this in JS if needed
    )



@app.route("/update-watchtime", methods=["POST"])
@login_required
def update_watchtime():
    data = request.json
    class_id = data.get("class_id")
    seconds = data.get("seconds", 0)
    user_id = session["user_id"]

    if not class_id or seconds <= 0:
        return jsonify({"message": "invalid data"}), 400

    record = db.student_watchtime.find_one({
        "user_id": user_id,
        "class_id": class_id
    })

    if record and record.get("last_updated"):
        diff = datetime.now() - record["last_updated"]
        if diff < timedelta(seconds=3):   # ✅ FIXED - was 4s, now 3s for safe margin
            return jsonify({"message": "ignored too soon"})

    db.student_watchtime.update_one(
        {"user_id": user_id, "class_id": class_id},
        {
            "$inc": {"watched_seconds": seconds},
            "$set": {"last_updated": datetime.now()}
        },
        upsert=True
    )

    return jsonify({"message": "updated"})

@app.route("/get-watchtime")
@login_required
def get_watchtime():
    user_id = session["user_id"]
    
    records = list(db.student_watchtime.find({"user_id": user_id}))
    
    total_seconds = sum(r.get("watched_seconds", 0) for r in records)
    
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    
    return jsonify({
        "total_seconds": total_seconds,
        "hours": hours,
        "minutes": minutes,
        "classes_watched": len(records)
    })

@app.route("/create-test", methods=["POST"])
@role_required("Teacher")
def create_test():
    data = request.json

    test_id = str(uuid.uuid4())

    start_time = datetime.strptime(
        data.get("start_time"),
        "%Y-%m-%dT%H:%M"
    )

    tests_col.insert_one({
        "test_id": test_id,
        "course_id": data.get("course_id"),
        "teacher_id": data.get("teacher_id"),

        "name": data.get("name"),
        "duration": int(data.get("duration")),
        "start_time": start_time,

        "marks_per_q": float(data.get("marks_per_q")),
        "negative_marks": float(data.get("negative_marks")),

        # ✅ ADD THIS
        "subjects": data.get("subjects"),  

        "questions": data.get("questions"),
        "created_at": datetime.now()
    })

    return jsonify({"message": "Test created"})

@app.route("/tests/<test_id>")
@login_required
def live_test_page(test_id):

    test = tests_col.find_one({"test_id": test_id})

    now_utc = datetime.now(timezone.utc)

    start_time = test.get("start_time")  # naive datetime (IST intended)

    # Step 1: Attach IST timezone manually (+05:30)
    ist_offset = timedelta(hours=5, minutes=30)
    start_time_ist = start_time.replace(tzinfo=timezone(ist_offset))

    # Step 2: Convert IST → UTC
    start_time_utc = start_time_ist.astimezone(timezone.utc)

    # DEBUG
    print("NOW UTC:", now_utc)
    print("START UTC:", start_time_utc)

    # ⛔ BEFORE START
    if now_utc < start_time_utc:
        return render_template("test_wait.html", test=test)

    return render_template("live_test_page.html", test=test, user_id=session["user_id"])

@app.route("/get-results/<test_id>")
def get_results(test_id):

    attempts = list(test_attempts_col.find({"test_id": test_id}))

    output = []

    for a in attempts:

        user = users_col.find_one({"id": a.get("user_id")})

        output.append({
            "user_id": a.get("user_id"),
            "student_name": user.get("fullname") if user else "Unknown",
            "score": a.get("score", 0),
            "correct": a.get("correct", 0),
            "wrong": a.get("wrong", 0)
        })

    return jsonify(output)

@app.route("/get-attempt/<test_id>/<user_id>")
def get_attempt(test_id, user_id):

    attempt = test_attempts_col.find_one({
        "test_id": test_id,
        "user_id": user_id
    })

    test = tests_col.find_one({"test_id": test_id})

    if not attempt or not test:
        return jsonify({"error": "Not found"}), 404

    questions = test.get("questions", [])
    answers = attempt.get("answers", {})

    result = []

    for i, q in enumerate(questions):

        user_ans = answers.get(str(i), -1)

        result.append({
            "question": q.get("question"),
            "options": q.get("options"),
            "correct": q.get("correct"),
            "marked": int(user_ans),
            "is_correct": int(user_ans) == q.get("correct")
        })

    return jsonify(result)


@app.route("/submit-test", methods=["POST"])
@login_required
def submit_test():

    data = request.json
    test_id = data.get("test_id")
    answers = data.get("answers")
    user_id = session["user_id"]

    test = tests_col.find_one({"test_id": test_id})

    score = 0
    correct = 0
    wrong = 0

    for i, q in enumerate(test["questions"]):

        user_ans = answers.get(str(i))

        if user_ans is None or int(user_ans) == -1:  # ✅ fixed unanswered check
            continue

        if int(user_ans) == q["correct"]:
            score += q["marks"]
            correct += 1
        else:
            score -= q["negative"]
            wrong += 1

    test_attempts_col.update_one(
        {"user_id": user_id, "test_id": test_id},
        {
            "$set": {
                "answers": answers,
                "score": score,
                "correct": correct,
                "wrong": wrong
            }
        },
        upsert=True
    )

    return jsonify({
        "score": score,
        "correct": correct,
        "wrong": wrong,
        "answers": answers
    })


@app.route("/schedule-free-class", methods=["POST"])
@role_required("Teacher")
def schedule_free_class():
    try:
        title = request.form.get("title")
        date = request.form.get("date")
        time = request.form.get("time")

        if not title or not date or not time:
            return jsonify({"error": "Missing fields"}), 400

        teacher = teachers_col.find_one({"user_id": session["user_id"]})

        if not teacher:
            return jsonify({"error": "Teacher not found"}), 404

        class_id = str(uuid.uuid4())

        classes_col.insert_one({
            "class_id": class_id,
            "course_id": "free",
            "teacher_id": teacher["teacher_id"],
            "subject": title,
            "date": date,
            "time": time,
            "status": "upcoming",
            "is_free": True,
            "created_at": datetime.now()
        })

        return jsonify({"message": "Free class scheduled 🚀"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/get-result/<test_id>")
@login_required
def get_result(test_id):

    user_id = session["user_id"]

    attempt = test_attempts_col.find_one({
        "user_id": user_id,
        "test_id": test_id
    })

    if not attempt:
        return jsonify({"attempted": False})

    return jsonify({
        "attempted": True,
        "score": attempt["score"],
        "correct": attempt["correct"],
        "wrong": attempt["wrong"],
        "answers": attempt["answers"]
    })
    

# ---------------- HEALTH CHECK ----------------
@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200



# ---------------- ADMIN -------------
@app.route("/admin")
@role_required("Admin")
def admin_dashboard():

    courses = list(courses_col.find())

    return render_template("admin.html", courses=courses)

@app.route("/admin/course/<course_id>")
@role_required("Admin")
def admin_course(course_id):

    course = courses_col.find_one({"course_id": course_id})

    classes = list(classes_col.find({"course_id": course_id}))
    notes = list(notes_col.find({"course_id": course_id}))
    tests = list(tests_col.find({"course_id": course_id}))

    return render_template("course_admin.html",
        course=course,
        classes=classes,
        notes=notes,
        tests=tests,
        teacher_id="admin"   # dummy
    )

@app.route("/delete-course/<course_id>", methods=["DELETE"])
@role_required("Admin")
def delete_course(course_id):

    courses_col.delete_one({"course_id": course_id})
    classes_col.delete_many({"course_id": course_id})
    notes_col.delete_many({"course_id": course_id})
    tests_col.delete_many({"course_id": course_id})

    return jsonify({"msg":"deleted"})

@app.route("/add-course", methods=["POST"])
def add_course():

    try:
        data = request.get_json()

        # ---------- DEBUG (optional) ----------
        print("Incoming:", data)

        if not data:
            return jsonify({"error": "No JSON received"}), 400

        # ---------- VALIDATION ----------
        if not data.get("name"):
            return jsonify({"error": "Course name required"}), 400

        # ---------- CREATE COURSE ----------
        new_course = {
            "course_id": str(uuid.uuid4()),
            "name": data.get("name"),
            "desc": data.get("desc", ""),
            "category": data.get("category", "General"),

            "teacher_id": ADMIN_ID,

            "total_classes": 0,
            "start_date": datetime.utcnow(),
            "created_at": datetime.utcnow()
        }

        courses_col.insert_one(new_course)

        return jsonify({
            "msg": "Course added successfully",
            "course_id": new_course["course_id"]
        })

    except Exception as e:
        print("ERROR:", str(e))  # 🔥 IMPORTANT (see terminal)
        return jsonify({"error": str(e)}), 500

@app.route("/admin-data")
@role_required("Admin")
def admin_data():
    return jsonify(list(courses_col.find({}, {"_id":0})))

@app.route("/admin-course-data/<course_id>")
@role_required("Admin")
def admin_course_data(course_id):

    return jsonify({
        "course": courses_col.find_one({"course_id":course_id},{"_id":0}),
        "classes": list(classes_col.find({"course_id":course_id},{"_id":0})),
        "notes": list(notes_col.find({"course_id":course_id},{"_id":0})),
        "tests": list(tests_col.find({"course_id":course_id},{"_id":0}))
    })

@app.route("/update-class-admin", methods=["POST"])
def update_class_admin():
    data = request.get_json()

    classes_col.update_one(
        {"class_id": data["class_id"]},
        {
            "$set": {
                "subject": data.get("subject"),
                "date": data.get("date"),
                "time": data.get("time"),
                "link": data.get("link", "")
            }
        }
    )

    return jsonify({"msg": "updated"})

@app.route("/admin-users-data")
@role_required("Admin")
def admin_users_data():
    users = list(users_col.find({}, {"_id": 0, "password": 0}))
    return jsonify(users)



# ---------------- GLOBAL ERROR HANDLERS ----------------

@app.errorhandler(400)
def bad_request(e):
    return handle_error("Bad Request", 400, str(e))

@app.errorhandler(401)
def unauthorized(e):
    return handle_error("Unauthorized", 401, "Login required")

@app.errorhandler(403)
def forbidden(e):
    return handle_error("Forbidden", 403, "You don't have permission")

@app.errorhandler(404)
def not_found(e):
    return handle_error("Not Found", 404, "Resource not found")

@app.errorhandler(405)
def method_not_allowed(e):
    return handle_error("Method Not Allowed", 405, "Invalid HTTP method")

@app.errorhandler(500)
def internal_error(e):
    return handle_error("Server Error", 500, "Something went wrong")

@app.errorhandler(Exception)
def handle_all_errors(e):
    print("🔥 UNCAUGHT ERROR:", str(e))
    return handle_error("Unexpected Error", 500, str(e))


# 🔥 COMMON HANDLER FUNCTION
def handle_error(title, status_code, message):
    if request.path.startswith("/api") or request.is_json:
        return jsonify({
            "error": title,
            "message": message,
            "status": status_code
        }), status_code
    else:
        return render_template(
            "error.html",
            title=title,
            message=message,
            status=status_code
        ), status_code

@app.errorhandler(Exception)
def handle_all_errors(e):
    logging.error(f"ERROR: {str(e)}")
    return handle_error("Unexpected Error", 500, str(e))


# ---------------- Run ----------------
if __name__ == "__main__":
    socketio.run(app, debug=True)
