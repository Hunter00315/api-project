Healthcare Appointment System — Backend API
==========================================
Module  : Scalable Cloud Programming (H9SCPRO1)
Course  : MSc Cloud Computing — National College of Ireland
Region  : eu-north-1 (Stockholm)
Stack   : Python · Flask · Gunicorn · AWS DynamoDB · AWS SQS · EC2


────────────────────────────────────────────
1. PROJECT OVERVIEW
────────────────────────────────────────────
A RESTful backend that allows users to:
  • Check doctor slot availability
  • Reserve / cancel appointment slots
  • Receive health insights via an external API
  • Access weather and air quality data

Storage    : AWS DynamoDB (production) / slots.json (development)
Queue      : AWS SQS for async reservation event processing
Deployment : AWS EC2 t3.micro, Amazon Linux 2023


────────────────────────────────────────────
2. API ENDPOINTS
────────────────────────────────────────────

  GET  /health                     Service liveness check (no auth)
  GET  /slots[?doctor=<name>]      List slots, optionally by doctor (no auth)
  POST /reserve                    Book a slot          (X-API-Key required)
  DELETE /reserve/<reservation_id> Cancel a booking     (X-API-Key required)
  GET  /reservations[?doctor=<name>] List bookings      (X-API-Key required)
  POST /metrics                    Forward to health-calculation API (no auth)
  GET  /weather?city=<city>        Current weather      (no auth)
  GET  /aqi?city=<city>            Air quality index    (no auth)

All protected endpoints require the header:
  X-API-Key: <value-of-API_KEY-env-var>


POST /reserve — example body
  {
    "patient_name": "John Doe",
    "doctor":       "Dr Smith",
    "time":         "10:00"
  }

POST /metrics — example body
  {
    "age": 25, "gender": "male", "weight": 80,
    "height": 180, "activity_level": "moderate", "goal": "cut"
  }


────────────────────────────────────────────
3. LOCAL DEVELOPMENT SETUP
────────────────────────────────────────────

Prerequisites: Python 3.9+, pip

  # 1. Clone the repository
  git clone https://github.com/Hunter00315/api-project.git
  cd api-project

  # 2. Create and activate a virtual environment
  python3 -m venv venv
  source venv/bin/activate          # Linux / macOS
  venv\Scripts\activate             # Windows

  # 3. Install dependencies
  pip install -r requirements.txt
  pip install pytest pytest-cov     # testing extras

  # 4. Copy and edit the environment file
  cp .env.example .env
  # Edit .env — set USE_DYNAMODB=false for local JSON backend

  # 5. Run the development server
  python app.py
  # API is now available at http://localhost:5000

  # 6. Run unit tests
  pytest tests/ -v


────────────────────────────────────────────
4. EC2 PRODUCTION SETUP (one-time)
────────────────────────────────────────────

  # Connect to EC2
  chmod 400 cloud-key-pair.pem
  ssh -i cloud-key-pair.pem ec2-user@<EC2_PUBLIC_IP>

  # --- On the EC2 instance ---

  # Update system and install dependencies
  sudo dnf update -y
  sudo dnf install python3 python3-pip git -y

  # Clone the repository
  git clone https://github.com/Hunter00315/api-project.git ~/api-project
  cd ~/api-project

  # Install Python packages
  pip3 install -r requirements.txt --user

  # Create the environment file
  cp .env.example .env
  nano .env          # fill in all values

  # Seed DynamoDB table and SQS queue
  python3 setup_dynamodb.py

  # Create log directory
  sudo mkdir -p /var/log/healthcare-api
  sudo chown ec2-user /var/log/healthcare-api

  # Install and enable systemd service
  sudo cp healthcare-api.service /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable healthcare-api
  sudo systemctl start healthcare-api
  sudo systemctl status healthcare-api

  # Verify
  curl http://localhost:5000/health


────────────────────────────────────────────
5. CI/CD (GITHUB ACTIONS)
────────────────────────────────────────────

The workflow file is at .github/workflows/deploy.yml

On every push to main:
  1. Runs unit tests
  2. On success, SSHes into EC2, pulls latest code, restarts service

Required GitHub repository secrets:
  EC2_PUBLIC_IP  — public IP address of the EC2 instance
  EC2_SSH_KEY    — contents of cloud-key-pair.pem (the private key)

Add them at:
  GitHub repo → Settings → Secrets and variables → Actions → New repository secret


────────────────────────────────────────────
6. ENVIRONMENT VARIABLES
────────────────────────────────────────────

See .env.example for the full list.  Key variables:

  USE_DYNAMODB        true | false  (default: true)
  AWS_REGION          AWS region    (default: eu-north-1)
  DYNAMODB_TABLE      Table name    (default: HealthcareSlots)
  SQS_QUEUE_URL       Full SQS queue URL
  API_KEY             Secret key for protected endpoints
  WAQI_TOKEN          WAQI API token (default: demo)
  HEALTH_API_URL      Classmate health calculation API URL


────────────────────────────────────────────
7. SCALABILITY
────────────────────────────────────────────

  • DynamoDB     — serverless, auto-scaling NoSQL storage
  • SQS          — decoupled async reservation event queue
  • Gunicorn     — multi-worker WSGI server (4 workers by default)
  • EC2 Auto Scaling Groups + Load Balancer can be added on top


────────────────────────────────────────────
8. PROJECT STRUCTURE
────────────────────────────────────────────

  app.py                     Flask application entry point
  requirements.txt           Python dependencies
  slots.json                 Initial slot seed data
  setup_dynamodb.py          One-time DynamoDB table + SQS queue setup
  healthcare-api.service     systemd unit file for EC2
  .env.example               Environment variable template
  services/
    reservation_service.py   DynamoDB + JSON reservation logic
    weather_service.py       wttr.in weather integration
    aqi_service.py           WAQI air quality integration
    health_service.py        Classmate health API proxy
  tests/
    conftest.py              pytest fixtures
    test_app.py              Unit tests
  .github/workflows/
    deploy.yml               GitHub Actions CI/CD pipeline
