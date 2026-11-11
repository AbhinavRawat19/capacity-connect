# Capacity Connect

### One platform. Connected learning. Measurable growth.

Capacity Connect is an inclusive e-learning platform that connects learners and trainers through structured courses, interactive assessments, practice resources, and progress tracking.

It brings the essential parts of the learning journey into one ecosystem — from discovering courses and practicing questions to earning certificates and tracking achievements.

---

## The Problem

Online learning has become increasingly accessible, but the learning experience remains fragmented.

- Learners switch between multiple platforms for courses, practice, assessments, and progress tracking.
- Limited opportunities for structured practice make it difficult to identify and improve weak areas.
- Trainers need better ways to manage courses, assessments, learners, and their educational services.
- Lack of motivation and consistent progress tracking can make learners abandon their goals.
- Payment and course-management workflows can create additional friction for independent trainers.

**The result?** Learning becomes disconnected, difficult to track, and harder to sustain.

## Our Solution

Capacity Connect brings learners and trainers together through a unified learning ecosystem.

Rather than focusing exclusively on delivering course content, the platform supports the complete learning journey:

**Discover → Learn → Practice → Evaluate → Improve → Achieve**

Learners get access to organized educational resources and tools to monitor their progress. Trainers get an environment to manage and deliver learning experiences.

---

## Key Features

### 1. Structured Learning
- Discover and explore available courses.
- Access organized lessons and learning materials.
- Track course completion and learning progress.
- Preview supported course content.

### 2. Practice & Assessment
- Practice using a dedicated question bank.
- Attempt interactive quizzes and assessments.
- Receive feedback on submitted answers.
- Revisit missed questions to strengthen understanding.

### 3. Trainer Ecosystem
- Create and manage courses.
- Organize lessons and assessments.
- Manage educational content.
- Access trainer-oriented analytics.

### 4. Secure Payment Integration
- PayPal-powered payment workflows.
- Course purchase functionality.
- Refund workflows.
- Trainer payout support.

### 5. Course Completion Certificates
- Earn certificates after completing eligible courses.
- Track learning achievements.

### 6. Gamified Learning
- Achievement system.
- Learning streaks.
- Leaderboards.
- Progress-based motivation.

### 7. Course Discovery
- Explore available learning opportunities.
- Filter courses to find relevant content.

---

## Technology Stack

| Layer | Technologies |
|---|---|
| Frontend | HTML, CSS, JavaScript, React |
| Backend | Python, Django, Django REST Framework |
| API Services | FastAPI |
| Database | SQLite |
| ORM & Migrations | SQLAlchemy, Alembic |
| Authentication | JWT |
| Payments | PayPal API |
| Server | Uvicorn |
| Testing | pytest |
| Version Control | Git, GitHub |

---

## System Architecture

Capacity Connect uses a modular backend architecture.

- **Django:** Handles core application functionality, user management, courses, and platform operations.
- **Django REST Framework:** Exposes REST APIs for frontend communication.
- **FastAPI:** Provides a separate API service for supporting backend functionality.
- **SQLite:** Stores application data.
- **PayPal:** Supports payment-related workflows.
- **Frontend:** Provides the learner and trainer interfaces.

The separation of responsibilities makes the application easier to maintain and extend.

---

## Getting Started

Follow these steps to run the project locally.

### Prerequisites

Make sure you have installed:

- Python 3.10+
- Git
- Node.js and npm (if using the frontend package)
- pip

### 1. Clone the Repository

```bash
git clone https://github.com/AbhinavRawat19/capacity-connect.git
cd capacity-connect
```

### 2. Set Up the Python Environment

```bash
python -m venv venv
```

Activate the environment.

**Windows:**

```bash
venv\Scripts\activate
```

**Linux/macOS:**

```bash
source venv/bin/activate
```

### 3. Install Dependencies

Install the dependencies using the requirements files provided in the respective backend directories.

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create the required `.env` files using the corresponding `.env.example` files.

Configure the necessary application settings, database configuration, authentication secrets, and PayPal credentials.

**Important:** Never commit API keys, passwords, or production secrets to GitHub.

### 5. Run the Backend

Start the Django application using its configured entry point.

Start the FastAPI service separately:

```bash
uvicorn backend.main:app --reload --port 8000
```

### 6. Run the Frontend

If the frontend uses npm:

```bash
npm install
npm run dev
```

Use the frontend's configured development command if it differs.

---

## Project Structure

The project is organized into separate application and service components.

```text
capacity-connect/
│
├── backend/
│   ├── Django application
│   └── FastAPI service
│
├── frontend/
│   └── Frontend application
│
├── requirements.txt
├── .env.example
├── README.md
└── ...
```

Refer to the respective application directories for their individual configurations and dependencies.

---

## Security & Reliability

Capacity Connect incorporates several important application-level safeguards:

- JWT-based authentication.
- Role-based access and authorization.
- Trainer ownership and resource validation.
- Quiz and assessment validation.
- Payment-related workflows.
- Backend test coverage.

Sensitive configuration values should be supplied through environment variables rather than committed to the repository.

---

## Future Scope

Capacity Connect is designed to evolve with additional learning capabilities.

Potential improvements include:

- AI-powered personalized learning recommendations.
- Adaptive learning paths based on learner performance.
- AI-assisted quiz generation.
- Intelligent identification of knowledge gaps.
- Expanded analytics for learners and trainers.
- Additional integrations with educational services.

---

## Our Vision

We believe learning should be more than accessing educational content.

It should be a continuous process of discovering knowledge, practicing skills, receiving feedback, measuring improvement, and celebrating achievements.

**Capacity Connect aims to make that entire journey accessible through one connected platform.**

---

## Contributors

Built with collaboration, experimentation, and a shared vision of making digital learning more accessible.

**Team: ELEVATE IQ**
1) Abhinav Rawat
2) Abhishek Kumar
3) Omar Shah
---

## License

Add the project's chosen open-source license here before publishing.