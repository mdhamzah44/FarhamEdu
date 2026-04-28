# 🎓 FarhamEdu - Online Learning Platform

FarhamEdu is a full-stack online education platform built with **Flask**, **MongoDB**, and **Socket.IO**. It supports students, teachers, and admins with features like course creation, live classes, tests, notes sharing, and real-time interaction.

---

## 🚀 Features

### 👨‍🎓 Student
- Register & login
- Enroll in courses
- Attend live & upcoming classes
- Attempt tests
- Watch class recordings
- Track learning progress (watch time)
- Follow teachers
- Add reviews

### 👨‍🏫 Teacher
- Create & manage courses
- Schedule classes (paid & free)
- Upload notes (PDF, docs, etc.)
- Conduct tests
- Manage profile & image
- View student engagement

### 🛠️ Admin
- Manage all courses
- Add/edit/delete classes
- Monitor users
- Full platform control

### 💬 Real-time Features
- Live class chat
- Join notifications
- Interactive classroom experience

---

## 🧱 Tech Stack

- **Backend:** Flask (Python)
- **Database:** MongoDB Atlas
- **Real-time:** Flask-SocketIO (Eventlet)
- **Cloud Storage:** Cloudinary
- **Frontend:** HTML, CSS, Jinja2 Templates
- **Authentication:** Session-based auth + password hashing

---

## 📂 Project Structure
FarhamEdu/
- │── app.py
- │── templates/
- │── static/
- │── requirements.txt
- │── README.md



---

## ⚙️ Installation

### 1. Clone the repo
```bash
git clone https://github.com/mdhamzah44/FarhamEdu.git
cd FarhamEdu


2. Create virtual environment
python -m venv venv
source venv/bin/activate   # Mac/Linux
venv\Scripts\activate      # Windows

3. Install dependencies
pip install -r requirements.txt

4. Set environment variables
export SECRET_KEY=your_secret_key

▶️ Run the App
Bash python app.py

App will run on: http://127.0.0.1:5000/



🔐 Roles
Role	Access
Student	Courses, classes, tests
Teacher	Create courses, classes, notes
Admin	Full control
📸 Key Modules
Authentication (Register/Login)
Course Management
Class Scheduling
Live Chat System
Test System with scoring
Notes Upload System
Watch Time Tracking
⚠️ Security Notes
Do NOT expose:
MongoDB URI
Cloudinary credentials
Use .env file in production
🧪 API Highlights
/register → Create account
/login → Login
/create_course → Teacher creates course
/enroll/<course_id> → Student enroll
/submit-test → Submit answers
/add-comment → Live chat
🌐 Deployment

You can deploy on:

Render
Vercel (frontend)
Railway / AWS / DigitalOcean
📌 Future Improvements
Payment integration 💳
Video streaming integration 🎥
Mobile app 📱
AI-based recommendations 🤖


👨‍💻 Author:
Developed by Mohd Hamzah

