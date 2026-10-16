# Real-Time Support Ticket System

# Project Overview

The Real-Time Support Ticket System is a backend application developed using FastAPI and MySQL. It allows customers to create and track support tickets, agents to manage and resolve tickets, and administrators to monitor ticket assignments and service-level agreements (SLAs).

The system uses JWT authentication, role-based access control, asynchronous database operations, WebSockets, and scheduled background tasks.

# Objectives

- Develop REST APIs using FastAPI.
- Implement secure authentication using JWT.
- Provide role-based access for Customers, Agents, and Admins.
- Manage support tickets, categories, priorities, and statuses.
- Automatically assign tickets to eligible agents.
- Maintain ticket history and notifications.
- Support real-time communication through WebSockets.
- Monitor SLA deadlines and ticket escalation.
- Provide API documentation through Swagger UI.

# Technologies Used

| Technology         | Purpose                                 |
|-------             |-------                                  |
| Python 3.12        | Backend programming                     |
| FastAPI            | REST API development                    |
| Pydantic           | Request validation and response schemas |
| SQLAlchemy         | Asynchronous database operations        |
| MySQL              | Database management                     |
| aiomysql           | Asynchronous MySQL driver               |
| Alembic            | Database migrations                     |
| JWT                | Authentication                          |
| Passlib and bcrypt | Password hashing                        |
| WebSockets         | Real-time communication                 |
| APScheduler        | Scheduled background jobs               |
| Uvicorn            | ASGI server                             |

# Main Features

# Authentication and Authorization
- Customer registration and login.
- JWT-based authentication.
- Password hashing.
- Role-based access control for Customers, Agents, and Admins.
- Initial administrator setup.

# Ticket Management
- Create and view support tickets.
- Generate ticket numbers using the `TKT-YYYYMMDD-####` format.
- Assign categories and priorities.
- Track ticket status.
- Reopen eligible resolved tickets.
- Maintain ticket history.

# Agent Management
- Create and list agents.
- Manage agent availability.
- Configure maximum open-ticket limits.
- Associate agents with support categories.
- Support automatic ticket assignment based on agent eligibility.

# SLA Management
- Configure first-response and resolution deadlines.
- Track SLA deadlines.
- Monitor ticket SLA status.

# Real-Time Features
- WebSocket-based ticket communication.
- Real-time notification functionality.
- Notification retrieval and read-status management.

**Note:** File attachments, SMTP email notifications, complete WebSocket flows, SLA escalation, and all assignment rules must be verified against the implementation and tested before claiming them as fully working features.

# Project Structure

The project is organized into application modules for routes, models, schemas, services, authentication, WebSockets, and database management. The exact files may vary depending on the current implementation.

support_ticket_system/
│
├── app/
│   ├── main.py
│   ├── models/
│   ├── routers/
│   ├── schemas/
│   ├── services/
│   ├── auth/
│   ├── websockets/
│   ├── jobs/
│   └── database.py
│
├── alembic/
├── .env
├── alembic.ini
├── requirements.txt
└── README.md

# Prerequisites
Install the following before running the application:
- Python 3.9 or later
- MySQL Server
- MySQL Workbench (optional)
- Visual Studio Code
- Git (optional)

# Installation and Setup

# Create a virtual environment
- Open the VS Code terminal and execute:
python -m venv venv

- Activate the environment on Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create the MySQL database
- Open MySQL Workbench and execute:
CREATE DATABASE support_ticket_db;

# Configure environment variables
Create or update the '.env' file in the project root using the variable names expected by your application.

# Run database migrations
- If your project uses Alembic migrations, execute:
alembic upgrade head

- If migrations have not yet been created, generate them using the project's configured Alembic setup before applying them.

#  Start the application
- uvicorn app.main:app --reload

- The server should start at:
`http://127.0.0.1:8000`

# API Documentation

Once the server is running, open Swagger UI:
'http://127.0.0.1:8000/docs'

Swagger UI allows you to execute API requests, enter JSON request bodies, provide authentication tokens, and inspect responses.

# Authentication Workflow

1. Run the initial administrator setup endpoint if the database has not been initialized with an administrator.
2. Register a customer or create an agent using the available endpoints.
3. Log in using the required credentials.
4. Copy the access token returned by the login endpoint.
5. Click **Authorize** in Swagger UI and enter the token using the format required by the configured HTTP Bearer authentication.
6. Execute protected endpoints according to the user's role.

Do not share access tokens or passwords in screenshots or public repositories.

# Ticket Workflow

1. A customer creates a ticket with a category, subject, description, and priority.
2. The application calculates SLA deadlines using the configured policy.
3. The assignment service searches for an eligible agent based on availability, category, and open-ticket limits.
4. The assigned agent works on the ticket through the supported status workflow.
5. Ticket status changes and other relevant actions are recorded in the history.
6. Customers and agents retrieve ticket information through the available APIs.
7. Scheduled jobs and notification features operate according to the application's configuration.

Ticket assignment and status transitions depend on the implemented business rules and must be verified through API testing.

# Testing

Use Swagger UI at 'http://127.0.0.1:8000/docs' to test the application.

Recommended testing areas:
- Customer registration and login.
- JWT authentication and role-based access.
- Category and SLA configuration.
- Agent creation and availability.
- Ticket creation and automatic assignment.
- Ticket listing and detail retrieval.
- Valid and invalid status transitions.
- Ticket history and reopening.
- WebSocket communication.
- Notifications and read status.
- SLA monitoring and escalation.
- File uploads and email notifications, if implemented.

Record the HTTP status codes and response bodies. Capture screenshots of successful tests and document any errors found during testing.

# Security Considerations
- Store passwords as secure hashes rather than plain text.
- Keep secret keys and database credentials in environment variables.
- Protect restricted endpoints using authentication and role checks.
- Validate request data and uploaded files.
- Avoid exposing sensitive information in API responses and logs.
- Use HTTPS and secure deployment settings in production.

# Conclusion
The Real-Time Support Ticket System provides a foundation for managing customer support requests using FastAPI and MySQL. It brings together authentication, ticket management, agent availability, SLA tracking, and real-time communication in a modular backend application.

The project can be further improved through comprehensive API testing, automated tests, security reviews, and verification of all assignment requirements.


