# Bukka AI API Documentation

This document provides a detailed reference for all API endpoints available in the Bukka AI system.

## Table of Contents

- [Authentication](#authentication)
- [Admin Endpoints](#admin-endpoints)
- [Webhook Endpoints](#webhook-endpoints)
- [Demo Endpoints](#demo-endpoints)
- [General Endpoints](#general-endpoints)

---

## Authentication

Several endpoints are protected and require specific headers for authentication or verification.

- **WhatsApp Webhooks:** Require an `X-Hub-Signature-256` header for HMAC-SHA256 signature verification.
- **Telegram Webhooks:** Require an `X-Telegram-Bot-Api-Secret-Token` header.
- **Admin Actions:** Certain administrative actions, like resetting demo data, require an `X-Admin-Reset-Token`.

These tokens and secrets are configured via environment variables.

---

## Admin Endpoints

These endpoints are used for administrative tasks like vendor management.

### Onboard New Vendor

- **`POST /api/v1/admin/onboard`**

  Onboards a new vendor, creates a unique vendor ID, generates a WhatsApp click-to-chat QR code, and saves it to the static directory.

  **Request Body:**

  ```json
  {
    "vendor_name": "Mama J's Kitchen",
    "phone_number": "2348012345678"
  }
  ```

  **Successful Response (201):**

  ```json
  {
    "detail": "Vendor onboarded successfully.",
    "vendor_id": "VEN-A1B2C3D4",
    "qr_image_url": "/static/qr_codes/VEN-A1B2C3D4.png"
  }
  ```

---

## Webhook Endpoints

These endpoints are the entry points for incoming messages from messaging platforms.

### WhatsApp Webhook Verification

- **`GET /api/v1/webhook`**

  Used by Meta to verify the webhook endpoint during setup. The endpoint must echo back the `hub.challenge` value if the `hub.verify_token` is valid.

  **Query Parameters:**

  - `hub.mode`: Should be `"subscribe"`.
  - `hub.verify_token`: Your secret verification token.
  - `hub.challenge`: A random string to be echoed back.

  **Successful Response (200):**

  - The `hub.challenge` string as plain text.

### Receive WhatsApp Message

- **`POST /api/v1/webhook`**

  Receives incoming messages and status updates from the WhatsApp Cloud API. The request body is signed with HMAC-SHA256 using your App Secret.

  **Headers:**

  - `X-Hub-Signature-256`: `sha256=<signature>`

  **Request Body:**

  - A complex JSON object from the Meta Graph API. See Meta's documentation for the full schema.

  **Successful Response (200):**

  The endpoint immediately returns a `200 OK` and processes the message in the background to avoid timeouts.

  ```json
  {
    "status": "received"
  }
  ```

### Receive Telegram Message

- **`POST /api/v1/telegram/webhook`**

  Receives incoming messages and updates from the Telegram Bot API.

  **Headers:**

  - `X-Telegram-Bot-Api-Secret-Token`: Your secret webhook token.

  **Request Body:**

  - A JSON object from the Telegram Bot API representing an `Update`.

  **Successful Response (200):**

  ```json
  {
    "status": "ok"
  }
  ```

---

## Demo Endpoints

These endpoints are for demonstration and testing purposes.

### Get Demo Chats

- **`GET /api/v1/demo/chats`**

  Retrieves the last 50 messages from the database for display on a demo frontend.

  **Successful Response (200):**

  An array of message objects.

### Reset Demo Chats

- **`POST /api/v1/demo/reset`**

  Deletes all messages from the `messages` table to reset the demo state. This is a destructive action protected by a token.

  **Headers:**

  - `X-Admin-Reset-Token`: Your secret admin token.

  **Successful Response (200):**

  ```json
  {
    "status": "cleared"
  }
  ```

---

## General Endpoints

### Root / Health Check

- **`GET /`**

  A simple endpoint to confirm that the API server is online and running.

  **Successful Response (200):**

  ```json
  {
    "status": "Bukka AI System Online 🚀"
  }
  ```